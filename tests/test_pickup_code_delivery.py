import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django_tenants.utils import tenant_context

from accounts import sms
from devices.simulator import SimulatedDevice
from lockers.models import Compartment, CompartmentSize, Locker
from parcels import services
from parcels.models import Parcel, ParcelEvent, ParcelStatus
from parcels.pickup import PickupBlocked, pickup_parcel
from parcels.pickup_code import pickup_code_matches
from parcels.services import (
    PickupCodeDeliveryFailed,
    create_parcel,
    deposit_parcel,
    issue_pickup_code,
    send_pickup_code,
)
from parcels.state_machine import (
    MAX_PICKUP_ATTEMPTS,
    InvalidTransition,
    PickupAttemptsExhausted,
)

pytestmark = pytest.mark.django_db(transaction=True)

S = ParcelStatus
E164 = "+989123456789"


@pytest.fixture
def tenant(make_org):
    organization = make_org("acme")
    with tenant_context(organization):
        yield organization


@pytest.fixture
def locker(tenant):
    return Locker.objects.create(code="one", name="One")


def stored_parcel(locker):
    Compartment.objects.create(locker=locker, number=1, size=CompartmentSize.SMALL)
    parcel = create_parcel(
        locker=locker,
        recipient_phone="09123456789",
        size=CompartmentSize.SMALL,
        actor="test",
    )
    return deposit_parcel(parcel.pk, actor="courier")


def ready_parcel(locker):
    parcel = stored_parcel(locker)
    return parcel, issue_pickup_code(parcel.pk, actor="system")


def code_in(message):
    return message.rsplit(" ", 1)[-1]


class FailingBackend(sms.SmsBackend):
    def send(self, phone_number, message):
        raise sms.SmsDeliveryError("provider is down")


class BrokenConfigBackend(sms.SmsBackend):
    def send(self, phone_number, message):
        raise ImproperlyConfigured("no SMS settings")


# Re-sending through issue_pickup_code


def test_a_resend_replaces_the_code(locker, monkeypatch):
    codes = iter(["111111", "222222"])
    monkeypatch.setattr(services, "generate_pickup_code", lambda: next(codes))
    parcel, _ = ready_parcel(locker)
    issue_pickup_code(parcel.pk, actor="operator")
    parcel.refresh_from_db()
    assert parcel.status == S.READY_FOR_PICKUP
    assert pickup_code_matches(parcel, "222222")
    assert not pickup_code_matches(parcel, "111111")


def test_a_resend_is_recorded(locker):
    parcel, _ = ready_parcel(locker)
    issue_pickup_code(parcel.pk, actor="user:7")
    event = ParcelEvent.objects.filter(parcel=parcel).last()
    assert (event.from_status, event.to_status) == ("READY_FOR_PICKUP",) * 2
    assert (event.actor, event.reason) == ("user:7", "pickup code re-sent")


def test_a_resend_frees_a_parcel_blocked_by_wrong_codes(locker):
    parcel, old_code = ready_parcel(locker)
    Parcel.objects.filter(pk=parcel.pk).update(wrong_code_attempts=3)
    device = SimulatedDevice()
    with pytest.raises(PickupBlocked):
        pickup_parcel(parcel.pk, old_code, device=device, actor="user")

    new_code = issue_pickup_code(parcel.pk, actor="operator")
    parcel.refresh_from_db()
    assert parcel.wrong_code_attempts == 0
    assert pickup_parcel(parcel.pk, new_code, device=device, actor="user").delivered


def test_a_finished_parcel_gets_no_code(locker):
    parcel = stored_parcel(locker)
    Parcel.objects.filter(pk=parcel.pk).update(status=S.DELIVERED)
    with pytest.raises(InvalidTransition):
        issue_pickup_code(parcel.pk, actor="operator")
    parcel.refresh_from_db()
    assert parcel.pickup_code_hash == ""


# send_pickup_code


