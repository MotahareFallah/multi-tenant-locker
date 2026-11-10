import itertools

import pytest
from django_tenants.utils import tenant_context

from lockers.models import Compartment, CompartmentSize, Locker
from parcels.models import Parcel, ParcelEvent, ParcelStatus
from parcels.state_machine import InvalidTransition, transition

pytestmark = pytest.mark.django_db(transaction=True)

S = ParcelStatus


@pytest.fixture
def ready_parcel(make_org):
    organization = make_org("acme")
    with tenant_context(organization):
        locker = Locker.objects.create(code="one", name="One")
        compartment = Compartment.objects.create(
            locker=locker, number=1, size=CompartmentSize.SMALL
        )
        parcel = Parcel.objects.create(
            locker=locker,
            compartment=compartment,
            recipient_phone="+989120000001",
            size=CompartmentSize.SMALL,
            status=S.READY_FOR_PICKUP,
        )
    return organization, parcel


def test_concurrent_pickups_of_one_parcel_have_exactly_one_winner(
    ready_parcel, run_concurrently
):
    organization, parcel = ready_parcel

    def pick_up():
        with tenant_context(organization):
            return transition(parcel.pk, S.PICKUP_IN_PROGRESS, actor="test").status

    outcomes = run_concurrently(pick_up, 8)
    winners = [result for result, error in outcomes if error is None]
    losers = [error for result, error in outcomes if error is not None]
    assert len(winners) == 1
    assert len(losers) == 7
    assert all(isinstance(error, InvalidTransition) for error in losers)
    with tenant_context(organization):
        assert ParcelEvent.objects.count() == 1


def test_pickup_racing_with_expiry_has_exactly_one_outcome(
    ready_parcel, run_concurrently
):
    organization, parcel = ready_parcel
    targets = [S.PICKUP_IN_PROGRESS, S.EXPIRED]
    counter = itertools.count()

    def attempt():
        target = targets[next(counter) % 2]
        with tenant_context(organization):
            return transition(parcel.pk, target, actor="test").status

    outcomes = run_concurrently(attempt, 2)
    winners = [result for result, error in outcomes if error is None]
    errors = [error for result, error in outcomes if error is not None]
    assert len(winners) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], InvalidTransition)
    with tenant_context(organization):
        parcel.refresh_from_db()
        assert parcel.status == winners[0]
        assert ParcelEvent.objects.get().to_status == winners[0]
