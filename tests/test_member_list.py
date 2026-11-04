import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from organizations.models import Membership, Organization, Role
from organizations.services import add_member

pytestmark = pytest.mark.django_db

URL = "/api/v1/orgs/acme/members/"


def make_user(number, full_name=""):
    return get_user_model().objects.create(
        phone_number=f"+98912000{number:04d}", full_name=full_name
    )


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


@pytest.fixture
def acme():
    return make_org("acme")


@pytest.fixture
def admin(acme):
    user = make_user(1, "Ali Admin")
    add_member(organization=acme, user=user, role=Role.ADMIN)
    return user


def test_an_admin_lists_the_members_with_only_the_expected_fields(acme, admin):
    operator = make_user(2, "Omid Operator")
    add_member(organization=acme, user=operator, role=Role.OPERATOR)
    response = client_for(admin).get(URL)
    assert response.status_code == 200
    body = response.json()
    assert [m["phone_number"] for m in body] == ["+989120000001", "+989120000002"]
    assert [m["role"] for m in body] == ["admin", "operator"]
    assert body[0]["full_name"] == "Ali Admin"
    assert set(body[0]) == {
        "id",
        "phone_number",
        "full_name",
        "role",
        "is_active",
        "created_at",
    }


def test_inactive_members_are_listed_and_marked(acme, admin):
    former = make_user(2)
    membership = add_member(organization=acme, user=former, role=Role.OPERATOR)
    Membership.objects.filter(pk=membership.pk).update(is_active=False)
    body = client_for(admin).get(URL).json()
    assert {m["phone_number"]: m["is_active"] for m in body} == {
        "+989120000001": True,
        "+989120000002": False,
    }


def test_members_of_other_organizations_are_not_listed(acme, admin):
    other = make_user(3)
    add_member(organization=make_org("globex"), user=other, role=Role.ADMIN)
    body = client_for(admin).get(URL).json()
    assert [m["phone_number"] for m in body] == ["+989120000001"]


def test_an_operator_is_forbidden(acme):
    operator = make_user(2)
    add_member(organization=acme, user=operator, role=Role.OPERATOR)
    assert client_for(operator).get(URL).status_code == 403


def test_a_non_member_gets_a_404(acme, admin):
    assert client_for(make_user(3)).get(URL).status_code == 404


def test_an_anonymous_request_gets_a_401(acme):
    assert APIClient().get(URL).status_code == 401


def test_members_are_listed_in_the_order_they_joined(acme, admin):
    for number in (5, 4, 6):
        add_member(organization=acme, user=make_user(number), role=Role.OPERATOR)
    phones = [m["phone_number"] for m in client_for(admin).get(URL).json()]
    assert phones == [
        "+989120000001",
        "+989120000005",
        "+989120000004",
        "+989120000006",
    ]
