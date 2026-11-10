"""The parcel lifecycle rules (ADR-0003).

`transition()` is the only place that changes `Parcel.status`. Views, tasks and
device callbacks call it; none of them assign the status directly.
"""

from django.db import transaction

from parcels.models import OCCUPYING_STATUSES, Parcel, ParcelEvent, ParcelStatus

MAX_PICKUP_ATTEMPTS = 3

_S = ParcelStatus

ALLOWED_TRANSITIONS = frozenset(
    (source.value, target.value)
    for source, target in [
        (_S.CREATED, _S.STORED),
        (_S.CREATED, _S.EXPIRED),
        (_S.STORED, _S.READY_FOR_PICKUP),
        (_S.STORED, _S.EXPIRED),
        (_S.READY_FOR_PICKUP, _S.PICKUP_IN_PROGRESS),
        (_S.READY_FOR_PICKUP, _S.EXPIRED),
        (_S.PICKUP_IN_PROGRESS, _S.DELIVERED),
        (_S.PICKUP_IN_PROGRESS, _S.PICKUP_FAILED),
        (_S.PICKUP_FAILED, _S.READY_FOR_PICKUP),
        (_S.PICKUP_FAILED, _S.EXPIRED),
    ]
)


class InvalidTransition(Exception):
    """The requested state change is not allowed (maps to HTTP 409)."""


class PickupAttemptsExhausted(InvalidTransition):
    """A failed pickup was retried too many times; an operator must step in."""


@transaction.atomic
def transition(
    parcel_id,
    to_status,
    *,
    actor,
    reason="",
    compartment=None,
    override_retry_limit=False,
):
    """Move a parcel to `to_status`, or raise `InvalidTransition`.

    The parcel row is locked, and the rules are checked against the state read
    under that lock, never against a copy the caller loaded earlier.
    """
    if not actor:
        raise ValueError("actor is required")
    to_status = str(to_status)

    parcel = Parcel.objects.select_for_update().get(pk=parcel_id)
    from_status = parcel.status

    if (from_status, to_status) not in ALLOWED_TRANSITIONS:
        raise InvalidTransition(f"{from_status} -> {to_status} is not allowed")

    if compartment is not None:
        if to_status != ParcelStatus.STORED:
            raise InvalidTransition("a compartment is assigned only when storing")
        parcel.compartment = compartment
    if to_status in OCCUPYING_STATUSES and parcel.compartment_id is None:
        raise InvalidTransition(f"{to_status} needs a compartment")

    if to_status == ParcelStatus.PICKUP_FAILED:
        parcel.pickup_attempts += 1
    elif (
        from_status == ParcelStatus.PICKUP_FAILED
        and to_status == ParcelStatus.READY_FOR_PICKUP
        and parcel.pickup_attempts >= MAX_PICKUP_ATTEMPTS
    ):
        if not override_retry_limit:
            raise PickupAttemptsExhausted(
                f"{parcel.pickup_attempts} failed attempts; operator action needed"
            )
        parcel.pickup_attempts = 0

    parcel.status = to_status
    parcel.save(update_fields=["status", "compartment", "pickup_attempts", "updated_at"])
    ParcelEvent.objects.create(
        parcel=parcel,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        reason=reason,
    )
    return parcel
