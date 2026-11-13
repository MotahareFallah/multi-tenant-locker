import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.urls import path
from django_tenants.utils import tenant_context
from rest_framework.response import Response
from rest_framework.test import APIClient
from rest_framework.views import APIView

from organizations.models import Role
from organizations.services import add_member
from organizations.views import CustomerTenantMixin


class ProbeView(CustomerTenantMixin, APIView):
    def get(self, request, slug):
        models = ContentType.objects.filter(app_label="probe").order_by("model")
        return Response({"models": list(models.values_list("model", flat=True))})


class LazyProbeView(CustomerTenantMixin, APIView):
    def get(self, request, slug):
        # Left lazy on purpose: it is only evaluated when the response is rendered.
        models = ContentType.objects.filter(app_label="probe").order_by("model")
        return Response({"models": models.values_list("model", flat=True)})


class WhoView(CustomerTenantMixin, APIView):
    def get(self, request, slug):
        return Response(
            {
                "has_membership": hasattr(request, "membership"),
                "tenant": request.tenant.slug,
            }
        )


class BoomView(CustomerTenantMixin, APIView):
    def get(self, request, slug):
        raise RuntimeError("boom")


urlpatterns = [
    path("api/v1/orgs/<slug:slug>/my/probe/", ProbeView.as_view()),
    path("api/v1/orgs/<slug:slug>/my/lazy/", LazyProbeView.as_view()),
    path("api/v1/orgs/<slug:slug>/my/who/", WhoView.as_view()),
    path("api/v1/orgs/<slug:slug>/my/boom/", BoomView.as_view()),
]

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.urls(__name__),
]


def client_for(user, **kwargs):
    client = APIClient(**kwargs)
    client.force_authenticate(user)
    return client


@pytest.fixture
def world(make_org):
    users = get_user_model().objects
    acme, globex = make_org("acme"), make_org("globex")
    for organization, model in ((acme, "a"), (globex, "b")):
        with tenant_context(organization):
            ContentType.objects.create(app_label="probe", model=model)
    customer = users.create(phone_number="+989120000001")
    admin = users.create(phone_number="+989120000002")
    add_member(organization=acme, user=admin, role=Role.ADMIN)
    return customer, admin


def test_a_signed_in_user_without_membership_reaches_the_schema_by_slug(world):
    customer, _ = world
    in_acme = client_for(customer).get("/api/v1/orgs/acme/my/probe/")
    in_globex = client_for(customer).get("/api/v1/orgs/globex/my/probe/")
    assert in_acme.json() == {"models": ["a"]}
    assert in_globex.json() == {"models": ["b"]}


def test_an_unknown_slug_is_a_404(world):
    customer, _ = world
    assert client_for(customer).get("/api/v1/orgs/nope/my/probe/").status_code == 404


def test_anonymous_callers_are_refused(world):
    assert APIClient().get("/api/v1/orgs/acme/my/probe/").status_code == 401


def test_there_is_no_membership_and_no_role_on_this_path(world):
    customer, admin = world
    for user in (customer, admin):
        body = client_for(user).get("/api/v1/orgs/acme/my/who/").json()
        assert body == {"has_membership": False, "tenant": "acme"}


def test_the_connection_goes_back_to_public(world):
    customer, _ = world
    client_for(customer).get("/api/v1/orgs/acme/my/probe/")
    assert connection.schema_name == "public"
    assert ContentType.objects.filter(app_label="probe").count() == 0


def test_lazy_data_is_read_in_the_right_schema(world):
    customer, _ = world
    response = client_for(customer).get("/api/v1/orgs/globex/my/lazy/")
    assert response.json() == {"models": ["b"]}


def test_an_error_still_resets_the_schema(world):
    customer, _ = world
    client = client_for(customer, raise_request_exception=False)
    assert client.get("/api/v1/orgs/acme/my/boom/").status_code == 500
    assert connection.schema_name == "public"
