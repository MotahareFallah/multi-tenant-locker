from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.utils.module_loading import import_string
from rest_framework.throttling import SimpleRateThrottle

from . import otp
from .sms import SmsBackend

CONSOLE_BACKEND = "accounts.sms.ConsoleSmsBackend"
HTTP_BACKEND = "accounts.sms.HttpSmsBackend"
MIN_HMAC_KEY_LENGTH = 32
MIN_HMAC_KEY_DISTINCT_CHARS = 8


def _setting(name, default=""):
    return getattr(settings, name, default)


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
    # The service validates the same settings before every use (processes such
    # as gunicorn never run checks); this reports the problem early as well.
    try:
        for factory in otp.POLICIES.values():
            factory()
    except ImproperlyConfigured as exc:
        return [Error(str(exc), id="accounts.E007")]
    return []


@register()
def sms_backend_is_importable(app_configs, **kwargs):
    path = _setting("SMS_BACKEND")
    if not path:
        return [Error("SMS_BACKEND is not set.", id="accounts.E008")]
    try:
        backend = import_string(path)
    except Exception as exc:
        return [
            Error(
                f"SMS_BACKEND {path!r} cannot be imported ({type(exc).__name__}).",
                id="accounts.E008",
            )
        ]
    if not (isinstance(backend, type) and issubclass(backend, SmsBackend)):
        return [
            Error(
                f"SMS_BACKEND {path!r} must be a subclass of accounts.sms.SmsBackend.",
                id="accounts.E009",
            )
        ]
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
        return [
            Error("SMS_API_URL must be an https URL with a host.", id="accounts.E004")
        ]
    return []


THROTTLE_SCOPES = ("otp_request", "otp_verify")


def _rest_framework_settings():
    return getattr(settings, "REST_FRAMEWORK", {}) or {}


def _is_valid_rate(rate):
    if not isinstance(rate, str):
        return False
    try:
        num_requests, duration = SimpleRateThrottle.parse_rate(None, rate)
    except (ValueError, KeyError, IndexError, AttributeError):
        return False
    return num_requests > 0 and duration > 0


def _proxy_count():
    return _rest_framework_settings().get("NUM_PROXIES")


def _is_valid_proxy_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@register()
def throttle_rates_are_valid(app_configs, **kwargs):
    rates = _rest_framework_settings().get("DEFAULT_THROTTLE_RATES") or {}
    errors = []
    for scope in THROTTLE_SCOPES:
        if not _is_valid_rate(rates.get(scope)):
            errors.append(
                Error(
                    f"The IP throttle rate for '{scope}' is missing or invalid.",
                    hint=(
                        "Set REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']"
                        f"['{scope}'] to a positive rate such as '30/hour'."
                    ),
                    id="accounts.E010",
                )
            )
    return errors


@register()
def proxy_count_is_valid(app_configs, **kwargs):
    if _is_valid_proxy_count(_proxy_count()):
        return []
    return [
        Error(
            "REST_FRAMEWORK['NUM_PROXIES'] must be an integer >= 0.",
            hint=(
                "None makes DRF trust the whole X-Forwarded-For header, so a "
                "forged header could dodge IP throttling. Set TRUSTED_PROXY_COUNT."
            ),
            id="accounts.E011",
        )
    ]


@register(Tags.security, deploy=True)
def proxy_count_matches_deployment(app_configs, **kwargs):
    value = _proxy_count()
    if _is_valid_proxy_count(value) and value == 0:
        return [
            Warning(
                "NUM_PROXIES is 0: the client IP is the socket address and "
                "X-Forwarded-For is ignored.",
                hint=(
                    "Behind a reverse proxy or load balancer every user would "
                    "share one IP and one throttle bucket. Set TRUSTED_PROXY_COUNT "
                    "to the number of trusted proxies, or ignore this if there is none."
                ),
                id="accounts.W001",
            )
        ]
    return []
