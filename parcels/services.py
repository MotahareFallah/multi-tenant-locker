"""Operations on parcels. Each one is a single transaction."""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from accounts.phone import normalize_phone_number
from lockers.models import Compartment
from parcels.models import OCCUPYING_STATUSES, Parcel, ParcelEvent, ParcelStatus
from parcels.pickup_code import generate_pickup_code, hash_pickup_code
from parcels.state_machine import InvalidTransition, transition


class LockerUnavailable(Exception):
    """The locker is switched off."""


class NoFreeCompartment(Exception):
    """No free, active compartment of the parcel's size in the locker."""


@transaction.atomic
def create_parcel(*, locker, recipient_phone, size, actor):
    if not locker.is_active:
        raise LockerUnavailable(f"Locker {locker.code} is not active.")
    parcel = Parcel(
        locker=locker,
        recipient_phone=normalize_phone_number(recipient_phone),
        size=size,
        expires_at=timezone.now() + timedelta(days=settings.PARCEL_STORAGE_DAYS),
    )
    parcel.full_clean()
    parcel.save()
    ParcelEvent.objects.create(
        parcel=parcel,
        from_status="",
        to_status=ParcelStatus.CREATED,
        actor=actor,
        reason="created",
    )
    return parcel


@transaction.atomic
def deposit_parcel(parcel_id, *, actor):
    """Put a created parcel into the lowest-numbered free compartment of its size."""
    parcel = Parcel.objects.select_for_update().get(pk=parcel_id)
    if parcel.status != ParcelStatus.CREATED:
        raise InvalidTransition(f"{parcel.status} parcels cannot be deposited")
    if not parcel.locker.is_active:
        raise LockerUnavailable(f"Locker {parcel.locker.code} is not active.")

    occupied = Parcel.objects.filter(
        compartment=OuterRef("pk"), status__in=OCCUPYING_STATUSES
    )
    candidate_ids = list(
        Compartment.objects.filter(
            locker=parcel.locker, is_active=True, size=parcel.size
        )
        .filter(~Exists(occupied))
        .order_by("number")
        .values_list("pk", flat=True)
    )
    for compartment_id in candidate_ids:
        # Lock one compartment at a time. Locking all candidates would make a
        # concurrent deposit see every free compartment as taken.
        compartment = (
            Compartment.objects.select_for_update(skip_locked=True)
            .filter(pk=compartment_id, is_active=True)
            .first()
        )
        if compartment is None:
            continue  # another deposit holds it right now
        # Checked again under the lock: a deposit that committed after our first
        # query is visible to this fresh one.
        if Parcel.objects.filter(
            compartment=compartment, status__in=OCCUPYING_STATUSES
        ).exists():
            continue
        return transition(
            parcel.pk,
            ParcelStatus.STORED,
            actor=actor,
            reason="deposited",
            compartment=compartment,
        )
    raise NoFreeCompartment(f"No free {parcel.size} compartment in {parcel.locker.code}.")


@transaction.atomic
def issue_pickup_code(parcel_id, *, actor):
    """Make the parcel ready for pickup and return the code. Shown only once."""
    parcel = Parcel.objects.select_for_update().get(pk=parcel_id)
    code = generate_pickup_code()
    parcel.pickup_code_hash = hash_pickup_code(parcel.tracking_code, code)
    parcel.save(update_fields=["pickup_code_hash", "updated_at"])
    # If the state does not allow this, the whole transaction rolls back and the
    # new hash is not kept.
    transition(
        parcel.pk,
        ParcelStatus.READY_FOR_PICKUP,
        actor=actor,
        reason="pickup code issued",
    )
    return code
