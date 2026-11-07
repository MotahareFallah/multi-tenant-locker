import pytest
from django.core.exceptions import ValidationError

from organizations.models import Membership, Organization, Role
from organizations.services import add_member_by_phone

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.concurrency]


def test_simultaneous_adds_of_the_same_number_create_one_membership(run_concurrently):
    org = Organization(name="acme", slug="acme", schema_name="org_acme")
    org.auto_create_schema = False
    org.save()
    results = run_concurrently(
        lambda: add_member_by_phone(
            organization=org, phone_number="09123456789", role=Role.OPERATOR
        ),
        6,
    )
    errors = [error for _, error in results if error is not None]
    assert len(errors) == 5
    assert all(isinstance(error, ValidationError) for error in errors)
    assert Membership.objects.count() == 1
