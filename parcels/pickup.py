"""Pickup: check the code, open the door, record the result (ADR-0003).

Three steps, so that no database lock is held while talking to hardware:

1. A short transaction locks the parcel, checks the code and moves the parcel to
   PICKUP_IN_PROGRESS.
2. The device is asked to open the door, outside any transaction.
3. A second transaction records DELIVERED or PICKUP_FAILED.

A crash between steps 1 and 3 leaves the parcel in PICKUP_IN_PROGRESS; a recovery
task (a later step) moves such parcels to PICKUP_FAILED.
"""

from dataclasses import dataclass

from django.db import connection, transaction

from devices.base import DeviceError, DeviceTimeout
from parcels.models import Parcel, ParcelStatus
from parcels.pickup_code import pickup_code_matches
from parcels.state_machine import InvalidTransition, transition

MAX_WRONG_CODE_ATTEMPTS = 3


class WrongPickupCode(Exception):
    def __init__(self, attempts_left):
        super().__init__(f"Wrong pickup code; {attempts_left} attempts left.")
        self.attempts_left = attempts_left


class PickupBlocked(Exception):
    """Too many wrong codes. Even the right code is refused now."""


@dataclass(frozen=True)
class PickupOutcome:
    parcel: Parcel
    device_error: DeviceError | None = None

    @property
    def delivered(self):
        return self.device_error is None


@dataclass(frozen=True)
class _DoorCommand:
    locker_code: str
    compartment_number: int
    command_id: str


def _begin_pickup(parcel_id, code, actor):
    attempts_left = None
    with transaction.atomic():
        parcel = Parcel.objects.select_for_update().get(pk=parcel_id)
        if parcel.status != ParcelStatus.READY_FOR_PICKUP:
            raise InvalidTransition(f"{parcel.status} parcels cannot be picked up")
        if parcel.wrong_code_attempts >= MAX_WRONG_CODE_ATTEMPTS:
            raise PickupBlocked("Too many wrong pickup codes.")
        if pickup_code_matches(parcel, code):
            transition(
                parcel.pk,
                ParcelStatus.PICKUP_IN_PROGRESS,
                actor=actor,
                reason="pickup code accepted",
            )
            # The code is one-time: a retry needs a freshly issued one.
            Parcel.objects.filter(pk=parcel.pk).update(
                pickup_code_hash="", wrong_code_attempts=0
            )
            return _DoorCommand(
                locker_code=parcel.locker.code,
                compartment_number=parcel.compartment.number,
                command_id=f"{parcel.tracking_code}:{parcel.pickup_attempts + 1}",
            )
        parcel.wrong_code_attempts += 1
        parcel.save(update_fields=["wrong_code_attempts", "updated_at"])
        attempts_left = MAX_WRONG_CODE_ATTEMPTS - parcel.wrong_code_attempts
    # Raised after the transaction committed, so the counter is kept.
    raise WrongPickupCode(attempts_left)


def pickup_parcel(parcel_id, code, *, device, actor):
    """Run a pickup. Returns the outcome; raises if the request is refused."""
    if connection.in_atomic_block:
        raise RuntimeError("pickup_parcel must not run inside a transaction.")

    command = _begin_pickup(parcel_id, code, actor)
    try:
        device.open_door(
            locker_code=command.locker_code,
            compartment_number=command.compartment_number,
            command_id=command.command_id,
        )
    except DeviceError as error:
        if isinstance(error, DeviceTimeout):
            reason = "device timeout; door state unknown"
        else:
            reason = f"device fault: {error}"[:255]
        parcel = transition(
            parcel_id, ParcelStatus.PICKUP_FAILED, actor="device", reason=reason
        )
        return PickupOutcome(parcel, error)
    parcel = transition(
        parcel_id, ParcelStatus.DELIVERED, actor="device", reason="door opened"
    )
    return PickupOutcome(parcel)
