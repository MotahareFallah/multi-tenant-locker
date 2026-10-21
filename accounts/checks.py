from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def sms_backend_is_not_console(app_configs, **kwargs):
    if settings.SMS_BACKEND == "accounts.sms.ConsoleSmsBackend":
        return [
            Error(
                "SMS_BACKEND is the console backend; OTP codes would be logged.",
                hint="Set SMS_BACKEND to a real backend, e.g. "
                "accounts.sms.HttpSmsBackend.",
                id="accounts.E001",
            )
        ]
    return []


@register(Tags.security, deploy=True)
def otp_hmac_key_is_separate(app_configs, **kwargs):
    key = settings.OTP_HMAC_KEY
    if not key or key == settings.SECRET_KEY:
        return [
            Error(
                "OTP_HMAC_KEY must be set and different from SECRET_KEY.",
                id="accounts.E002",
            )
        ]
    return []


@register(Tags.security, deploy=True)
def sms_http_backend_is_configured(app_configs, **kwargs):
    if settings.SMS_BACKEND != "accounts.sms.HttpSmsBackend":
        return []
    if not settings.SMS_API_URL or not settings.SMS_API_KEY:
        return [
            Error(
                "HttpSmsBackend requires SMS_API_URL and SMS_API_KEY.",
                id="accounts.E003",
            )
        ]
    if not settings.SMS_API_URL.startswith("https://"):
        return [Error("SMS_API_URL must use https.", id="accounts.E004")]
    return []
