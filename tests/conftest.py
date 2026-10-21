import pytest

from accounts.sms import InMemorySmsBackend


@pytest.fixture(autouse=True)
def sms_outbox(settings):
    settings.SMS_BACKEND = "accounts.sms.InMemorySmsBackend"
    InMemorySmsBackend.outbox.clear()
    return InMemorySmsBackend.outbox
