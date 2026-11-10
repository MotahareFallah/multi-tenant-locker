import pytest
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django_tenants.utils import tenant_context

from lockers.models import Compartment, CompartmentSize, Locker
from organizations.services import create_organization
from parcels.models import Parcel, ParcelEvent, ParcelStatus

pytestmark = pytest.mark.django_db(transaction=True)

PHONE = "+989120000001"


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


def make_locker(code="one"):
    return Locker.objects.create(code=code, name=code)


def make_compartment(locker, number=1):
    return Compartment.objects.create(
        locker=locker, number=number, size=CompartmentSize.SMALL
    )


def make_parcel(locker, compartment=None, status=ParcelStatus.CREATED):
    return Parcel.objects.create(
        locker=locker,
        compartment=compartment,
        recipient_phone=PHONE,
        size=CompartmentSize.SMALL,
        status=status,
    )


def test_parcel_tables_exist_only_in_the_tenant_schema(make_org):
    org = make_org("acme")
    assert schemas_with_table("parcels_parcel") == {org.schema_name}
    assert schemas_with_table("parcels_parcelevent") == {org.schema_name}


def test_a_new_parcel_starts_created_with_a_unique_tracking_code(make_org):
    with tenant_context(make_org("acme")):
        locker = make_locker()
        first, second = make_parcel(locker), make_parcel(locker)
        assert first.status == ParcelStatus.CREATED
        assert first.compartment is None
        assert first.tracking_code and first.tracking_code != second.tracking_code


@pytest.mark.parametrize(
    "first, second",
    [
        (ParcelStatus.STORED, ParcelStatus.STORED),
        (ParcelStatus.STORED, ParcelStatus.READY_FOR_PICKUP),
        (ParcelStatus.PICKUP_IN_PROGRESS, ParcelStatus.STORED),
        (ParcelStatus.PICKUP_FAILED, ParcelStatus.STORED),
    ],
)
def test_two_parcels_cannot_occupy_one_compartment(make_org, first, second):
    with tenant_context(make_org("acme")):
        locker = make_locker()
        compartment = make_compartment(locker)
        make_parcel(locker, compartment, first)
        with pytest.raises(IntegrityError), transaction.atomic():
            make_parcel(locker, compartment, second)


@pytest.mark.parametrize("finished", [ParcelStatus.DELIVERED, ParcelStatus.EXPIRED])
def test_a_finished_parcel_frees_the_compartment(make_org, finished):
    with tenant_context(make_org("acme")):
        locker = make_locker()
        compartment = make_compartment(locker)
        make_parcel(locker, compartment, finished)
        make_parcel(locker, compartment, ParcelStatus.STORED)
        assert Parcel.objects.filter(compartment=compartment).count() == 2


@pytest.mark.parametrize(
    "status",
    [
        ParcelStatus.STORED,
        ParcelStatus.READY_FOR_PICKUP,
        ParcelStatus.PICKUP_IN_PROGRESS,
        ParcelStatus.PICKUP_FAILED,
    ],
)
def test_a_parcel_in_an_occupying_state_needs_a_compartment(make_org, status):
    with tenant_context(make_org("acme")):
        locker = make_locker()
        with pytest.raises(IntegrityError), transaction.atomic():
            make_parcel(locker, None, status)


def test_an_unknown_status_is_rejected(make_org):
    with tenant_context(make_org("acme")):
        locker = make_locker()
        with pytest.raises(IntegrityError), transaction.atomic():
            make_parcel(locker, None, "LOST")


def test_parcels_are_isolated_between_organizations(make_org):
    org_a, org_b = make_org("acme"), make_org("globex")
    with tenant_context(org_a):
        make_parcel(make_locker())
    with tenant_context(org_b):
        assert Parcel.objects.count() == 0
    with tenant_context(org_a):
        assert Parcel.objects.count() == 1


def test_a_parcel_with_history_cannot_be_deleted(make_org):
    with tenant_context(make_org("acme")):
        parcel = make_parcel(make_locker())
        ParcelEvent.objects.create(
            parcel=parcel,
            from_status="",
            to_status=ParcelStatus.CREATED,
            actor="system",
        )
        with pytest.raises(ProtectedError):
            parcel.delete()
