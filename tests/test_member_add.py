import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from organizations.models import Membership, Organization, Role
from organizations.services import add_member_by_phone, deactivate_member

pytestmark = pytest.mark.django_db

User = get_user_model()
PHONE = "09123456789"
E164 = "+989123456789"


@pytest.fixture
def org():
    # Only the row: these tests are about membership, not about schemas.
    organization = Organization(name="acme", slug="acme", schema_name="org_acme")
    organization.auto_create_schema = False
    organization.save()
    return organization


def test_an_existing_user_is_added_by_phone(org):
    user = User.objects.create_user(PHONE)
    membership = add_member_by_phone(organization=org, phone_number=PHONE, role=Role.OPERATOR)
    assert membership.user == user
    assert membership.role == Role.OPERATOR


def test_every_spelling_of_a_number_is_the_same_person(org):
    User.objects.create_user(E164)
    add_member_by_phone(organization=org, phone_number="0912 345 6789", role=Role.OPERATOR)
    assert User.objects.count() == 1


def test_an_unknown_number_gets_an_account_and_a_membership(org):
    membership = add_member_by_phone(organization=org, phone_number=PHONE, role=Role.OPERATOR)
    assert User.objects.get().phone_number == E164
    assert membership.user.is_active
    assert not membership.user.has_usable_password()


def test_an_invalid_number_creates_nothing(org):
    with pytest.raises(ValidationError):
        add_member_by_phone(organization=org, phone_number="12345", role=Role.OPERATOR)
    assert User.objects.count() == 0
    assert Membership.objects.count() == 0


def test_an_unknown_role_creates_nothing(org):
    with pytest.raises(ValidationError):
        add_member_by_phone(organization=org, phone_number=PHONE, role="owner")
    assert User.objects.count() == 0


def test_an_active_member_cannot_be_added_twice(org):
    add_member_by_phone(organization=org, phone_number=PHONE, role=Role.ADMIN)
    with pytest.raises(ValidationError):
        add_member_by_phone(organization=org, phone_number=E164, role=Role.OPERATOR)
    assert Membership.objects.count() == 1


def test_a_former_member_is_reactivated_with_the_new_role(org):
    add_member_by_phone(organization=org, phone_number="09121234567", role=Role.ADMIN)
    former = add_member_by_phone(organization=org, phone_number=PHONE, role=Role.ADMIN)
    deactivate_member(former)
    again = add_member_by_phone(organization=org, phone_number=PHONE, role=Role.OPERATOR)
    assert again.pk == former.pk
    assert again.is_active
    assert again.role == Role.OPERATOR
    assert Membership.objects.count() == 2
