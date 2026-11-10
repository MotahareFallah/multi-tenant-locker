"""One-time pickup codes. Only an HMAC hash is stored, never the code itself."""

import hashlib
import hmac
import secrets

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

PICKUP_CODE_LENGTH = 6
_PURPOSE = "parcel-pickup"


def generate_pickup_code() -> str:
    return f"{secrets.randbelow(10**PICKUP_CODE_LENGTH):0{PICKUP_CODE_LENGTH}d}"


def hash_pickup_code(tracking_code: str, code: str) -> str:
    """Bind the hash to one parcel, so its code is useless for any other."""
    key = settings.OTP_HMAC_KEY
    if not key:
        raise ImproperlyConfigured("OTP_HMAC_KEY must be set.")
    return hmac.new(
        key.encode(),
        f"{_PURPOSE}:{tracking_code}:{code}".encode(),
        hashlib.sha256,
    ).hexdigest()


def pickup_code_matches(parcel, code) -> bool:
    if not parcel.pickup_code_hash or not isinstance(code, str):
        return False
    return hmac.compare_digest(
        parcel.pickup_code_hash, hash_pickup_code(parcel.tracking_code, code)
    )
