import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.core.cache import cache
from django.db import connections

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


@pytest.fixture(autouse=True)
def otp_hmac_key(settings):
    settings.OTP_HMAC_KEY = "test-only-otp-key"


@pytest.fixture
def fixed_codes(monkeypatch):
    codes = iter(["111111", "222222", "333333"])
    monkeypatch.setattr(otp, "_generate_code", lambda length: next(codes))


@pytest.fixture
def other_purpose(monkeypatch):
    """A second, test-only purpose that shares the default policy."""
    monkeypatch.setitem(otp.POLICIES, "other_purpose", otp._settings_policy)
    return "other_purpose"


@pytest.fixture
def run_concurrently():
    """Release `count` threads together; return a (result, error) pair per thread."""

    def run(func, count):
        barrier = threading.Barrier(count)

        def worker():
            try:
                barrier.wait(timeout=10)
                try:
                    return func(), None
                except Exception as exc:
                    return None, exc
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=count) as pool:
            futures = [pool.submit(worker) for _ in range(count)]
            return [future.result() for future in futures]

    return run


@pytest.fixture(autouse=True)
def local_memory_cache(settings):
    """Keep throttle counters out of Redis and isolated between tests."""
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "tests",
        }
    }
    cache.clear()
