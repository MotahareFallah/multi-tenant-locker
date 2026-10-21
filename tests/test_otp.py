from datetime import timedelta

import pytest
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts import otp
from accounts.models import OTPChallenge, OTPCloseReason, OTPPurpose, User

PHONE = "09123456789"
E164 = "+989123456789"
PURPOSE = OTPPurpose.CUSTOMER_SIGN_IN

pytestmark = pytest.mark.django_db


class FailingBackend:
    def send(self, phone_number, message):
        raise RuntimeError("provider down")


def test_request_stores_only_a_hash_and_sends_the_sms(fixed_codes, sms_outbox):
    otp.request_otp(PHONE, purpose=PURPOSE)
    challenge = OTPChallenge.objects.get()
    assert challenge.phone_number == E164
    assert challenge.purpose == PURPOSE
    assert challenge.code_hash != "111111"
    assert len(challenge.code_hash) == 64
    assert len(sms_outbox) == 1
    recipient, message = sms_outbox[0]
    assert recipient == E164
    assert "111111" in message


def test_verify_returns_the_number_and_creates_no_user(fixed_codes):
    otp.request_otp(PHONE, purpose=PURPOSE)
    assert otp.verify_otp(PHONE, "111111", purpose=PURPOSE) == E164
    assert not User.objects.exists()
    challenge = OTPChallenge.objects.get()
    assert challenge.closed_at is not None
    assert challenge.closed_reason == OTPCloseReason.CONSUMED


def test_wrong_code_is_rejected_and_the_attempt_is_persisted(fixed_codes):
    otp.request_otp(PHONE, purpose=PURPOSE)
    with pytest.raises(otp.InvalidOTP):
        otp.verify_otp(PHONE, "999999", purpose=PURPOSE)
    assert OTPChallenge.objects.get().attempts == 1


def test_challenge_is_locked_after_too_many_wrong_attempts(fixed_codes, settings):
    otp.request_otp(PHONE, purpose=PURPOSE)
    for _ in range(settings.OTP_MAX_ATTEMPTS):
        with pytest.raises(otp.InvalidOTP):
            otp.verify_otp(PHONE, "999999", purpose=PURPOSE)
    with pytest.raises(otp.InvalidOTP):
        otp.verify_otp(PHONE, "111111", purpose=PURPOSE)


def test_expired_code_is_rejected(fixed_codes):
    otp.request_otp(PHONE, purpose=PURPOSE)
    OTPChallenge.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(otp.InvalidOTP):
        otp.verify_otp(PHONE, "111111", purpose=PURPOSE)


def test_code_can_be_used_only_once(fixed_codes):
    otp.request_otp(PHONE, purpose=PURPOSE)
    otp.verify_otp(PHONE, "111111", purpose=PURPOSE)
    with pytest.raises(otp.InvalidOTP):
        otp.verify_otp(PHONE, "111111", purpose=PURPOSE)


def test_resend_is_blocked_during_the_cooldown(fixed_codes, sms_outbox, settings):
    otp.request_otp(PHONE, purpose=PURPOSE)
    with pytest.raises(otp.OTPCooldown) as exc:
        otp.request_otp(PHONE, purpose=PURPOSE)
    assert 0 < exc.value.retry_after <= settings.OTP_RESEND_COOLDOWN_SECONDS
    assert len(sms_outbox) == 1


def test_resend_after_the_cooldown_invalidates_the_previous_code(fixed_codes):
    otp.request_otp(PHONE, purpose=PURPOSE)
    OTPChallenge.objects.update(created_at=timezone.now() - timedelta(minutes=5))
    otp.request_otp(PHONE, purpose=PURPOSE)
    with pytest.raises(otp.InvalidOTP):
        otp.verify_otp(PHONE, "111111", purpose=PURPOSE)
    assert otp.verify_otp(PHONE, "222222", purpose=PURPOSE) == E164
    reasons = set(OTPChallenge.objects.values_list("closed_reason", flat=True))
    assert reasons == {OTPCloseReason.SUPERSEDED, OTPCloseReason.CONSUMED}


