"""OTP challenges: proof that someone controls a phone number.

Verifying a code proves phone ownership only. It never creates users, roles or
organization memberships; those belong to the flows that call into this module.
"""

import hashlib
import hmac
import logging
import math
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import connection, transaction
from django.utils import timezone

from .models import OTPChallenge, OTPCloseReason, OTPPurpose
from .phone import normalize_phone_number
from .sms import get_sms_backend

logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class OTPPolicy:
    length: int
    ttl: timedelta
    max_attempts: int
    cooldown: timedelta
    max_requests: int
    window: timedelta


MIN_CODE_LENGTH = 6
MAX_CODE_LENGTH = 10


def _int_setting(name: str, minimum: int, maximum: int | None = None) -> int:
    value = getattr(settings, name, None)
    valid = (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= minimum
        and (maximum is None or value <= maximum)
    )
    if not valid:
        bounds = (
            f"at least {minimum}"
            if maximum is None
            else f"between {minimum} and {maximum}"
        )
        raise ImproperlyConfigured(f"{name} must be an integer {bounds}.")
    return value


def _settings_policy() -> OTPPolicy:
    """Build the default policy, rejecting invalid settings before any use."""
    return OTPPolicy(
        length=_int_setting("OTP_LENGTH", MIN_CODE_LENGTH, MAX_CODE_LENGTH),
        ttl=timedelta(seconds=_int_setting("OTP_TTL_SECONDS", 1)),
        max_attempts=_int_setting("OTP_MAX_ATTEMPTS", 1),
        cooldown=timedelta(seconds=_int_setting("OTP_RESEND_COOLDOWN_SECONDS", 1)),
        max_requests=_int_setting("OTP_MAX_REQUESTS_PER_WINDOW", 1),
        window=timedelta(seconds=_int_setting("OTP_RATE_WINDOW_SECONDS", 1)),
    )


# One entry per allowed purpose. Every flow gets its own limits here, and a
# purpose without a policy cannot be used.
POLICIES = {OTPPurpose.CUSTOMER_SIGN_IN: _settings_policy}


def _resolve(purpose: str) -> tuple[str, OTPPolicy]:
    factory = POLICIES.get(purpose)
    if factory is None:
        raise ValueError(f"Unknown OTP purpose: {purpose!r}")
    return str(purpose), factory()


def _generate_code(length: int) -> str:
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


def _is_well_formed(code: object, policy: OTPPolicy) -> bool:
    return (
        isinstance(code, str)
        and code.isascii()
        and code.isdigit()
        and len(code) == policy.length
    )


def _lock_requests(phone_number: str, purpose: str) -> None:
    """Serialize concurrent requests for one (phone, purpose) until commit.

    Row locks are not enough here: rows inserted by a concurrent request are
    invisible to a statement that is already waiting, so the cooldown and the
    window count would be stale. A transaction-level advisory lock exists even
    when there are no rows yet, and the queries that follow it see fresh data.
    This ties the service to PostgreSQL (see accounts.E006).
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"otp:{purpose}:{phone_number}"],
        )


def request_otp(raw_phone_number: str, *, purpose: OTPPurpose) -> None:
    """Create a fresh challenge for the number and send the code by SMS.

    Concurrent calls for the same (phone, purpose) run one after another: the
    first creates the challenge, the others are rejected by the cooldown.
    """
    purpose, policy = _resolve(purpose)
    phone_number = normalize_phone_number(raw_phone_number)
    code = _generate_code(policy.length)
    now = timezone.now()
    with transaction.atomic():
        _lock_requests(phone_number, purpose)
        recent = list(
            OTPChallenge.objects.filter(
                phone_number=phone_number,
                purpose=purpose,
                created_at__gte=now - policy.window,
            ).order_by("created_at")
        )
        if len(recent) >= policy.max_requests:
            raise OTPRateLimited(_seconds(recent[0].created_at + policy.window - now))
        # A failed delivery sent nothing, so it must not block a retry.
        delivered = [
            c for c in recent if c.closed_reason != OTPCloseReason.DELIVERY_FAILED
        ]
        if delivered and now - delivered[-1].created_at < policy.cooldown:
            raise OTPCooldown(
                _seconds(delivered[-1].created_at + policy.cooldown - now)
            )
        OTPChallenge.objects.filter(
            phone_number=phone_number, purpose=purpose, closed_at__isnull=True
        ).update(closed_at=now, closed_reason=OTPCloseReason.SUPERSEDED)
        challenge = OTPChallenge.objects.create(
            phone_number=phone_number,
            purpose=purpose,
            code_hash=_hash_code(purpose, phone_number, code),
            expires_at=now + policy.ttl,
        )
    try:
        get_sms_backend().send(phone_number, f"Your verification code is {code}")
    except Exception:
        # Keep the record for troubleshooting, but make the code unusable.
        try:
            OTPChallenge.objects.filter(
                pk=challenge.pk, closed_at__isnull=True
            ).update(
                closed_at=timezone.now(),
                closed_reason=OTPCloseReason.DELIVERY_FAILED,
            )
        except Exception:
            # Never hide the delivery error. The code was not delivered and it
            # expires on its own. The OTP itself is never logged.
            logger.exception("Could not close OTP challenge %s", challenge.pk)
        raise


def verify_otp(raw_phone_number: str, code: str, *, purpose: OTPPurpose) -> str:
    """Consume a valid code and return the verified E.164 phone number."""
    purpose, policy = _resolve(purpose)
    try:
        phone_number = normalize_phone_number(raw_phone_number)
    except ValidationError:
        raise InvalidOTP from None
    if not _is_well_formed(code, policy):
        # Malformed input is treated as a wrong guess, so it is counted like one
        # and can never be used to probe without using up attempts.
        code = ""
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
            or challenge.attempts >= policy.max_attempts
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
