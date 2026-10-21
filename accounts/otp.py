import hashlib
import hmac
import math
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import OTPChallenge, User
from .phone import normalize_phone_number
from .sms import get_sms_backend


class OTPError(Exception):
    pass


class InvalidOTP(OTPError):
    """Wrong, expired, used or unknown code. Deliberately one error for all."""


class OTPCooldown(OTPError):
    def __init__(self, retry_after: int):
        super().__init__(f"Retry after {retry_after} seconds.")
        self.retry_after = retry_after


def _generate_code() -> str:
    length = settings.OTP_LENGTH
    return f"{secrets.randbelow(10**length):0{length}d}"


def _hash_code(phone_number: str, code: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(),
        f"{phone_number}:{code}".encode(),
        hashlib.sha256,
    ).hexdigest()


def request_otp(raw_phone_number: str) -> None:
    """Create a fresh challenge for the number and send the code by SMS."""
    phone_number = normalize_phone_number(raw_phone_number)
    code = _generate_code()
    now = timezone.now()
    cooldown = timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS)
    try:
        with transaction.atomic():
            latest = (
                OTPChallenge.objects.select_for_update()
                .filter(phone_number=phone_number)
                .order_by("-created_at")
                .first()
            )
            if latest is not None and now - latest.created_at < cooldown:
                remaining = latest.created_at + cooldown - now
                raise OTPCooldown(max(1, math.ceil(remaining.total_seconds())))
            OTPChallenge.objects.filter(
                phone_number=phone_number, consumed_at__isnull=True
            ).update(consumed_at=now)
            challenge = OTPChallenge.objects.create(
                phone_number=phone_number,
                code_hash=_hash_code(phone_number, code),
                expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS),
            )
    except IntegrityError:
        # A concurrent request created the open challenge first.
        raise OTPCooldown(settings.OTP_RESEND_COOLDOWN_SECONDS) from None
    try:
        get_sms_backend().send(phone_number, f"Your verification code is {code}")
    except Exception:
        challenge.delete()
        raise


def verify_otp(raw_phone_number: str, code: str) -> User:
    """Consume a valid code and return the user, creating it on first sign-in."""
    try:
        phone_number = normalize_phone_number(raw_phone_number)
    except ValidationError:
        raise InvalidOTP from None
    now = timezone.now()
    user = None
    # Failures are raised after the atomic block so that the attempt counter
    # is committed instead of being rolled back.
    with transaction.atomic():
        challenge = (
            OTPChallenge.objects.select_for_update()
            .filter(phone_number=phone_number, consumed_at__isnull=True)
            .first()
        )
        if (
            challenge is None
            or challenge.expires_at <= now
            or challenge.attempts >= settings.OTP_MAX_ATTEMPTS
        ):
            valid = False
        elif not hmac.compare_digest(
            challenge.code_hash, _hash_code(phone_number, code)
        ):
            challenge.attempts += 1
            challenge.save(update_fields=["attempts"])
            valid = False
        else:
            challenge.consumed_at = now
            challenge.save(update_fields=["consumed_at"])
            user = User.objects.filter(phone_number=phone_number).first()
            if user is None:
                user = User.objects.create_user(phone_number=phone_number)
            valid = user.is_active
    if not valid:
        raise InvalidOTP
    return user
