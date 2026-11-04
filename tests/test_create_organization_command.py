import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from organizations.models import Membership, Organization, Role

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def drop_created_schemas():
    yield
    for organization in Organization.objects.all():
        organization.delete(force_drop=True)


def schema_names():
    with connection.cursor() as cursor:
        cursor.execute("SELECT schema_name FROM information_schema.schemata")
        return {row[0] for row in cursor.fetchall()}


def run(**options):
    call_command("create_organization", **options)


def test_it_creates_the_organization_its_schema_and_its_first_admin():
    run(name="Acme", slug="acme", admin_phone="09123456789")
    organization = Organization.objects.get(slug="acme")
    assert organization.schema_name in schema_names()
    membership = Membership.objects.get()
    assert membership.organization == organization
    assert membership.role == Role.ADMIN
    assert membership.user.phone_number == "+989123456789"


def test_an_invalid_phone_number_creates_nothing():
    before = schema_names()
    with pytest.raises(CommandError):
        run(name="Acme", slug="acme", admin_phone="12345")
    assert Organization.objects.count() == 0
    assert get_user_model().objects.count() == 0
    assert schema_names() == before


def test_a_duplicate_slug_creates_nothing_more():
    run(name="Acme", slug="acme", admin_phone="09123456789")
    before = schema_names()
    with pytest.raises(CommandError):
        run(name="Other", slug="acme", admin_phone="09121234567")
    assert Organization.objects.count() == 1
    assert schema_names() == before
