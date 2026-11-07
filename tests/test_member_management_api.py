import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from organizations.models import Membership, Organization, Role
from organizations.services import add_member

pytestmark = pytest.mark.django_db

User = get_user_model()
LIST = "/api/v1/orgs/acme/members/"
PHONE = "09123456789"


def make_org(slug):
    # Only the row: these tests are about the API, not about schemas.
    organization = Organization(name=slug, slug=slug, schema_name=f"org_{slug}")
    organization.auto_create_schema = False
    organization.save()
    return organization


def make_user(number):
    return User.objects.create(phone_number=f"+98912000{number:04d}")


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def acme():
    return make_org("acme")


@pytest.fixture
def admin(acme):
    user = make_user(1)
    membership = add_member(organization=acme, user=user, role=Role.ADMIN)
    return SimpleAdmin(client_for(user), membership)


class SimpleAdmin:
    def __init__(self, client, membership):
        self.client = client
        self.membership = membership


def detail(membership):
    return f"/api/v1/orgs/acme/members/{membership.pk}/"


def operator_in(acme, number=2):
    return add_member(organization=acme, user=make_user(number), role=Role.OPERATOR)


def post(client, **body):
    return client.post(LIST, body, format="json")


def test_an_admin_adds_a_member_by_phone(admin):
    response = post(admin.client, phone_number=PHONE, role="operator")
    assert response.status_code == 201
    body = response.json()
    assert body["phone_number"] == "+989123456789"
    assert body["role"] == "operator"
    assert body["is_active"] is True
    assert User.objects.filter(phone_number="+989123456789").exists()


def test_persian_digits_are_accepted(admin):
    response = post(admin.client, phone_number="۰۹۱۲۳۴۵۶۷۸۹", role="operator")
    assert response.status_code == 201
    assert response.json()["phone_number"] == "+989123456789"


def test_an_invalid_phone_number_is_a_400_and_creates_nothing(admin):
    response = post(admin.client, phone_number="12345", role="operator")
    assert response.status_code == 400
    assert User.objects.count() == 1


def test_an_unknown_role_is_a_400(admin):
    assert post(admin.client, phone_number=PHONE, role="owner").status_code == 400


def test_adding_an_active_member_twice_is_a_400(admin):
    assert post(admin.client, phone_number=PHONE, role="operator").status_code == 201
    assert post(admin.client, phone_number=PHONE, role="operator").status_code == 400


def test_a_former_member_comes_back_active_with_the_new_role(admin, acme):
    former = operator_in(acme)
    admin.client.patch(detail(former), {"is_active": False}, format="json")
    phone = User.objects.get(pk=former.user_id).phone_number
    response = post(admin.client, phone_number=phone, role="admin")
    assert response.status_code == 201
    body = response.json()
    assert (body["id"], body["role"], body["is_active"]) == (former.pk, "admin", True)


def test_only_admins_can_add_members(acme, admin):
    operator = add_member(organization=acme, user=make_user(2), role=Role.OPERATOR)
    outsider = client_for(make_user(3))
    body = {"phone_number": PHONE, "role": "operator"}
    assert client_for(operator.user).post(LIST, body, format="json").status_code == 403
    assert outsider.post(LIST, body, format="json").status_code == 404
    assert APIClient().post(LIST, body, format="json").status_code == 401


def test_an_admin_changes_a_role(admin, acme):
    operator = operator_in(acme)
    response = admin.client.patch(detail(operator), {"role": "admin"}, format="json")
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_an_admin_deactivates_and_reactivates_a_member(admin, acme):
    operator = operator_in(acme)
    off = admin.client.patch(detail(operator), {"is_active": False}, format="json")
    assert off.json()["is_active"] is False
    on = admin.client.patch(detail(operator), {"is_active": True}, format="json")
    assert on.json()["is_active"] is True


def test_the_last_admin_cannot_be_demoted_or_deactivated(admin):
    url = detail(admin.membership)
    assert admin.client.patch(url, {"role": "operator"}, format="json").status_code == 409
    assert admin.client.patch(url, {"is_active": False}, format="json").status_code == 409
    membership = Membership.objects.get(pk=admin.membership.pk)
    assert (membership.role, membership.is_active) == (Role.ADMIN, True)


def test_an_admin_can_demote_themselves_when_another_admin_remains(admin, acme):
    add_member(organization=acme, user=make_user(2), role=Role.ADMIN)
    response = admin.client.patch(
        detail(admin.membership), {"role": "operator"}, format="json"
    )
    assert response.status_code == 200


def test_an_empty_update_is_a_400(admin, acme):
    operator = operator_in(acme)
    assert admin.client.patch(detail(operator), {}, format="json").status_code == 400


def test_a_member_of_another_organization_is_a_404(admin):
    other = add_member(
        organization=make_org("globex"), user=make_user(5), role=Role.OPERATOR
    )
    response = admin.client.patch(detail(other), {"role": "admin"}, format="json")
    assert response.status_code == 404
    assert Membership.objects.get(pk=other.pk).role == Role.OPERATOR


def test_an_unknown_member_is_a_404(admin):
    url = "/api/v1/orgs/acme/members/999999/"
    assert admin.client.patch(url, {"role": "admin"}, format="json").status_code == 404


def test_an_operator_cannot_change_members(admin, acme):
    operator = operator_in(acme)
    response = client_for(operator.user).patch(
        detail(admin.membership), {"is_active": False}, format="json"
    )
    assert response.status_code == 403


def test_members_cannot_be_deleted(admin, acme):
    operator = operator_in(acme)
    assert admin.client.delete(detail(operator)).status_code == 405
