"""Request validation for the OTP endpoints.

Shape problems (not a string, wrong characters, absurd length) are rejected here
with field errors. Whether a well-formed code is *correct* is decided by the
service, which answers with one generic error.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .otp import MAX_CODE_LENGTH, MIN_CODE_LENGTH
from .phone import normalize_phone_number

MAX_INPUT_LENGTH = 64

# Persian (U+06F0..) and Arabic-Indic (U+0660..) digits map to ASCII digits.
_DIGITS = {
    **{0x06F0 + i: ord("0") + i for i in range(10)},
    **{0x0660 + i: ord("0") + i for i in range(10)},
}


def normalize_digits(value: str) -> str:
    return value.translate(_DIGITS)


class StrictCharField(serializers.CharField):
    """A string field that never coerces numbers or booleans to text."""

    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", MAX_INPUT_LENGTH)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        if len(data) > self.max_length:
            self.fail("max_length", max_length=self.max_length)
        return super().to_internal_value(data)


class PhoneNumberField(StrictCharField):
    def to_internal_value(self, data):
        value = normalize_digits(super().to_internal_value(data))
        try:
            return normalize_phone_number(value)
        except DjangoValidationError:
            raise serializers.ValidationError(
                "Enter a valid mobile phone number."
            ) from None


class OTPCodeField(StrictCharField):
    def to_internal_value(self, data):
        value = normalize_digits(super().to_internal_value(data))
        well_formed = (
            value.isascii()
            and value.isdigit()
            and MIN_CODE_LENGTH <= len(value) <= MAX_CODE_LENGTH
        )
        if not well_formed:
            raise serializers.ValidationError("Enter the numeric code you received.")
        return value


class OTPRequestSerializer(serializers.Serializer):
    phone_number = PhoneNumberField()


class OTPVerifySerializer(serializers.Serializer):
    phone_number = PhoneNumberField()
    code = OTPCodeField()
