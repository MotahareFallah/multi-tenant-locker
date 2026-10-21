from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Error, Tags, register
from django.db import connection
from django.utils.module_loading import import_string

CONSOLE_BACKEND = "accounts.sms.ConsoleSmsBackend"
HTTP_BACKEND = "accounts.sms.HttpSmsBackend"
MIN_HMAC_KEY_LENGTH = 32
MIN_HMAC_KEY_DISTINCT_CHARS = 8
POSITIVE_INT_SETTINGS = (
    "OTP_TTL_SECONDS",
    "OTP_MAX_ATTEMPTS",
    "OTP_RESEND_COOLDOWN_SECONDS",
    "OTP_MAX_REQUESTS_PER_WINDOW",
    "OTP_RATE_WINDOW_SECONDS",
)


def _setting(name, default=""):
    return getattr(settings, name, default)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_https_url(url):
    try:
        parsed = urlparse(url)
        return parsed.scheme == "https" and bool(parsed.hostname)
    except ValueError:
        return False


@register()
def database_is_postgresql(app_configs, **kwargs):
    if connection.vendor != "postgresql":
        return [
            Error(
                "OTP request serialization uses PostgreSQL advisory locks.",
                hint="Use PostgreSQL as the database.",
                id="accounts.E006",
            )
        ]
    return []


@register()
def otp_settings_are_valid(app_configs, **kwargs):
    errors = []
    length = _setting("OTP_LENGTH", None)
    if not _is_int(length) or not 6 <= length <= 10:
        errors.append(
            Error("OTP_LENGTH must be an integer between 6 and 10.", id="accounts.E007")
        )
    for name in POSITIVE_INT_SETTINGS:
        value = _setting(name, None)
        if not _is_int(value) or value <= 0:
            errors.append(
                Error(f"{name} must be a positive integer.", id="accounts.E007")
            )
    return errors


@register()
def sms_backend_is_importable(app_configs, **kwargs):
    path = _setting("SMS_BACKEND")
    if not path:
        return [Error("SMS_BACKEND is not set.", id="accounts.E008")]
    try:
        import_string(path)
    except ImportError:
        return [Error(f"SMS_BACKEND {path!r} cannot be imported.", id="accounts.E008")]
    return []


@register(Tags.security, deploy=True)
def sms_backend_is_not_console(app_configs, **kwargs):
    if _setting("SMS_BACKEND") == CONSOLE_BACKEND:
        return [
            Error(
                "SMS_BACKEND is the console backend; OTP codes would be logged.",
                hint=f"Set SMS_BACKEND to a real backend, e.g. {HTTP_BACKEND}.",
                id="accounts.E001",
            )
        ]
    return []


@register(Tags.security, deploy=True)
def otp_hmac_key_is_strong(app_configs, **kwargs):
    key = _setting("OTP_HMAC_KEY")
    if not key or key == _setting("SECRET_KEY"):
        return [
            Error(
                "OTP_HMAC_KEY must be set and different from SECRET_KEY.",
                id="accounts.E002",
            )
        ]
    # A heuristic: it rejects obviously weak keys but cannot prove entropy.
    if len(key) < MIN_HMAC_KEY_LENGTH or len(set(key)) < MIN_HMAC_KEY_DISTINCT_CHARS:
        return [
            Error(
                "OTP_HMAC_KEY is too weak.",
                hint="Generate one with: "
                'python -c "import secrets; print(secrets.token_hex(32))"',
                id="accounts.E005",
            )
        ]
    return []


@register(Tags.security, deploy=True)
def sms_http_backend_is_configured(app_configs, **kwargs):
    if _setting("SMS_BACKEND") != HTTP_BACKEND:
        return []
    url = _setting("SMS_API_URL")
    if not url or not _setting("SMS_API_KEY"):
        return [
            Error(
                "HttpSmsBackend requires SMS_API_URL and SMS_API_KEY.",
                id="accounts.E003",
            )
        ]
    if not _is_https_url(url):
        return [Error("SMS_API_URL must be an https URL with a host.", id="accounts.E004")]
    return []
