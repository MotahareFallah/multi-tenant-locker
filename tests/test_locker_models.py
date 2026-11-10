import pytest
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django_tenants.utils import tenant_context

from lockers.models import Compartment, CompartmentSize, Locker
from organizations.services import create_organization

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def make_org():
    created = []

    def make(slug):
        organization = create_organization(name=slug, slug=slug)
        created.append(organization)
        return organization

    yield make
    for organization in created:
        organization.delete(force_drop=True)


def schemas_with_table(table):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_schema FROM information_schema.tables WHERE table_name = %s",
            [table],
        )
        return {row[0] for row in cursor.fetchall()}


def test_locker_tables_exist_only_in_the_tenant_schema(make_org):
    org = make_org("acme")
    assert schemas_with_table("lockers_locker") == {org.schema_name}
    assert schemas_with_table("lockers_compartment") == {org.schema_name}


def test_lockers_are_isolated_between_organizations(make_org):
    org_a, org_b = make_org("acme"), make_org("globex")
    with tenant_context(org_a):
        Locker.objects.create(code="main-hall", name="Main hall")
    with tenant_context(org_b):
        assert Locker.objects.count() == 0
        # The same code is free to use in another organization.
        Locker.objects.create(code="main-hall", name="Main hall")
    with tenant_context(org_a):
        assert Locker.objects.count() == 1


def test_compartment_number_is_unique_per_locker(make_org):
    org = make_org("acme")
    with tenant_context(org):
        one = Locker.objects.create(code="one", name="One")
        two = Locker.objects.create(code="two", name="Two")
        Compartment.objects.create(locker=one, number=1, size=CompartmentSize.SMALL)
        Compartment.objects.create(locker=two, number=1, size=CompartmentSize.SMALL)
        with pytest.raises(IntegrityError), transaction.atomic():
            Compartment.objects.create(
                locker=one, number=1, size=CompartmentSize.LARGE
            )


def test_compartment_number_must_be_positive(make_org):
    org = make_org("acme")
    with tenant_context(org):
        locker = Locker.objects.create(code="one", name="One")
        with pytest.raises(IntegrityError), transaction.atomic():
            Compartment.objects.create(
                locker=locker, number=0, size=CompartmentSize.SMALL
            )


def test_compartment_size_must_be_known(make_org):
    org = make_org("acme")
    with tenant_context(org):
        locker = Locker.objects.create(code="one", name="One")
        with pytest.raises(IntegrityError), transaction.atomic():
            Compartment.objects.create(locker=locker, number=1, size="HUGE")


def test_a_locker_with_compartments_cannot_be_deleted(make_org):
    org = make_org("acme")
    with tenant_context(org):
        locker = Locker.objects.create(code="one", name="One")
        Compartment.objects.create(locker=locker, number=1, size=CompartmentSize.SMALL)
        with pytest.raises(ProtectedError):
            locker.delete()
