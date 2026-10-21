"""Customer sign-in. A verified phone number identifies a customer only.

It grants no organization permissions. Owner and staff onboarding are separate
flows with their own OTP purposes and rules.
"""

from django.db import IntegrityError, transaction

from . import otp
from .models import OTPPurpose, User


def request_customer_code(raw_phone_number: str) -> None:
    otp.request_otp(raw_phone_number, purpose=OTPPurpose.CUSTOMER_SIGN_IN)


def sign_in_customer(raw_phone_number: str, code: str) -> User:
    phone_number = otp.verify_otp(
        raw_phone_number, code, purpose=OTPPurpose.CUSTOMER_SIGN_IN
    )
    user = User.objects.filter(phone_number=phone_number).first()
    if user is None:
        try:
            with transaction.atomic():
                user = User.objects.create_user(phone_number=phone_number)
        except IntegrityError:
            user = User.objects.get(phone_number=phone_number)
    if not user.is_active:
        raise otp.InvalidOTP
    return user
