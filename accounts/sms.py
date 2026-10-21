from django.conf import settings
from django.utils.module_loading import import_string


class SmsBackend:
    def send(self, phone_number: str, message: str) -> None:
        raise NotImplementedError


class ConsoleSmsBackend(SmsBackend):
    """Development backend: prints the message instead of sending it."""

    def send(self, phone_number: str, message: str) -> None:
        print(f"[SMS to {phone_number}] {message}")


class InMemorySmsBackend(SmsBackend):
    """Test backend: collects messages in a list."""

    outbox: list[tuple[str, str]] = []

    def send(self, phone_number: str, message: str) -> None:
        self.outbox.append((phone_number, message))


def get_sms_backend() -> SmsBackend:
    return import_string(settings.SMS_BACKEND)()
