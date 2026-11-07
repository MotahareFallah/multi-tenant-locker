import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from organizations.models import Membership, Organization, Role
from organizations.services import (
    LastAdminError,
    add_member,
    change_role,
    deactivate_member,
    reactivate_member,
)

pytestmark = pytest.mark.django_db


def make_user(number):
    return get_user_model().objects.create(phone_number=f"+98912000{number:04d}")


def make_org(slug):
    # Only the row: these tests are about membership rules, not about schemas.
    organization = Organization(name=slug, slug=slug, schema_name=f"org_{slug}")
    organization.auto_create_schema = False
    organization.save()
    return organization


def join(organization, number, role):
    return add_member(organization=organization, user=make_user(number), role=role)


def fresh(membership):
    return Membership.objects.get(pk=membership.pk)


def test_a_role_can_be_changed():
    org = make_org("acme")
    join(org, 1, Role.ADMIN)
    operator = join(org, 2, Role.OPERATOR)
    change_role(operator, Role.ADMIN)
    assert fresh(operator).role == Role.ADMIN


def test_the_only_admin_cannot_be_demoted():
    admin = join(make_org("acme"), 1, Role.ADMIN)
    with pytest.raises(LastAdminError):
        change_role(admin, Role.OPERATOR)
    assert fresh(admin).role == Role.ADMIN


def test_an_admin_can_be_demoted_when_another_admin_remains():
    org = make_org("acme")
    first = join(org, 1, Role.ADMIN)
    join(org, 2, Role.ADMIN)
    change_role(first, Role.OPERATOR)
    assert fresh(first).role == Role.OPERATOR


def test_the_only_admin_cannot_be_deactivated():
    admin = join(make_org("acme"), 1, Role.ADMIN)
    with pytest.raises(LastAdminError):
        deactivate_member(admin)
    assert fresh(admin).is_active


def test_an_admin_can_be_deactivated_when_another_admin_remains():
    org = make_org("acme")
    first = join(org, 1, Role.ADMIN)
    join(org, 2, Role.ADMIN)
    deactivate_member(first)
    assert not fresh(first).is_active


def test_an_inactive_admin_does_not_count_as_the_other_admin():
    org = make_org("acme")
    first = join(org, 1, Role.ADMIN)
    second = join(org, 2, Role.ADMIN)
    Membership.objects.filter(pk=second.pk).update(is_active=False)
    with pytest.raises(LastAdminError):
        change_role(first, Role.OPERATOR)
    with pytest.raises(LastAdminError):
        deactivate_member(first)


def test_admins_of_other_organizations_do_not_count():
    org = make_org("acme")
    admin = join(org, 1, Role.ADMIN)
    join(make_org("globex"), 2, Role.ADMIN)
    with pytest.raises(LastAdminError):
        deactivate_member(admin)


def test_an_operator_can_always_be_deactivated():
    org = make_org("acme")
    join(org, 1, Role.ADMIN)
    operator = join(org, 2, Role.OPERATOR)
    deactivate_member(operator)
    assert not fresh(operator).is_active


def test_a_member_can_be_reactivated():
    org = make_org("acme")
    join(org, 1, Role.ADMIN)
    operator = join(org, 2, Role.OPERATOR)
    deactivate_member(operator)
    reactivate_member(operator)
    assert fresh(operator).is_active


def test_an_unknown_role_is_rejected_and_nothing_changes():
    org = make_org("acme")
    join(org, 1, Role.ADMIN)
    operator = join(org, 2, Role.OPERATOR)
    with pytest.raises(ValidationError):
        change_role(operator, "owner")
    assert fresh(operator).role == Role.OPERATOR
