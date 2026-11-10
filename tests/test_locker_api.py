from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django_tenants.utils import tenant_context
from rest_framework.test import APIClient

from lockers.models import Compartment, CompartmentSize, Locker
from organizations.models import Role
from organizations.services import add_member

pytestmark = pytest.mark.django_db(transaction=True)

BASE = "/api/v1/orgs/acme/"

ENDPOINTS = [
    ("get", "lockers/"),
    ("post", "lockers/"),
    ("get", "lockers/main/"),
    ("patch", "lockers/main/"),
    ("post", "lockers/main/compartments/"),
    ("get", "lockers/main/compartments/1/"),
    ("patch", "lockers/main/compartments/1/"),
]


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def call(client, method, path, data=None):
    if method == "get":
        return client.get(BASE + path)
    return getattr(client, method)(BASE + path, data or {}, format="json")


@pytest.fixture
def staff(make_org):
    users = get_user_model().objects
    organization = make_org("acme")
    admin = users.create(phone_number="+989120000001")
    operator = users.create(phone_number="+989120000002")
    outsider = users.create(phone_number="+989120000003")
    add_member(organization=organization, user=admin, role=Role.ADMIN)
    add_member(organization=organization, user=operator, role=Role.OPERATOR)
    with tenant_context(organization):
        locker = Locker.objects.create(code="main", name="Main hall")
        Compartment.objects.create(locker=locker, number=1, size=CompartmentSize.SMALL)
    return SimpleNamespace(
        org=organization,
        admin=client_for(admin),
        operator=client_for(operator),
        outsider=client_for(outsider),
        anonymous=APIClient(),
    )


# Who may call what


@pytest.mark.parametrize("method, path", ENDPOINTS)
def test_anonymous_callers_are_refused(staff, method, path):
    assert call(staff.anonymous, method, path).status_code == 401


@pytest.mark.parametrize("method, path", ENDPOINTS)
def test_non_members_see_a_404(staff, method, path):
    assert call(staff.outsider, method, path).status_code == 404


@pytest.mark.parametrize("method, path", ENDPOINTS)
def test_operators_get_a_403(staff, method, path):
    assert call(staff.operator, method, path).status_code == 403


# Lockers


def test_an_admin_creates_a_locker(staff):
    response = call(
        staff.admin,
        "post",
        "lockers/",
        {"code": "north", "name": "North", "address": "1 Main St"},
    )
    assert response.status_code == 201
    body = response.json()
    assert (body["code"], body["name"], body["address"], body["is_active"]) == (
        "north",
        "North",
        "1 Main St",
        True,
    )
    with tenant_context(staff.org):
        assert Locker.objects.filter(code="north").exists()


@pytest.mark.parametrize(
    "data",
    [
        {"code": "main", "name": "Duplicate"},
        {"code": "Bad Code!", "name": "Bad"},
        {"code": "nameless"},
    ],
)
def test_invalid_lockers_are_rejected(staff, data):
    assert call(staff.admin, "post", "lockers/", data).status_code == 400


def test_the_locker_list_is_paginated_and_ordered_by_code(staff):
    with tenant_context(staff.org):
        Locker.objects.bulk_create(
            [Locker(code=f"l{i:03d}", name="x") for i in range(51)]
        )
    first = call(staff.admin, "get", "lockers/").json()
    assert first["count"] == 52
    assert len(first["results"]) == 50
    assert first["next"] is not None
    codes = [item["code"] for item in first["results"]]
    assert codes == sorted(codes)
    second = staff.admin.get(first["next"]).json()
    assert len(second["results"]) == 2


def test_a_locker_shows_its_compartments_in_order(staff):
    with tenant_context(staff.org):
        Compartment.objects.create(
            locker=Locker.objects.get(code="main"),
            number=2,
            size=CompartmentSize.LARGE,
        )
    body = call(staff.admin, "get", "lockers/main/").json()
    assert body["compartments"] == [
        {"number": 1, "size": "SMALL", "is_active": True},
        {"number": 2, "size": "LARGE", "is_active": True},
    ]


def test_an_unknown_locker_is_a_404(staff):
    assert call(staff.admin, "get", "lockers/nope/").status_code == 404


def test_a_locker_can_be_renamed_and_switched_off_but_keeps_its_code(staff):
    response = call(
        staff.admin,
        "patch",
        "lockers/main/",
        {"name": "Renamed", "is_active": False, "code": "other"},
    )
    assert response.status_code == 200
    with tenant_context(staff.org):
        locker = Locker.objects.get(code="main")
        assert (locker.name, locker.is_active) == ("Renamed", False)
        assert not Locker.objects.filter(code="other").exists()


@pytest.mark.parametrize("method", ["put", "delete"])
def test_a_locker_cannot_be_replaced_or_deleted(staff, method):
    assert call(staff.admin, method, "lockers/main/").status_code == 405


# Compartments


def test_an_admin_adds_a_compartment(staff):
    response = call(
        staff.admin,
        "post",
        "lockers/main/compartments/",
        {"number": 2, "size": "LARGE"},
    )
    assert response.status_code == 201
    assert response.json() == {"number": 2, "size": "LARGE", "is_active": True}


@pytest.mark.parametrize(
    "data",
    [
        {"number": 1, "size": "SMALL"},  # already exists
        {"number": 0, "size": "SMALL"},
        {"number": 3, "size": "HUGE"},
    ],
)
def test_invalid_compartments_are_rejected(staff, data):
    response = call(staff.admin, "post", "lockers/main/compartments/", data)
    assert response.status_code == 400


def test_a_compartment_needs_an_existing_locker(staff):
    response = call(
        staff.admin,
        "post",
        "lockers/nope/compartments/",
        {"number": 1, "size": "SMALL"},
    )
    assert response.status_code == 404


def test_a_compartment_can_be_read(staff):
    response = call(staff.admin, "get", "lockers/main/compartments/1/")
    assert response.json() == {"number": 1, "size": "SMALL", "is_active": True}


def test_a_compartment_can_be_switched_off_but_not_resized(staff):
    response = call(
        staff.admin,
        "patch",
        "lockers/main/compartments/1/",
        {"is_active": False, "size": "LARGE", "number": 9},
    )
    assert response.status_code == 200
    assert response.json() == {"number": 1, "size": "SMALL", "is_active": False}


def test_a_compartment_update_needs_the_switch(staff):
    response = call(staff.admin, "patch", "lockers/main/compartments/1/", {})
    assert response.status_code == 400


def test_an_unknown_compartment_is_a_404(staff):
    assert call(staff.admin, "get", "lockers/main/compartments/9/").status_code == 404


# Isolation


def test_lockers_are_isolated_between_organizations(staff, make_org):
    other = make_org("globex")
    with tenant_context(other):
        Locker.objects.create(code="secret", name="Secret")
    listed = call(staff.admin, "get", "lockers/").json()["results"]
    assert [item["code"] for item in listed] == ["main"]
    assert call(staff.admin, "get", "lockers/secret/").status_code == 404
    assert staff.admin.get("/api/v1/orgs/globex/lockers/").status_code == 404
