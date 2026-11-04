import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.urls import path
from rest_framework import serializers
from rest_framework.generics import ListAPIView
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.test import APIClient
from rest_framework.views import APIView

from organizations.models import Membership, Organization, Role
from organizations.permissions import IsOrgAdmin, IsOrgMember
from organizations.services import add_member
from organizations.views import TenantAPIView, TenantViewMixin

seen = []
handled = []


class Recorder(BasePermission):
    def has_permission(self, request, view):
        seen.append((connection.schema_name, request.membership.role))
        return True


class AdminOnlyView(TenantAPIView):
    permission_classes = [IsOrgAdmin]

    def get(self, request, slug):
        return Response({"ok": True})


class MemberView(TenantAPIView):
    permission_classes = [IsOrgMember]

    def get(self, request, slug):
        return Response({"ok": True})


class GuardedView(TenantAPIView):
    permission_classes = [Recorder, IsOrgAdmin]

    def get(self, request, slug):
        handled.append(connection.schema_name)
        return Response({"ok": True})


class ProbeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContentType
        fields = ["model"]


class ListProbeView(TenantViewMixin, ListAPIView):
    queryset = ContentType.objects.filter(app_label="probe").order_by("model")
    serializer_class = ProbeSerializer


class NoMixinView(APIView):
    permission_classes = [IsOrgAdmin]

    def get(self, request, slug):
        return Response({"ok": True})


urlpatterns = [
    path("api/v1/orgs/<slug:slug>/admin-only/", AdminOnlyView.as_view()),
    path("api/v1/orgs/<slug:slug>/member/", MemberView.as_view()),
    path("api/v1/orgs/<slug:slug>/guarded/", GuardedView.as_view()),
    path("api/v1/orgs/<slug:slug>/list/", ListProbeView.as_view()),
    path("api/v1/orgs/<slug:slug>/no-mixin/", NoMixinView.as_view()),
]

pytestmark = [pytest.mark.django_db, pytest.mark.urls(__name__)]


@pytest.fixture(autouse=True)
def clear_records():
    seen.clear()
    handled.clear()


def make_user(number):
    return get_user_model().objects.create(phone_number=f"+98912000{number:04d}")


def make_org(slug):
    # Only the row: these tests are about access, not about schemas.
    organization = Organization(name=slug, slug=slug, schema_name=f"org_{slug}")
    organization.auto_create_schema = False
    organization.save()
    return organization


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def member(role, number=1):
    user = make_user(number)
    membership = add_member(organization=make_org("acme"), user=user, role=role)
    return client_for(user), membership


def test_an_admin_passes_an_admin_only_view():
    client, _ = member(Role.ADMIN)
    assert client.get("/api/v1/orgs/acme/admin-only/").status_code == 200


def test_an_operator_is_forbidden_on_an_admin_only_view():
    client, _ = member(Role.OPERATOR)
    assert client.get("/api/v1/orgs/acme/admin-only/").status_code == 403


def test_an_operator_passes_a_member_view():
    client, _ = member(Role.OPERATOR)
    assert client.get("/api/v1/orgs/acme/member/").status_code == 200


def test_an_admin_passes_a_member_view():
    client, _ = member(Role.ADMIN)
    assert client.get("/api/v1/orgs/acme/member/").status_code == 200


def test_a_non_member_gets_a_404_not_a_403():
    member(Role.ADMIN)
    outsider = client_for(make_user(2))
    assert outsider.get("/api/v1/orgs/acme/admin-only/").status_code == 404
    assert outsider.get("/api/v1/orgs/missing/admin-only/").status_code == 404


def test_an_anonymous_request_gets_a_401():
    make_org("acme")
    assert APIClient().get("/api/v1/orgs/acme/admin-only/").status_code == 401


def test_a_role_change_applies_to_the_next_request():
    client, membership = member(Role.ADMIN)
    assert client.get("/api/v1/orgs/acme/admin-only/").status_code == 200
    Membership.objects.filter(pk=membership.pk).update(role=Role.OPERATOR)
    assert client.get("/api/v1/orgs/acme/admin-only/").status_code == 403


def test_a_deactivated_membership_applies_to_the_next_request():
    client, membership = member(Role.ADMIN)
    assert client.get("/api/v1/orgs/acme/member/").status_code == 200
    Membership.objects.filter(pk=membership.pk).update(is_active=False)
    assert client.get("/api/v1/orgs/acme/member/").status_code == 404


def test_permissions_run_on_public_with_the_membership_available():
    client, _ = member(Role.ADMIN)
    assert client.get("/api/v1/orgs/acme/guarded/").status_code == 200
    assert seen == [("public", "admin")]
    assert handled == ["org_acme"]


def test_a_denied_request_never_activates_the_tenant_schema():
    client, _ = member(Role.OPERATOR)
    assert client.get("/api/v1/orgs/acme/guarded/").status_code == 403
    assert seen == [("public", "operator")]
    assert handled == []
    assert connection.schema_name == "public"


def test_the_mixin_composes_with_generic_views():
    client, _ = member(Role.OPERATOR)
    response = client.get("/api/v1/orgs/acme/list/")
    assert response.status_code == 200
    assert response.json() == []
    outsider = client_for(make_user(2))
    assert outsider.get("/api/v1/orgs/acme/list/").status_code == 404


def test_a_role_permission_without_the_mixin_fails_closed():
    client, _ = member(Role.ADMIN)
    assert client.get("/api/v1/orgs/acme/no-mixin/").status_code == 403
