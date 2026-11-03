import re

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from organizations.models import Organization
from organizations.services import create_organization

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def make_org():
    created = []

    def make(**kwargs):
        organization = create_organization(**kwargs)
        created.append(organization)
        return organization

    yield make
    for organization in created:
        organization.delete(force_drop=True)


def schema_names():
    with connection.cursor() as cursor:
        cursor.execute("SELECT schema_name FROM information_schema.schemata")
        return {row[0] for row in cursor.fetchall()}


def schemas_with_table(table):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_schema FROM information_schema.tables WHERE table_name = %s",
            [table],
        )
        return {row[0] for row in cursor.fetchall()}


def test_creating_an_organization_creates_its_schema(make_org):
    organization = make_org(name="Acme", slug="acme")
    assert organization.schema_name in schema_names()
    assert str(organization) == "Acme"


def test_schema_names_never_come_from_input(make_org):
    first = make_org(name="public", slug="public-org")
    second = make_org(name='x"; DROP SCHEMA public; --', slug="evil-org")
    for organization in (first, second):
        assert re.fullmatch(r"org_[0-9a-f]{12}", organization.schema_name)
    assert first.schema_name != second.schema_name
    assert "public" in schema_names()


def test_a_duplicate_slug_is_rejected_without_creating_a_schema(make_org):
    make_org(name="Acme", slug="acme")
    before = schema_names()
    with pytest.raises(ValidationError):
        make_org(name="Other", slug="acme")
    assert schema_names() == before
    assert Organization.objects.count() == 1


@pytest.mark.parametrize(
    "slug", ["Bad Slug!", "Upper", "-lead", "trail-", "", "a" * 64]
)
def test_an_invalid_slug_is_rejected_without_creating_anything(make_org, slug):
    before = schema_names()
    with pytest.raises(ValidationError):
        make_org(name="Acme", slug=slug)
    assert schema_names() == before
    assert Organization.objects.count() == 0


def test_users_stay_in_public_while_tenant_apps_get_their_own_tables(make_org):
    organization = make_org(name="Acme", slug="acme")
    assert schemas_with_table("accounts_user") == {"public"}
    assert {"public", organization.schema_name} <= schemas_with_table(
        "django_content_type"
    )
