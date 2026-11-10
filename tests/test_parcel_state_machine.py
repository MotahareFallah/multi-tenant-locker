import itertools

import pytest
from django_tenants.utils import tenant_context

from lockers.models import Compartment, CompartmentSize, Locker
from parcels.models import OCCUPYING_STATUSES, Parcel, ParcelEvent, ParcelStatus
from parcels.state_machine import (
    MAX_PICKUP_ATTEMPTS,
    InvalidTransition,
    PickupAttemptsExhausted,
    transition,
)

pytestmark = pytest.mark.django_db(transaction=True)

S = ParcelStatus
PHONE = "+989120000001"
numbers = itertools.count(1)

# Written out on purpose: this is the table from ADR-0003. Changing the rules
# means changing the ADR and this list together.
ALLOWED = {
    (S.CREATED, S.STORED),
    (S.CREATED, S.EXPIRED),
    (S.STORED, S.READY_FOR_PICKUP),
    (S.STORED, S.EXPIRED),
    (S.READY_FOR_PICKUP, S.PICKUP_IN_PROGRESS),
    (S.READY_FOR_PICKUP, S.EXPIRED),
    (S.PICKUP_IN_PROGRESS, S.DELIVERED),
    (S.PICKUP_IN_PROGRESS, S.PICKUP_FAILED),
    (S.PICKUP_FAILED, S.READY_FOR_PICKUP),
    (S.PICKUP_FAILED, S.EXPIRED),
}


@pytest.fixture
def tenant(make_org):
    organization = make_org("acme")
    with tenant_context(organization):
        yield organization


def free_compartment(locker):
    return Compartment.objects.create(
        locker=locker, number=next(numbers), size=CompartmentSize.SMALL
    )


def new_parcel(status=S.CREATED, attempts=0):
    locker, _ = Locker.objects.get_or_create(code="one", defaults={"name": "One"})
    compartment = free_compartment(locker) if status in OCCUPYING_STATUSES else None
    return Parcel.objects.create(
        locker=locker,
        compartment=compartment,
        recipient_phone=PHONE,
        size=CompartmentSize.SMALL,
        status=status,
        pickup_attempts=attempts,
    )


def test_only_the_documented_transitions_are_allowed(tenant):
    allowed = set()
    for source in S:
        for target in S:
            parcel = new_parcel(source)
            compartment = None
            if (source, target) == (S.CREATED, S.STORED):
                compartment = free_compartment(parcel.locker)
            try:
                transition(parcel.pk, target, actor="test", compartment=compartment)
            except InvalidTransition:
                continue
            allowed.add((source, target))
    assert allowed == ALLOWED


def test_a_transition_updates_the_parcel_and_records_the_event(tenant):
    parcel = new_parcel(S.CREATED)
    compartment = free_compartment(parcel.locker)
    transition(
        parcel.pk, S.STORED, actor="user:5", reason="deposited", compartment=compartment
    )
    parcel.refresh_from_db()
    assert parcel.status == S.STORED
    assert parcel.compartment == compartment
    event = ParcelEvent.objects.get()
    assert (event.from_status, event.to_status) == ("CREATED", "STORED")
    assert (event.actor, event.reason) == ("user:5", "deposited")


def test_a_rejected_transition_changes_nothing(tenant):
    parcel = new_parcel(S.DELIVERED)
    with pytest.raises(InvalidTransition):
        transition(parcel.pk, S.READY_FOR_PICKUP, actor="test")
    parcel.refresh_from_db()
    assert parcel.status == S.DELIVERED
    assert ParcelEvent.objects.count() == 0


def test_storing_needs_a_compartment(tenant):
    parcel = new_parcel(S.CREATED)
    with pytest.raises(InvalidTransition):
        transition(parcel.pk, S.STORED, actor="test")
    parcel.refresh_from_db()
    assert parcel.status == S.CREATED


def test_a_compartment_is_only_assigned_when_storing(tenant):
    parcel = new_parcel(S.STORED)
    original = parcel.compartment
    other = free_compartment(parcel.locker)
    with pytest.raises(InvalidTransition):
        transition(parcel.pk, S.READY_FOR_PICKUP, actor="test", compartment=other)
    parcel.refresh_from_db()
    assert parcel.compartment == original


def test_an_unknown_target_status_is_rejected(tenant):
    parcel = new_parcel(S.CREATED)
    with pytest.raises(InvalidTransition):
        transition(parcel.pk, "LOST", actor="test")


def test_an_actor_is_required(tenant):
    parcel = new_parcel(S.CREATED)
    with pytest.raises(ValueError):
        transition(parcel.pk, S.EXPIRED, actor="")


def test_a_failed_pickup_counts_as_an_attempt(tenant):
    parcel = new_parcel(S.PICKUP_IN_PROGRESS)
    transition(parcel.pk, S.PICKUP_FAILED, actor="device")
    parcel.refresh_from_db()
    assert parcel.pickup_attempts == 1


def test_a_retry_is_allowed_below_the_limit(tenant):
    parcel = new_parcel(S.PICKUP_FAILED, attempts=MAX_PICKUP_ATTEMPTS - 1)
    transition(parcel.pk, S.READY_FOR_PICKUP, actor="test")
    parcel.refresh_from_db()
    assert parcel.status == S.READY_FOR_PICKUP


def test_a_retry_is_blocked_at_the_limit(tenant):
    parcel = new_parcel(S.PICKUP_FAILED, attempts=MAX_PICKUP_ATTEMPTS)
    with pytest.raises(PickupAttemptsExhausted):
        transition(parcel.pk, S.READY_FOR_PICKUP, actor="test")
    parcel.refresh_from_db()
    assert parcel.status == S.PICKUP_FAILED


def test_an_operator_can_override_the_retry_limit(tenant):
    parcel = new_parcel(S.PICKUP_FAILED, attempts=MAX_PICKUP_ATTEMPTS)
    transition(
        parcel.pk, S.READY_FOR_PICKUP, actor="operator", override_retry_limit=True
    )
    parcel.refresh_from_db()
    assert parcel.status == S.READY_FOR_PICKUP
    assert parcel.pickup_attempts == 0


def test_a_blocked_parcel_can_still_expire(tenant):
    parcel = new_parcel(S.PICKUP_FAILED, attempts=MAX_PICKUP_ATTEMPTS)
    transition(parcel.pk, S.EXPIRED, actor="system")
    parcel.refresh_from_db()
    assert parcel.status == S.EXPIRED


def test_repeated_failures_end_in_a_blocked_parcel(tenant):
    parcel = new_parcel(S.READY_FOR_PICKUP)
    for attempt in range(1, MAX_PICKUP_ATTEMPTS + 1):
        transition(parcel.pk, S.PICKUP_IN_PROGRESS, actor="test")
        transition(parcel.pk, S.PICKUP_FAILED, actor="device")
        if attempt < MAX_PICKUP_ATTEMPTS:
            transition(parcel.pk, S.READY_FOR_PICKUP, actor="test")
    with pytest.raises(PickupAttemptsExhausted):
        transition(parcel.pk, S.READY_FOR_PICKUP, actor="test")
