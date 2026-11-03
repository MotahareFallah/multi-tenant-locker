import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from organizations.models import Membership, Organization, Role
from organizations.services import add_member, get_active_membership

pytestmark = pytest.mark.django_db


def make_user(number):
    return get_user_model().objects.create(phone_number=f"+98912000{number:04d}")


def make_org(slug):
    # Only the row: these tests are about memberships, not about schemas.
    organization = Organization(
        name=slug, slug=slug, schema_name=f"org_{slug.replace('-', '')}"
    )
    organization.auto_create_schema = False
    organization.save()
    return organization


def test_add_member_creates_an_active_membership():
    user, org = make_user(1), make_org("acme")
    membership = add_member(organization=org, user=user, role=Role.OPERATOR)
    assert membership.is_active
    assert membership.role == "operator"


def test_a_user_has_at_most_one_membership_per_organization():
    user, org = make_user(1), make_org("acme")
    add_member(organization=org, user=user, role=Role.ADMIN)
    with pytest.raises(ValidationError):
        add_member(organization=org, user=user, role=Role.OPERATOR)


def test_the_database_also_rejects_a_duplicate_membership():
    user, org = make_user(1), make_org("acme")
    Membership.objects.create(user=user, organization=org, role=Role.ADMIN)
    with pytest.raises(IntegrityError), transaction.atomic():
        Membership.objects.create(user=user, organization=org, role=Role.OPERATOR)


def test_a_user_can_belong_to_several_organizations_with_different_roles():
    user = make_user(1)
    add_member(organization=make_org("acme"), user=user, role=Role.ADMIN)
    add_member(organization=make_org("globex"), user=user, role=Role.OPERATOR)
    roles = set(user.memberships.values_list("role", flat=True))
    assert roles == {"admin", "operator"}


def test_an_unknown_role_is_rejected():
    with pytest.raises(ValidationError):
        add_member(organization=make_org("acme"), user=make_user(1), role="owner")


def test_the_database_rejects_an_unknown_role():
    user, org = make_user(1), make_org("acme")
    with pytest.raises(IntegrityError), transaction.atomic():
        Membership.objects.create(user=user, organization=org, role="owner")


def test_an_active_membership_is_found_by_slug():
    user, org = make_user(1), make_org("acme")
    membership = add_member(organization=org, user=user, role=Role.ADMIN)
    assert get_active_membership(user, "acme") == membership


def test_another_organizations_slug_gives_none():
    user = make_user(1)
    add_member(organization=make_org("acme"), user=user, role=Role.ADMIN)
    make_org("globex")
    assert get_active_membership(user, "globex") is None


def test_an_inactive_membership_gives_none():
    user, org = make_user(1), make_org("acme")
    membership = add_member(organization=org, user=user, role=Role.ADMIN)
    Membership.objects.filter(pk=membership.pk).update(is_active=False)
    assert get_active_membership(user, "acme") is None


def test_somebody_elses_membership_gives_none():
    owner, outsider = make_user(1), make_user(2)
    add_member(organization=make_org("acme"), user=owner, role=Role.ADMIN)
    assert get_active_membership(outsider, "acme") is None


def test_an_unknown_slug_and_an_anonymous_user_give_none():
    user = make_user(1)
    add_member(organization=make_org("acme"), user=user, role=Role.ADMIN)
    assert get_active_membership(user, "missing") is None
    assert get_active_membership(AnonymousUser(), "acme") is None


def test_a_user_with_memberships_cannot_be_deleted():
    user = make_user(1)
    add_member(organization=make_org("acme"), user=user, role=Role.ADMIN)
    with pytest.raises(ProtectedError):
        user.delete()


def test_deleting_an_organization_removes_its_memberships():
    user, org = make_user(1), make_org("acme")
    add_member(organization=org, user=user, role=Role.ADMIN)
    org.delete()
    assert Membership.objects.count() == 0
