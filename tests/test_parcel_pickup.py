import threading

import pytest
from django.db import DatabaseError, connections, transaction
from django_tenants.utils import tenant_context

from devices.base import DeviceFault, DeviceTimeout
from devices.simulator import Fault, SimulatedDevice
from lockers.models import Compartment, CompartmentSize, Locker
from parcels.models import Parcel, ParcelEvent, ParcelStatus
from parcels.pickup import (
    MAX_WRONG_CODE_ATTEMPTS,
    PickupBlocked,
    WrongPickupCode,
    pickup_parcel,
)
from parcels.services import create_parcel, deposit_parcel, issue_pickup_code
from parcels.state_machine import InvalidTransition

pytestmark = pytest.mark.django_db(transaction=True)

S = ParcelStatus


@pytest.fixture
def tenant(make_org):
    organization = make_org("acme")
    with tenant_context(organization):
        yield organization


@pytest.fixture
def locker(tenant):
    return Locker.objects.create(code="one", name="One")


def ready_parcel(locker, number=1):
    Compartment.objects.create(locker=locker, number=number, size=CompartmentSize.SMALL)
    parcel = create_parcel(
        locker=locker,
        recipient_phone="09123456789",
        size=CompartmentSize.SMALL,
        actor="test",
    )
    parcel = deposit_parcel(parcel.pk, actor="courier")
    code = issue_pickup_code(parcel.pk, actor="system")
    return parcel, code


def wrong(code):
    return "000000" if code != "000000" else "000001"


def pick_up(parcel, code, device):
    return pickup_parcel(parcel.pk, code, device=device, actor="user")


def history(parcel):
    events = ParcelEvent.objects.filter(parcel=parcel).order_by("id")
    return [(event.from_status, event.to_status) for event in events]


def test_a_correct_code_delivers_the_parcel(locker):
    parcel, code = ready_parcel(locker)
    device = SimulatedDevice()
    outcome = pick_up(parcel, code, device)
    assert outcome.delivered
    assert outcome.parcel.status == S.DELIVERED
    assert device.opened == [("one", 1, f"{parcel.tracking_code}:1")]
    parcel.refresh_from_db()
    assert (parcel.pickup_code_hash, parcel.wrong_code_attempts) == ("", 0)
    assert history(parcel) == [
        ("", "CREATED"),
        ("CREATED", "STORED"),
        ("STORED", "READY_FOR_PICKUP"),
        ("READY_FOR_PICKUP", "PICKUP_IN_PROGRESS"),
        ("PICKUP_IN_PROGRESS", "DELIVERED"),
    ]


def test_a_code_works_only_once(locker):
    parcel, code = ready_parcel(locker)
    device = SimulatedDevice()
    pick_up(parcel, code, device)
    with pytest.raises(InvalidTransition):
        pick_up(parcel, code, device)
    assert len(device.opened) == 1


def test_a_wrong_code_is_refused_and_counted(locker):
    parcel, code = ready_parcel(locker)
    device = SimulatedDevice()
    with pytest.raises(WrongPickupCode) as caught:
        pick_up(parcel, wrong(code), device)
    assert caught.value.attempts_left == MAX_WRONG_CODE_ATTEMPTS - 1
    parcel.refresh_from_db()
    assert parcel.status == S.READY_FOR_PICKUP
    assert parcel.wrong_code_attempts == 1
    assert device.calls == 0


def test_a_missing_code_counts_as_wrong(locker):
    parcel, _ = ready_parcel(locker)
    with pytest.raises(WrongPickupCode):
        pick_up(parcel, None, SimulatedDevice())


def test_too_many_wrong_codes_block_the_parcel(locker):
    parcel, code = ready_parcel(locker)
    device = SimulatedDevice()
    for _ in range(MAX_WRONG_CODE_ATTEMPTS):
        with pytest.raises(WrongPickupCode):
            pick_up(parcel, wrong(code), device)
    with pytest.raises(PickupBlocked):
        pick_up(parcel, code, device)  # even the right code is refused now
    parcel.refresh_from_db()
    assert parcel.status == S.READY_FOR_PICKUP
    assert device.calls == 0


