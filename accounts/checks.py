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
