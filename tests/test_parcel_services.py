from datetime import timedelta

import pytest
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.utils import timezone
from django_tenants.utils import tenant_context

from lockers.models import Compartment, CompartmentSize, Locker
from parcels import services
from parcels.models import Parcel, ParcelEvent, ParcelStatus
from parcels.pickup_code import PICKUP_CODE_LENGTH, pickup_code_matches
from parcels.services import (
    LockerUnavailable,
    NoFreeCompartment,
    create_parcel,
    deposit_parcel,
    issue_pickup_code,
)
from parcels.state_machine import (
    MAX_PICKUP_ATTEMPTS,
    InvalidTransition,
    PickupAttemptsExhausted,
    transition,
)

pytestmark = pytest.mark.django_db(transaction=True)

S = ParcelStatus
SMALL, LARGE = CompartmentSize.SMALL, CompartmentSize.LARGE


@pytest.fixture
def tenant(make_org):
    organization = make_org("acme")
    with tenant_context(organization):
        yield organization


@pytest.fixture
def locker(tenant):
    return Locker.objects.create(code="one", name="One")


def add_compartment(locker, number, size=SMALL, **extra):
    return Compartment.objects.create(locker=locker, number=number, size=size, **extra)


def new_parcel(locker, size=SMALL):
    return create_parcel(
        locker=locker, recipient_phone="09123456789", size=size, actor="test"
    )


def stored_parcel(locker, number=1):
    add_compartment(locker, number)
    return deposit_parcel(new_parcel(locker).pk, actor="courier")


# create_parcel


def test_create_normalizes_the_phone_and_records_the_event(locker):
    parcel = create_parcel(
        locker=locker, recipient_phone="0912 345 6789", size=SMALL, actor="user:1"
    )
    assert parcel.recipient_phone == "+989123456789"
    assert parcel.status == S.CREATED
    event = ParcelEvent.objects.get()
    assert (event.from_status, event.to_status, event.actor) == ("", "CREATED", "user:1")


def test_create_sets_the_storage_deadline(locker, settings):
    settings.PARCEL_STORAGE_DAYS = 3
    before = timezone.now()
    parcel = new_parcel(locker)
    assert (
        before + timedelta(days=3)
        <= parcel.expires_at
        <= timezone.now() + timedelta(days=3)
    )


def test_create_rejects_an_invalid_phone_number(locker):
    with pytest.raises(ValidationError):
        create_parcel(locker=locker, recipient_phone="12345", size=SMALL, actor="test")
    assert Parcel.objects.count() == 0


def test_create_rejects_an_unknown_size(locker):
    with pytest.raises(ValidationError):
        create_parcel(
            locker=locker, recipient_phone="09123456789", size="HUGE", actor="test"
        )
    assert Parcel.objects.count() == 0


def test_create_refuses_an_inactive_locker(locker):
    locker.is_active = False
    locker.save()
    with pytest.raises(LockerUnavailable):
        new_parcel(locker)


# deposit_parcel


def test_deposit_uses_the_lowest_numbered_free_compartment(locker):
    add_compartment(locker, 2)
    first = add_compartment(locker, 1)
    parcel = deposit_parcel(new_parcel(locker).pk, actor="courier")
    assert parcel.status == S.STORED
    assert parcel.compartment == first
    assert ParcelEvent.objects.filter(parcel=parcel).last().to_status == "STORED"


def test_deposit_skips_wrong_size_inactive_and_occupied_compartments(locker):
    add_compartment(locker, 1, LARGE)
    add_compartment(locker, 2, SMALL, is_active=False)
    busy = add_compartment(locker, 3)
    target = add_compartment(locker, 4)
    first = deposit_parcel(new_parcel(locker).pk, actor="courier")
    second = deposit_parcel(new_parcel(locker).pk, actor="courier")
    assert first.compartment == busy
    assert second.compartment == target


def test_deposit_fails_when_nothing_is_free(locker):
    add_compartment(locker, 1)
    stored = deposit_parcel(new_parcel(locker).pk, actor="courier")
    waiting = new_parcel(locker)
    with pytest.raises(NoFreeCompartment):
        deposit_parcel(waiting.pk, actor="courier")
    waiting.refresh_from_db()
    assert waiting.status == S.CREATED
    assert stored.compartment_id is not None


