import pytest
from django.db import connection
from django_tenants.utils import schema_context, tenant_context

from accounts.checks import database_is_postgresql
from organizations.models import Organization
from tenantdemo.models import Item

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def make_org():
    created = []

    def make(schema_name, name):
        org = Organization(schema_name=schema_name, name=name)
        org.save()
        created.append(org)
        return org

    yield make
    for org in created:
        org.delete(force_drop=True)


def schemas_with_table(table):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_schema FROM information_schema.tables WHERE table_name = %s",
            [table],
        )
        return sorted(row[0] for row in cursor.fetchall())


def test_tenant_tables_live_only_in_the_tenant_schema(make_org):
    make_org("org_a", "A")
    with schema_context("public"):
        assert schemas_with_table("tenantdemo_item") == ["org_a"]
        assert schemas_with_table("accounts_user") == ["public"]


def test_data_is_isolated_between_organizations(make_org):
    org_a = make_org("org_a", "A")
    org_b = make_org("org_b", "B")
    with tenant_context(org_a):
        Item.objects.create(name="only in a")
        assert Item.objects.count() == 1
    with tenant_context(org_b):
        assert Item.objects.count() == 0


def test_the_schema_is_public_again_after_leaving_a_tenant(make_org):
    org = make_org("org_a", "A")
    assert connection.schema_name == "public"
    with tenant_context(org):
        assert connection.schema_name == "org_a"
    assert connection.schema_name == "public"
    with pytest.raises(RuntimeError):
        with tenant_context(org):
            raise RuntimeError("boom")
    assert connection.schema_name == "public"


def test_the_postgresql_system_check_still_passes_on_the_tenant_backend():
    assert connection.vendor == "postgresql"
    assert database_is_postgresql(None) == []
