"""OTP challenges: proof that someone controls a phone number.

Verifying a code proves phone ownership only. It never creates users, roles or
organization memberships; those belong to the flows that call into this module.
"""

import hashlib
import hmac
import math
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import connection, transaction
from django.utils import timezone

from .models import OTPChallenge, OTPCloseReason
from .phone import normalize_phone_number
from .sms import get_sms_backend


class OTPError(Exception):
    pass


class InvalidOTP(OTPError):
    """Wrong, expired, used or unknown code. Deliberately one error for all."""


class OTPThrottled(OTPError):
    def __init__(self, retry_after: int):
        super().__init__(f"Retry after {retry_after} seconds.")
        self.retry_after = retry_after


class OTPCooldown(OTPThrottled):
    """A code was sent very recently."""


class OTPRateLimited(OTPThrottled):
    """Too many codes were requested for this number in the current window."""


def _generate_code() -> str:
    length = settings.OTP_LENGTH
    return f"{secrets.randbelow(10**length):0{length}d}"


def _hash_code(purpose: str, phone_number: str, code: str) -> str:
    key = settings.OTP_HMAC_KEY
    if not key:
        raise ImproperlyConfigured("OTP_HMAC_KEY must be set.")
    return hmac.new(
        key.encode(),
        f"{purpose}:{phone_number}:{code}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _seconds(delta: timedelta) -> int:
    return max(1, math.ceil(delta.total_seconds()))


def _lock_requests(phone_number: str, purpose: str) -> None:
    """Serialize concurrent requests for one (phone, purpose) until commit.

    Row locks are not enough here: rows inserted by a concurrent request are
    invisible to a statement that is already waiting, so the cooldown and the
    window count would be stale. A transaction-level advisory lock exists even
    when there are no rows yet, and the queries that follow it see fresh data.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"otp:{purpose}:{phone_number}"],
        )


def request_otp(raw_phone_number: str, *, purpose: str) -> None:
    """Create a fresh challenge for the number and send the code by SMS.

    Concurrent calls for the same (phone, purpose) run one after another: the
    first creates the challenge, the others are rejected by the cooldown.
    """
    phone_number = normalize_phone_number(raw_phone_number)
    code = _generate_code()
    now = timezone.now()
    window = timedelta(seconds=settings.OTP_RATE_WINDOW_SECONDS)
    cooldown = timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS)
    with transaction.atomic():
        _lock_requests(phone_number, purpose)
        recent = list(
            OTPChallenge.objects.filter(
                phone_number=phone_number,
                purpose=purpose,
                created_at__gte=now - window,
            ).order_by("created_at")
        )
        if len(recent) >= settings.OTP_MAX_REQUESTS_PER_WINDOW:
            raise OTPRateLimited(_seconds(recent[0].created_at + window - now))
        # A failed delivery sent nothing, so it must not block a retry.
        delivered = [
            c for c in recent if c.closed_reason != OTPCloseReason.DELIVERY_FAILED
        ]
        if delivered and now - delivered[-1].created_at < cooldown:
            raise OTPCooldown(_seconds(delivered[-1].created_at + cooldown - now))
        OTPChallenge.objects.filter(
            phone_number=phone_number, purpose=purpose, closed_at__isnull=True
        ).update(closed_at=now, closed_reason=OTPCloseReason.SUPERSEDED)
        challenge = OTPChallenge.objects.create(
            phone_number=phone_number,
            purpose=purpose,
            code_hash=_hash_code(purpose, phone_number, code),
            expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS),
        )
    try:
        get_sms_backend().send(phone_number, f"Your verification code is {code}")
    except Exception:
        # Keep the record for troubleshooting, but make the code unusable.
        OTPChallenge.objects.filter(pk=challenge.pk, closed_at__isnull=True).update(
            closed_at=timezone.now(), closed_reason=OTPCloseReason.DELIVERY_FAILED
        )
        raise


def verify_otp(raw_phone_number: str, code: str, *, purpose: str) -> str:
    """Consume a valid code and return the verified E.164 phone number."""
    try:
        phone_number = normalize_phone_number(raw_phone_number)
    except ValidationError:
        raise InvalidOTP from None
    now = timezone.now()
    valid = False
    # The failure is raised after the atomic block so that the attempt counter
    # is committed instead of being rolled back.
    with transaction.atomic():
        challenge = (
            OTPChallenge.objects.select_for_update()
            .filter(phone_number=phone_number, purpose=purpose, closed_at__isnull=True)
            .first()
        )
        if (
            challenge is None
            or challenge.expires_at <= now
            or challenge.attempts >= settings.OTP_MAX_ATTEMPTS
        ):
            pass
        elif not hmac.compare_digest(
            challenge.code_hash, _hash_code(purpose, phone_number, code)
        ):
            challenge.attempts += 1
            challenge.save(update_fields=["attempts"])
        else:
            challenge.closed_at = now
            challenge.closed_reason = OTPCloseReason.CONSUMED
            challenge.save(update_fields=["closed_at", "closed_reason"])
            valid = True
    if not valid:
        raise InvalidOTP
    return phone_number