def test_a_correct_code_resets_the_wrong_code_counter(locker):
    parcel, code = ready_parcel(locker)
    device = SimulatedDevice()
    for _ in range(MAX_WRONG_CODE_ATTEMPTS - 1):
        with pytest.raises(WrongPickupCode):
            pick_up(parcel, wrong(code), device)
    assert pick_up(parcel, code, device).delivered
    parcel.refresh_from_db()
    assert parcel.wrong_code_attempts == 0


def test_a_device_error_fails_the_pickup_and_a_retry_uses_a_new_command(locker):
    parcel, code = ready_parcel(locker)
    device = SimulatedDevice()
    device.inject(Fault.ERROR)
    outcome = pick_up(parcel, code, device)
    assert not outcome.delivered
    assert isinstance(outcome.device_error, DeviceFault)
    parcel.refresh_from_db()
    assert parcel.status == S.PICKUP_FAILED
    assert parcel.pickup_attempts == 1
    assert parcel.pickup_code_hash == ""
    assert "device fault" in ParcelEvent.objects.filter(parcel=parcel).last().reason
    assert device.opened == []

    new_code = issue_pickup_code(parcel.pk, actor="system")
    assert pick_up(parcel, new_code, device).delivered
    assert device.opened == [("one", 1, f"{parcel.tracking_code}:2")]


def test_a_timeout_fails_the_pickup_even_if_the_door_opened(locker):
    parcel, code = ready_parcel(locker)
    device = SimulatedDevice()
    device.inject(Fault.TIMEOUT, opened=True)
    outcome = pick_up(parcel, code, device)
    assert isinstance(outcome.device_error, DeviceTimeout)
    parcel.refresh_from_db()
    assert parcel.status == S.PICKUP_FAILED
    assert "door state unknown" in ParcelEvent.objects.filter(parcel=parcel).last().reason
    # The door really did open. An operator has to reconcile this by hand.
    assert len(device.opened) == 1


def test_a_slow_device_still_delivers(locker):
    parcel, code = ready_parcel(locker)
    device = SimulatedDevice(sleep=lambda seconds: None)
    device.inject(Fault.SLOW, delay=5)
    assert pick_up(parcel, code, device).delivered


def test_a_parcel_that_is_not_ready_cannot_be_picked_up(locker):
    parcel, code = ready_parcel(locker)
    Parcel.objects.filter(pk=parcel.pk).update(status=S.STORED)
    device = SimulatedDevice()
    with pytest.raises(InvalidTransition):
        pick_up(parcel, code, device)
    assert device.calls == 0


class LockProbeDevice(SimulatedDevice):
    """Records whether the parcel row was locked while the door command ran."""

    def __init__(self, organization, parcel_pk):
        super().__init__()
        self.organization = organization
        self.parcel_pk = parcel_pk
        self.row_was_locked = None

    def open_door(self, **kwargs):
        def probe():
            try:
                with tenant_context(self.organization), transaction.atomic():
                    Parcel.objects.select_for_update(nowait=True).get(pk=self.parcel_pk)
                self.row_was_locked = False
            except DatabaseError:
                self.row_was_locked = True
            finally:
                connections.close_all()

        thread = threading.Thread(target=probe)
        thread.start()
        thread.join()
        return super().open_door(**kwargs)


def test_no_database_lock_is_held_while_the_device_works(tenant, locker):
    parcel, code = ready_parcel(locker)
    device = LockProbeDevice(tenant, parcel.pk)
    assert pick_up(parcel, code, device).delivered
    assert device.row_was_locked is False


def test_pickup_refuses_to_run_inside_a_transaction(locker):
    parcel, code = ready_parcel(locker)
    device = SimulatedDevice()
    with transaction.atomic(), pytest.raises(RuntimeError):
        pick_up(parcel, code, device)
    assert device.calls == 0
