from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts import otp
from accounts.models import OTPChallenge, User

PHONE = "09123456789"
E164 = "+989123456789"

pytestmark = pytest.mark.django_db


@pytest.fixture
def fixed_codes(monkeypatch):
    codes = iter(["111111", "222222", "333333"])
    monkeypatch.setattr(otp, "_generate_code", lambda: next(codes))


def test_request_stores_only_a_hash_and_sends_the_sms(fixed_codes, sms_outbox):
    otp.request_otp(PHONE)
    challenge = OTPChallenge.objects.get()
    assert challenge.phone_number == E164
    assert challenge.code_hash != "111111"
    assert len(challenge.code_hash) == 64
    assert len(sms_outbox) == 1
    recipient, message = sms_outbox[0]
    assert recipient == E164
    assert "111111" in message


def test_verify_registers_a_new_user(fixed_codes):
    otp.request_otp(PHONE)
    user = otp.verify_otp(PHONE, "111111")
    assert user.phone_number == E164
    assert not user.has_usable_password()
    assert User.objects.count() == 1
    assert OTPChallenge.objects.get().consumed_at is not None


def test_verify_signs_in_an_existing_user(fixed_codes):
    existing = User.objects.create_user(phone_number=PHONE)
    otp.request_otp(PHONE)
    assert otp.verify_otp(PHONE, "111111") == existing
    assert User.objects.count() == 1


def test_wrong_code_is_rejected_and_the_attempt_is_persisted(fixed_codes):
    otp.request_otp(PHONE)
    with pytest.raises(otp.InvalidOTP):
        otp.verify_otp(PHONE, "999999")
    assert OTPChallenge.objects.get().attempts == 1
    assert not User.objects.exists()


def test_challenge_is_locked_after_too_many_wrong_attempts(fixed_codes, settings):
    otp.request_otp(PHONE)
    for _ in range(settings.OTP_MAX_ATTEMPTS):
        with pytest.raises(otp.InvalidOTP):
            otp.verify_otp(PHONE, "999999")
    with pytest.raises(otp.InvalidOTP):
        otp.verify_otp(PHONE, "111111")
    assert not User.objects.exists()


def test_expired_code_is_rejected(fixed_codes):
    otp.request_otp(PHONE)
    OTPChallenge.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(otp.InvalidOTP):
        otp.verify_otp(PHONE, "111111")


def test_code_can_be_used_only_once(fixed_codes):
    otp.request_otp(PHONE)
    otp.verify_otp(PHONE, "111111")
    with pytest.raises(otp.InvalidOTP):
        otp.verify_otp(PHONE, "111111")


def test_resend_is_blocked_during_the_cooldown(fixed_codes, sms_outbox, settings):
    otp.request_otp(PHONE)
    with pytest.raises(otp.OTPCooldown) as exc:
        otp.request_otp(PHONE)
    assert 0 < exc.value.retry_after <= settings.OTP_RESEND_COOLDOWN_SECONDS
    assert len(sms_outbox) == 1


def test_resend_after_the_cooldown_invalidates_the_previous_code(fixed_codes):
    otp.request_otp(PHONE)
    OTPChallenge.objects.update(created_at=timezone.now() - timedelta(minutes=5))
    otp.request_otp(PHONE)
    with pytest.raises(otp.InvalidOTP):
        otp.verify_otp(PHONE, "111111")
    assert otp.verify_otp(PHONE, "222222").phone_number == E164


def test_unknown_number_gets_the_same_error_as_a_wrong_code():
    with pytest.raises(otp.InvalidOTP):
        otp.verify_otp(PHONE, "111111")


def test_invalid_phone_number_is_rejected_on_request():
    with pytest.raises(ValidationError):
        otp.request_otp("12345")


def test_sms_failure_removes_the_challenge(fixed_codes, monkeypatch):
    class FailingBackend:
        def send(self, phone_number, message):
            raise RuntimeError("provider down")

    monkeypatch.setattr(otp, "get_sms_backend", lambda: FailingBackend())
    with pytest.raises(RuntimeError):
        otp.request_otp(PHONE)
    assert not OTPChallenge.objects.exists()


def test_database_allows_only_one_open_challenge_per_phone():
    now = timezone.now()
    OTPChallenge.objects.create(phone_number=E164, code_hash="a", expires_at=now)
    with pytest.raises(IntegrityError), transaction.atomic():
        OTPChallenge.objects.create(phone_number=E164, code_hash="b", expires_at=now)