def test_unknown_number_gets_the_same_error_as_a_wrong_code():
    with pytest.raises(otp.InvalidOTP):
        otp.verify_otp(PHONE, "111111", purpose=PURPOSE)


def test_invalid_phone_number_is_rejected_on_request():
    with pytest.raises(ValidationError):
        otp.request_otp("12345", purpose=PURPOSE)


def test_failed_delivery_closes_the_challenge_but_keeps_the_record(
    fixed_codes, monkeypatch
):
    monkeypatch.setattr(otp, "get_sms_backend", lambda: FailingBackend())
    with pytest.raises(RuntimeError):
        otp.request_otp(PHONE, purpose=PURPOSE)
    challenge = OTPChallenge.objects.get()
    assert challenge.closed_reason == OTPCloseReason.DELIVERY_FAILED
    with pytest.raises(otp.InvalidOTP):
        otp.verify_otp(PHONE, "111111", purpose=PURPOSE)


def test_failed_delivery_does_not_trigger_the_resend_cooldown(
    fixed_codes, monkeypatch
):
    working_backend = otp.get_sms_backend
    monkeypatch.setattr(otp, "get_sms_backend", lambda: FailingBackend())
    with pytest.raises(RuntimeError):
        otp.request_otp(PHONE, purpose=PURPOSE)
    monkeypatch.setattr(otp, "get_sms_backend", working_backend)
    otp.request_otp(PHONE, purpose=PURPOSE)
    assert otp.verify_otp(PHONE, "222222", purpose=PURPOSE) == E164


def test_requests_per_phone_are_capped_within_the_window(settings):
    for _ in range(settings.OTP_MAX_REQUESTS_PER_WINDOW):
        otp.request_otp(PHONE, purpose=PURPOSE)
        OTPChallenge.objects.update(created_at=timezone.now() - timedelta(minutes=10))
    with pytest.raises(otp.OTPRateLimited) as exc:
        otp.request_otp(PHONE, purpose=PURPOSE)
    assert 0 < exc.value.retry_after <= settings.OTP_RATE_WINDOW_SECONDS
    assert OTPChallenge.objects.count() == settings.OTP_MAX_REQUESTS_PER_WINDOW


def test_codes_are_bound_to_their_purpose(fixed_codes):
    otp.request_otp(PHONE, purpose=PURPOSE)
    with pytest.raises(otp.InvalidOTP):
        otp.verify_otp(PHONE, "111111", purpose="other_purpose")
    assert otp.verify_otp(PHONE, "111111", purpose=PURPOSE) == E164


def test_purposes_do_not_supersede_each_other(fixed_codes):
    otp.request_otp(PHONE, purpose=PURPOSE)
    otp.request_otp(PHONE, purpose="other_purpose")
    assert OTPChallenge.objects.filter(closed_at__isnull=True).count() == 2
    assert otp.verify_otp(PHONE, "111111", purpose=PURPOSE) == E164


def test_hmac_key_is_required(settings):
    settings.OTP_HMAC_KEY = ""
    with pytest.raises(ImproperlyConfigured):
        otp.request_otp(PHONE, purpose=PURPOSE)
    assert not OTPChallenge.objects.exists()


def test_database_allows_one_open_challenge_per_phone_and_purpose():
    now = timezone.now()
    OTPChallenge.objects.create(
        phone_number=E164, purpose=PURPOSE, code_hash="a", expires_at=now
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        OTPChallenge.objects.create(
            phone_number=E164, purpose=PURPOSE, code_hash="b", expires_at=now
        )
    OTPChallenge.objects.create(
        phone_number=E164, purpose="other_purpose", code_hash="c", expires_at=now
    )


def test_database_requires_a_reason_for_closed_challenges():
    now = timezone.now()
    with pytest.raises(IntegrityError), transaction.atomic():
        OTPChallenge.objects.create(
            phone_number=E164, code_hash="a", expires_at=now, closed_at=now
        )
