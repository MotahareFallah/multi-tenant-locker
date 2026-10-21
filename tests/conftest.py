import pytest

from accounts import otp
from accounts.sms import SmsBackend


class InMemorySmsBackend(SmsBackend):
    def __init__(self):
        self.outbox: list[tuple[str, str]] = []

    def send(self, phone_number: str, message: str) -> None:
        self.outbox.append((phone_number, message))


@pytest.fixture(autouse=True)
def sms_outbox(monkeypatch):
    backend = InMemorySmsBackend()
    monkeypatch.setattr(otp, "get_sms_backend", lambda: backend)
    return backend.outbox