def test_the_code_is_texted_to_the_recipient(locker, sms_outbox):
    parcel = stored_parcel(locker)
    send_pickup_code(parcel.pk, actor="operator")
    assert len(sms_outbox) == 1
    phone, message = sms_outbox[0]
    assert phone == E164
    assert parcel.tracking_code in message
    parcel.refresh_from_db()
    assert parcel.status == S.READY_FOR_PICKUP
    assert pickup_code_matches(parcel, code_in(message))


def test_the_code_is_not_kept_anywhere_readable(locker, sms_outbox):
    parcel = stored_parcel(locker)
    send_pickup_code(parcel.pk, actor="operator")
    code = code_in(sms_outbox[0][1])
    parcel.refresh_from_db()
    assert code not in parcel.pickup_code_hash
    for event in ParcelEvent.objects.filter(parcel=parcel):
        assert code not in event.reason


def test_sending_again_invalidates_the_previous_text(locker, sms_outbox):
    parcel = stored_parcel(locker)
    send_pickup_code(parcel.pk, actor="operator")
    send_pickup_code(parcel.pk, actor="operator")
    first, second = (code_in(message) for _, message in sms_outbox)
    parcel.refresh_from_db()
    assert pickup_code_matches(parcel, second)
    assert first == second or not pickup_code_matches(parcel, first)


def test_a_failed_sms_leaves_the_parcel_ready_and_can_be_repeated(locker, monkeypatch):
    parcel = stored_parcel(locker)
    monkeypatch.setattr(sms, "get_sms_backend", lambda: FailingBackend())
    with pytest.raises(PickupCodeDeliveryFailed):
        send_pickup_code(parcel.pk, actor="operator")
    parcel.refresh_from_db()
    assert parcel.status == S.READY_FOR_PICKUP
    assert ParcelEvent.objects.filter(parcel=parcel).last().reason == (
        "pickup code SMS failed"
    )

    delivered = []

    class RecordingBackend(sms.SmsBackend):
        def send(self, phone_number, message):
            delivered.append((phone_number, message))

    monkeypatch.setattr(sms, "get_sms_backend", lambda: RecordingBackend())
    send_pickup_code(parcel.pk, actor="operator")  # the provider is back
    parcel.refresh_from_db()
    assert pickup_code_matches(parcel, code_in(delivered[0][1]))


def test_a_misconfigured_provider_is_not_disguised(locker, monkeypatch):
    parcel = stored_parcel(locker)
    monkeypatch.setattr(sms, "get_sms_backend", lambda: BrokenConfigBackend())
    with pytest.raises(ImproperlyConfigured):
        send_pickup_code(parcel.pk, actor="operator")


def test_a_blocked_retry_sends_nothing(locker, sms_outbox):
    parcel = stored_parcel(locker)
    Parcel.objects.filter(pk=parcel.pk).update(
        status=S.PICKUP_FAILED, pickup_attempts=MAX_PICKUP_ATTEMPTS
    )
    with pytest.raises(PickupAttemptsExhausted):
        send_pickup_code(parcel.pk, actor="operator")
    assert sms_outbox == []


def test_sending_refuses_to_run_inside_a_transaction(locker, sms_outbox):
    parcel = stored_parcel(locker)
    with transaction.atomic(), pytest.raises(RuntimeError):
        send_pickup_code(parcel.pk, actor="operator")
    assert sms_outbox == []


def test_concurrent_sends_leave_exactly_one_valid_code(
    tenant, locker, sms_outbox, run_concurrently
):
    parcel, _ = ready_parcel(locker)

    def send():
        with tenant_context(tenant):
            send_pickup_code(parcel.pk, actor="operator")

    outcomes = run_concurrently(send, 4)
    assert all(error is None for _result, error in outcomes)
    parcel.refresh_from_db()
    sent = [code_in(message) for _, message in sms_outbox]
    assert len(sent) == 4
    assert sum(pickup_code_matches(parcel, code) for code in sent) == 1
