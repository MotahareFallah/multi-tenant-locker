import phonenumbers
from django.conf import settings
from django.core.exceptions import ValidationError

_MOBILE_TYPES = {
    phonenumbers.PhoneNumberType.MOBILE,
    phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE,
}


def normalize_phone_number(raw: str) -> str:
    """Return a mobile number in E.164 format or raise ValidationError."""
    error = ValidationError("Enter a valid mobile phone number.")
    try:
        parsed = phonenumbers.parse(raw, settings.PHONE_DEFAULT_REGION)
    except phonenumbers.NumberParseException as exc:
        raise error from exc
    if not phonenumbers.is_valid_number(parsed):
        raise error
    if phonenumbers.number_type(parsed) not in _MOBILE_TYPES:
        raise error
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
