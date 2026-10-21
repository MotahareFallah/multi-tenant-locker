from datetime import timedelta

import pytest
from django.utils import timezone

from accounts import otp
from accounts.models import OTPChallenge, OTPCloseReason, OTPPurpose

PHONE = "09123456789"
E164 = "+989123456789"
PURPOSE = OTPPurpose.CUSTOMER_SIGN_IN

pytestmark = [pytest.mark.concurrency, pytest.mark.django_db(transaction=True)]


def test_simultaneous_requests_create_one_challenge_and_send_one_sms(
    run_concurrently, sms_outbox
):
    results = run_concurrently(lambda: otp.request_otp(PHONE, purpose=PURPOSE), 6)
    errors = [error for _, error in results if error is not None]
    assert len(errors) == 5
    assert all(isinstance(error, otp.OTPCooldown) for error in errors)
    assert OTPChallenge.objects.count() == 1
    assert OTPChallenge.objects.filter(closed_at__isnull=True).count() == 1
    assert len(sms_outbox) == 1


def test_the_request_cap_cannot_be_exceeded_concurrently(
    run_concurrently, settings, sms_outbox
):
    old = timezone.now() - timedelta(minutes=10)
    for _ in range(settings.OTP_MAX_REQUESTS_PER_WINDOW - 1):
        challenge = OTPChallenge.objects.create(
            phone_number=E164,
            purpose=PURPOSE,
            code_hash="x",
            expires_at=old,
            closed_at=old,
            closed_reason=OTPCloseReason.SUPERSEDED,
        )
        OTPChallenge.objects.filter(pk=challenge.pk).update(created_at=old)
    results = run_concurrently(lambda: otp.request_otp(PHONE, purpose=PURPOSE), 6)
    errors = [error for _, error in results if error is not None]
    assert len(errors) == 5
    assert all(isinstance(error, otp.OTPThrottled) for error in errors)
    assert OTPChallenge.objects.count() == settings.OTP_MAX_REQUESTS_PER_WINDOW
    assert len(sms_outbox) == 1


def test_simultaneous_verifications_consume_the_code_once(
    run_concurrently, fixed_codes
):
    otp.request_otp(PHONE, purpose=PURPOSE)
    results = run_concurrently(
        lambda: otp.verify_otp(PHONE, "111111", purpose=PURPOSE), 6
    )
    verified = [result for result, error in results if error is None]
    errors = [error for _, error in results if error is not None]
    assert verified == [E164]
    assert len(errors) == 5
    assert all(isinstance(error, otp.InvalidOTP) for error in errors)
    assert OTPChallenge.objects.get().closed_reason == OTPCloseReason.CONSUMED


def test_concurrent_wrong_guesses_cannot_exceed_the_attempt_cap(
    run_concurrently, fixed_codes, settings
):
    otp.request_otp(PHONE, purpose=PURPOSE)
    results = run_concurrently(
        lambda: otp.verify_otp(PHONE, "999999", purpose=PURPOSE), 12
    )
    assert all(isinstance(error, otp.InvalidOTP) for _, error in results)
    assert OTPChallenge.objects.get().attempts == settings.OTP_MAX_ATTEMPTS
    with pytest.raises(otp.InvalidOTP):
        otp.verify_otp(PHONE, "111111", purpose=PURPOSE)
