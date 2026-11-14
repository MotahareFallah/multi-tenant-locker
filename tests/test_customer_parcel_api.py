from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django_tenants.utils import tenant_context
from rest_framework.test import APIClient

from lockers.models import Compartment, CompartmentSize, Locker
from organizations.models import Role
from organizations.services import add_member
from parcels.services import create_parcel, deposit_parcel

pytestmark = pytest.mark.django_db(transaction=True)

ALICE = "+989123456781"
BOB = "+989123456782"
STAFF = "+989120000001"

CUSTOMER_FIELDS = {
    "tracking_code",
    "locker",
    "compartment",
    "size",
    "status",
    "expires_at",
    "created_at",
}


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def get(client, org, path):
    return client.get(f"/api/v1/orgs/{org}/my/{path}")


def parcel_for(locker, phone):
    return create_parcel(
        locker=locker, recipient_phone=phone, size=CompartmentSize.SMALL, actor="test"
    )


def make_locker(organization, with_compartment=False):
    with tenant_context(organization):
        locker = Locker.objects.create(code="main", name="Main hall")
        if with_compartment:
            Compartment.objects.create(
                locker=locker, number=1, size=CompartmentSize.SMALL
            )
    return locker


@pytest.fixture
def world(make_org):
    users = get_user_model().objects
    acme = make_org("acme")
    globex = make_org("globex")
    alice = users.create(phone_number=ALICE)
    bob = users.create(phone_number=BOB)
    staff = users.create(phone_number=STAFF)
    add_member(organization=acme, user=staff, role=Role.ADMIN)

    locker = make_locker(acme, with_compartment=True)
    with tenant_context(acme):
        first = parcel_for(locker, ALICE)
        second = parcel_for(locker, ALICE)
        deposit_parcel(second.pk, actor="test")
        bobs = parcel_for(locker, BOB)
        codes = SimpleNamespace(
            first=first.tracking_code,
            second=second.tracking_code,
            bobs=bobs.tracking_code,
        )

    other_locker = make_locker(globex)
    with tenant_context(globex):
        codes.elsewhere = parcel_for(other_locker, ALICE).tracking_code

    return SimpleNamespace(alice=alice, bob=bob, staff=staff, codes=codes)


def listed_codes(response):
    return [item["tracking_code"] for item in response.json()["results"]]


def test_a_customer_lists_only_their_own_parcels(world):
    response = get(client_for(world.alice), "acme", "parcels/")
    assert response.status_code == 200
    assert set(listed_codes(response)) == {world.codes.first, world.codes.second}


def test_the_newest_parcel_comes_first(world):
    response = get(client_for(world.alice), "acme", "parcels/")
    assert listed_codes(response) == [world.codes.second, world.codes.first]


def test_a_listed_parcel_shows_only_customer_fields(world):
    response = get(client_for(world.alice), "acme", "parcels/")
    for item in response.json()["results"]:
        assert set(item) == CUSTOMER_FIELDS


def test_a_customer_reads_their_parcel(world):
    response = get(client_for(world.alice), "acme", f"parcels/{world.codes.second}/")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == CUSTOMER_FIELDS
    assert body["status"] == "STORED"
    assert body["locker"] == "main"
    assert body["compartment"] == 1


def test_a_parcel_without_a_compartment_has_none(world):
    response = get(client_for(world.alice), "acme", f"parcels/{world.codes.first}/")
    assert response.json()["compartment"] is None
    assert response.json()["status"] == "CREATED"


def test_the_parcel_of_somebody_else_looks_like_one_that_does_not_exist(world):
    client = client_for(world.alice)
    others = get(client, "acme", f"parcels/{world.codes.bobs}/")
    missing = get(client, "acme", "parcels/0000000000000000/")
    assert others.status_code == missing.status_code == 404
    assert others.json() == missing.json()


def test_a_staff_member_who_is_not_the_recipient_sees_nothing(world):
    client = client_for(world.staff)
    assert get(client, "acme", "parcels/").json()["results"] == []
    assert get(client, "acme", f"parcels/{world.codes.first}/").status_code == 404


def test_parcels_of_another_organization_are_not_mixed_in(world):
    client = client_for(world.alice)
    in_acme = listed_codes(get(client, "acme", "parcels/"))
    in_globex = listed_codes(get(client, "globex", "parcels/"))
    assert world.codes.elsewhere not in in_acme
    assert in_globex == [world.codes.elsewhere]
    assert get(client, "globex", f"parcels/{world.codes.first}/").status_code == 404


def test_an_unknown_organization_is_not_found(world):
    assert get(client_for(world.alice), "nowhere", "parcels/").status_code == 404


def test_anonymous_callers_are_refused(world):
    assert get(APIClient(), "acme", "parcels/").status_code == 401
    detail = get(APIClient(), "acme", f"parcels/{world.codes.first}/")
    assert detail.status_code == 401


def test_customers_cannot_create_parcels(world):
    response = client_for(world.alice).post(
        "/api/v1/orgs/acme/my/parcels/", {}, format="json"
    )
    assert response.status_code == 405


def test_the_schema_is_public_after_a_customer_request(world):
    get(client_for(world.alice), "acme", "parcels/")
    assert connection.schema_name == "public"