def test_deposit_fails_when_only_another_size_exists(locker):
    add_compartment(locker, 1, LARGE)
    with pytest.raises(NoFreeCompartment):
        deposit_parcel(new_parcel(locker, SMALL).pk, actor="courier")


def test_a_compartment_is_reused_after_delivery(locker):
    add_compartment(locker, 1)
    first = deposit_parcel(new_parcel(locker).pk, actor="courier")
    for status in (S.READY_FOR_PICKUP, S.PICKUP_IN_PROGRESS, S.DELIVERED):
        transition(first.pk, status, actor="test")
    second = deposit_parcel(new_parcel(locker).pk, actor="courier")
    assert second.compartment_id == first.compartment_id


def test_a_deposited_parcel_cannot_be_deposited_again(locker):
    parcel = stored_parcel(locker)
    with pytest.raises(InvalidTransition):
        deposit_parcel(parcel.pk, actor="courier")


def test_deposit_refuses_an_inactive_locker(locker):
    add_compartment(locker, 1)
    parcel = new_parcel(locker)
    locker.is_active = False
    locker.save()
    with pytest.raises(LockerUnavailable):
        deposit_parcel(parcel.pk, actor="courier")


# issue_pickup_code


def test_issue_returns_the_code_and_stores_only_its_hash(locker):
    parcel = stored_parcel(locker)
    code = issue_pickup_code(parcel.pk, actor="system")
    parcel.refresh_from_db()
    assert len(code) == PICKUP_CODE_LENGTH and code.isdigit()
    assert parcel.status == S.READY_FOR_PICKUP
    assert len(parcel.pickup_code_hash) == 64
    assert code not in parcel.pickup_code_hash
    assert pickup_code_matches(parcel, code)
    wrong = "000000" if code != "000000" else "000001"
    assert not pickup_code_matches(parcel, wrong)
    assert not pickup_code_matches(parcel, None)


def test_the_same_code_hashes_differently_for_each_parcel(locker, monkeypatch):
    monkeypatch.setattr(services, "generate_pickup_code", lambda: "123456")
    first, second = stored_parcel(locker, 1), stored_parcel(locker, 2)
    issue_pickup_code(first.pk, actor="system")
    issue_pickup_code(second.pk, actor="system")
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.pickup_code_hash != second.pickup_code_hash
    assert pickup_code_matches(first, "123456")
    assert pickup_code_matches(second, "123456")


def test_a_parcel_without_a_code_matches_nothing(locker):
    parcel = new_parcel(locker)
    assert not pickup_code_matches(parcel, "123456")


def test_a_rejected_issue_leaves_no_code_behind(locker):
    parcel = new_parcel(locker)  # still CREATED, so it cannot become ready
    with pytest.raises(InvalidTransition):
        issue_pickup_code(parcel.pk, actor="system")
    parcel.refresh_from_db()
    assert parcel.pickup_code_hash == ""


def test_a_retry_after_a_failed_pickup_gets_a_new_code(locker, monkeypatch):
    codes = iter(["111111", "222222"])
    monkeypatch.setattr(services, "generate_pickup_code", lambda: next(codes))
    parcel = stored_parcel(locker)
    issue_pickup_code(parcel.pk, actor="system")
    transition(parcel.pk, S.PICKUP_IN_PROGRESS, actor="test")
    transition(parcel.pk, S.PICKUP_FAILED, actor="device")
    issue_pickup_code(parcel.pk, actor="system")
    parcel.refresh_from_db()
    assert pickup_code_matches(parcel, "222222")
    assert not pickup_code_matches(parcel, "111111")


def test_no_new_code_is_issued_when_retries_are_exhausted(locker):
    parcel = stored_parcel(locker)
    Parcel.objects.filter(pk=parcel.pk).update(
        status=S.PICKUP_FAILED, pickup_attempts=MAX_PICKUP_ATTEMPTS
    )
    with pytest.raises(PickupAttemptsExhausted):
        issue_pickup_code(parcel.pk, actor="system")
    parcel.refresh_from_db()
    assert parcel.pickup_code_hash == ""


def test_issue_needs_the_hmac_key(locker, settings):
    parcel = stored_parcel(locker)
    settings.OTP_HMAC_KEY = ""
    with pytest.raises(ImproperlyConfigured):
        issue_pickup_code(parcel.pk, actor="system")
    parcel.refresh_from_db()
    assert parcel.status == S.STORED
