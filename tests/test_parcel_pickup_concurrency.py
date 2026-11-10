import pytest
from django_tenants.utils import tenant_context

from devices.simulator import SimulatedDevice
from lockers.models import Compartment, CompartmentSize, Locker
from parcels.models import Parcel
from parcels.pickup import (
    MAX_WRONG_CODE_ATTEMPTS,
    PickupBlocked,
    WrongPickupCode,
    pickup_parcel,
)
from parcels.services import create_parcel, deposit_parcel, issue_pickup_code
from parcels.state_machine import InvalidTransition

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def ready(make_org):
    organization = make_org("acme")
    with tenant_context(organization):
        locker = Locker.objects.create(code="one", name="One")
        Compartment.objects.create(
            locker=locker, number=1, size=CompartmentSize.SMALL
        )
        parcel = create_parcel(
            locker=locker,
            recipient_phone="09123456789",
            size=CompartmentSize.SMALL,
            actor="test",
        )
        deposit_parcel(parcel.pk, actor="courier")
        code = issue_pickup_code(parcel.pk, actor="system")
    return organization, parcel.pk, code


def test_concurrent_pickups_with_the_right_code_open_the_door_once(
    ready, run_concurrently
):
    organization, parcel_pk, code = ready
    device = SimulatedDevice()

    def pick_up():
        with tenant_context(organization):
            return pickup_parcel(parcel_pk, code, device=device, actor="user")

    outcomes = run_concurrently(pick_up, 6)
    delivered = [result for result, error in outcomes if error is None]
    errors = [error for result, error in outcomes if error is not None]
    assert len(delivered) == 1
    assert delivered[0].delivered
    assert len(errors) == 5
    assert all(isinstance(error, InvalidTransition) for error in errors)
    assert len(device.opened) == 1


def test_concurrent_wrong_codes_are_counted_exactly(ready, run_concurrently):
    organization, parcel_pk, code = ready
    device = SimulatedDevice()
    wrong_code = "000000" if code != "000000" else "000001"

    def guess():
        with tenant_context(organization):
            return pickup_parcel(parcel_pk, wrong_code, device=device, actor="user")

    outcomes = run_concurrently(guess, 8)
    errors = [error for result, error in outcomes]
    wrong_codes = [e for e in errors if isinstance(e, WrongPickupCode)]
    blocked = [e for e in errors if isinstance(e, PickupBlocked)]
    assert len(wrong_codes) == MAX_WRONG_CODE_ATTEMPTS
    assert len(blocked) == 8 - MAX_WRONG_CODE_ATTEMPTS
    assert sorted(e.attempts_left for e in wrong_codes) == [0, 1, 2]
    with tenant_context(organization):
        assert Parcel.objects.get(pk=parcel_pk).wrong_code_attempts == 3
    assert device.calls == 0
