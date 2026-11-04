import itertools
import threading
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.urls import path
from django_tenants.utils import tenant_context
from rest_framework.response import Response
from rest_framework.test import APIClient

from organizations.models import Role
from organizations.services import add_member, create_organization
from organizations.views import TenantAPIView


class ProbeView(TenantAPIView):
    def get(self, request, slug):
        models = ContentType.objects.filter(app_label="probe").order_by("model")
        return Response({"models": list(models.values_list("model", flat=True))})


class LazyProbeView(TenantAPIView):
    def get(self, request, slug):
        # Left lazy on purpose: it is only evaluated when the response is rendered.
        models = ContentType.objects.filter(app_label="probe").order_by("model")
        return Response({"models": models.values_list("model", flat=True)})


class BoomView(TenantAPIView):
    def get(self, request, slug):
        raise RuntimeError("boom")


urlpatterns = [
    path("api/v1/orgs/<slug:slug>/probe/", ProbeView.as_view()),
    path("api/v1/orgs/<slug:slug>/lazy/", LazyProbeView.as_view()),
    path("api/v1/orgs/<slug:slug>/boom/", BoomView.as_view()),
]

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.urls(__name__),
]


@pytest.fixture
def make_org():
    created = []

    def make(slug):
        organization = create_organization(name=slug, slug=slug)
        created.append(organization)
        return organization

    yield make
    for organization in created:
        organization.delete(force_drop=True)


@pytest.fixture
def two_orgs(make_org):
    alice = get_user_model().objects.create(phone_number="+989120000001")
    bob = get_user_model().objects.create(phone_number="+989120000002")
    org_a, org_b = make_org("acme"), make_org("globex")
    add_member(organization=org_a, user=alice, role=Role.ADMIN)
    add_member(organization=org_b, user=bob, role=Role.OPERATOR)
    for organization, model in ((org_a, "a"), (org_b, "b")):
        with tenant_context(organization):
            ContentType.objects.create(app_label="probe", model=model)
    return SimpleNamespace(alice=alice, bob=bob, a=org_a, b=org_b)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_each_member_sees_only_their_own_organizations_rows(two_orgs):
    alice = client_for(two_orgs.alice).get("/api/v1/orgs/acme/probe/")
    bob = client_for(two_orgs.bob).get("/api/v1/orgs/globex/probe/")
    assert alice.json() == {"models": ["a"]}
    assert bob.json() == {"models": ["b"]}


def test_tenant_rows_are_not_in_the_public_schema(two_orgs):
    client_for(two_orgs.alice).get("/api/v1/orgs/acme/probe/")
    assert connection.schema_name == "public"
    assert ContentType.objects.filter(app_label="probe").count() == 0


def test_a_member_of_one_organization_cannot_read_another(two_orgs):
    response = client_for(two_orgs.alice).get("/api/v1/orgs/globex/probe/")
    assert response.status_code == 404
    assert b'"b"' not in response.content


def test_lazy_data_is_evaluated_in_the_tenant_schema(two_orgs):
    response = client_for(two_orgs.alice).get("/api/v1/orgs/acme/lazy/")
    assert response.json() == {"models": ["a"]}


def test_the_schema_is_public_after_an_unhandled_error(two_orgs):
    with pytest.raises(RuntimeError):
        client_for(two_orgs.alice).get("/api/v1/orgs/acme/boom/")
    assert connection.schema_name == "public"


def test_forged_headers_cannot_select_a_schema(two_orgs, settings):
    settings.ALLOWED_HOSTS = ["*"]
    forged = {
        "HTTP_HOST": f"{two_orgs.b.schema_name.replace('_', '-')}.example.com",
        "HTTP_X_FORWARDED_HOST": f"{two_orgs.b.schema_name.replace('_', '-')}.example.com",
        "HTTP_X_FORWARDED_FOR": "203.0.113.9",
        "HTTP_X_ORGANIZATION": "globex",
        "HTTP_X_TENANT": two_orgs.b.schema_name,
    }
    client = client_for(two_orgs.alice)
    # Pointing the headers at another organization does not grant access to it...
    assert client.get("/api/v1/orgs/globex/probe/", **forged).status_code == 404
    # ...and does not change which schema her own URL uses.
    own = client.get("/api/v1/orgs/acme/probe/", **forged)
    assert own.json() == {"models": ["a"]}


def test_concurrent_requests_never_see_another_organizations_rows(
    run_concurrently, two_orgs
):
    callers = [(two_orgs.alice, "acme", ["a"]), (two_orgs.bob, "globex", ["b"])]
    counter = itertools.count()
    lock = threading.Lock()

    def worker():
        with lock:
            user, slug, expected = callers[next(counter) % 2]
        client = client_for(user)
        mismatches = []
        for _ in range(10):
            body = client.get(f"/api/v1/orgs/{slug}/probe/").json()
            if body != {"models": expected}:
                mismatches.append(body)
        return mismatches

    results = run_concurrently(worker, 12)
    assert [error for _, error in results if error is not None] == []
    assert [mismatches for mismatches, _ in results if mismatches] == []
