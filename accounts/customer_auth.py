"""Customer sign-in. A verified phone number identifies a person only.

`User` is the shared identity for everyone (customers, owners, staff). Signing
in grants no organization permissions: those come exclusively from memberships.
Owner and staff onboarding are separate flows with their own OTP purposes.
"""

from django.db import IntegrityError, transaction

from . import otp
from .models import OTPPurpose, User

# PostgreSQL SQLSTATE for unique_violation. psycopg 3 exposes it as `.sqlstate`
# and the violated constraint as `.diag.constraint_name`.
UNIQUE_VIOLATION = "23505"
PHONE_UNIQUE_CONSTRAINT = "accounts_user_phone_number_key"


def request_customer_code(raw_phone_number: str) -> None:
    otp.request_otp(raw_phone_number, purpose=OTPPurpose.CUSTOMER_SIGN_IN)


def _is_duplicate_phone(exc: IntegrityError) -> bool:
    """True only for a unique violation on the phone number constraint."""
    cause = exc.__cause__
    diag = getattr(cause, "diag", None)
    return (
        getattr(cause, "sqlstate", None) == UNIQUE_VIOLATION
        and getattr(diag, "constraint_name", None) == PHONE_UNIQUE_CONSTRAINT
    )


def get_or_create_user(phone_number: str) -> User:
    """Return the user for a verified number, creating it when missing.

    Safe under concurrent creation. Only a duplicate-phone conflict is absorbed,
    and only if the user now exists; any other integrity error is re-raised
    instead of being hidden.
    """
    user = User.objects.filter(phone_number=phone_number).first()
    if user is not None:
        return user
    try:
        with transaction.atomic():
            return User.objects.create_user(phone_number=phone_number)
    except IntegrityError as exc:
        if not _is_duplicate_phone(exc):
            raise
        user = User.objects.filter(phone_number=phone_number).first()
        if user is None:
            raise
        return user


def sign_in_customer(raw_phone_number: str, code: str) -> User:
    phone_number = otp.verify_otp(
        raw_phone_number, code, purpose=OTPPurpose.CUSTOMER_SIGN_IN
    )
    user = get_or_create_user(phone_number)
    # Checked after the code is consumed on purpose: the caller gets the same
    # generic error as for a wrong code, so account state is not revealed, and
    # the code cannot be replayed.
    if not user.is_active:
        raise otp.InvalidOTP
    return user
