import itertools

import pytest
from django_tenants.utils import tenant_context

from lockers.models import Compartment, CompartmentSize, Locker
from parcels.models import Parcel, ParcelStatus
from parcels.services import NoFreeCompartment, create_parcel, deposit_parcel
from parcels.state_machine import InvalidTransition

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def stocked(make_org):
    """A locker with three small compartments and five created parcels."""
    organization = make_org("acme")
    with tenant_context(organization):
        locker = Locker.objects.create(code="one", name="One")
        for number in (1, 2, 3):
            Compartment.objects.create(
                locker=locker, number=number, size=CompartmentSize.SMALL
            )
        parcels = [
            create_parcel(
                locker=locker,
                recipient_phone="09123456789",
                size=CompartmentSize.SMALL,
                actor="test",
            )
            for _ in range(5)
        ]
    return organization, parcels


def test_concurrent_deposits_never_share_a_compartment(stocked, run_concurrently):
    organization, parcels = stocked
    counter = itertools.count()

    def deposit():
        parcel = parcels[next(counter)]
        with tenant_context(organization):
            return deposit_parcel(parcel.pk, actor="courier").compartment_id

    outcomes = run_concurrently(deposit, 5)
    stored = [result for result, error in outcomes if error is None]
    errors = [error for result, error in outcomes if error is not None]
    assert len(stored) == 3
    assert len(set(stored)) == 3
    assert len(errors) == 2
    assert all(isinstance(error, NoFreeCompartment) for error in errors)
    with tenant_context(organization):
        assert Parcel.objects.filter(status=ParcelStatus.STORED).count() == 3


def test_depositing_one_parcel_many_times_stores_it_once(stocked, run_concurrently):
    organization, parcels = stocked
    parcel = parcels[0]

    def deposit():
        with tenant_context(organization):
            return deposit_parcel(parcel.pk, actor="courier").compartment_id

    outcomes = run_concurrently(deposit, 6)
    stored = [result for result, error in outcomes if error is None]
    errors = [error for result, error in outcomes if error is not None]
    assert len(stored) == 1
    assert len(errors) == 5
    assert all(isinstance(error, InvalidTransition) for error in errors)
