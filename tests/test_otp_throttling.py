import uuid

import pytest
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from accounts.throttling import OTPRequestThrottle

REQUEST_URL = "/api/v1/auth/otp/request/"
VERIFY_URL = "/api/v1/auth/otp/verify/"

pytestmark = pytest.mark.django_db


class BrokenCache:
    def get(self, *args, **kwargs):
        raise ConnectionError("redis down")


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def rates(monkeypatch):
    """Override a throttle rate (DRF reads the rates once, at import time)."""

    def set_rate(scope, rate):
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, scope, rate)

    return set_rate


def phone(i):
    return f"091212{i:05d}"


def post_request(client, number, **extra):
    return client.post(REQUEST_URL, {"phone_number": number}, format="json", **extra)


def test_request_endpoint_is_throttled_per_ip(api_client, rates, sms_outbox):
    rates("otp_request", "3/hour")
    responses = [post_request(api_client, phone(i)) for i in range(4)]
    assert [r.status_code for r in responses] == [202, 202, 202, 429]
    assert int(responses[3]["Retry-After"]) > 0
    assert len(sms_outbox) == 3


def test_malformed_requests_count_against_the_limit(api_client, rates):
    rates("otp_request", "3/hour")
    for _ in range(3):
        assert post_request(api_client, "12345").status_code == 400
    assert post_request(api_client, phone(1)).status_code == 429


def test_verify_endpoint_is_throttled_per_ip(api_client, rates):
    rates("otp_verify", "2/hour")
    body = {"phone_number": "09123456789", "code": "111111"}
    statuses = [
        api_client.post(VERIFY_URL, body, format="json").status_code for _ in range(3)
    ]
    assert statuses == [400, 400, 429]


def test_each_ip_has_its_own_budget(api_client, rates):
    rates("otp_request", "2/hour")
    for i in range(2):
        response = post_request(api_client, phone(i), REMOTE_ADDR="10.0.0.1")
        assert response.status_code == 202
    assert post_request(api_client, phone(2), REMOTE_ADDR="10.0.0.1").status_code == 429
    assert post_request(api_client, phone(3), REMOTE_ADDR="10.0.0.2").status_code == 202


def test_a_forged_forwarded_for_header_cannot_dodge_the_limit(api_client, rates):
    rates("otp_request", "2/hour")
    statuses = [
        post_request(
            api_client, phone(i), HTTP_X_FORWARDED_FOR=f"203.0.113.{i}"
        ).status_code
        for i in range(3)
    ]
    assert statuses == [202, 202, 429]


def test_behind_a_trusted_proxy_the_proxy_appended_client_is_used(
    api_client, rates, settings
):
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
    rates("otp_request", "2/hour")

    def call(i, forwarded_for):
        response = post_request(api_client, phone(i), HTTP_X_FORWARDED_FOR=forwarded_for)
        return response.status_code

    assert call(0, "9.9.9.9, 1.1.1.1") == 202
    assert call(1, "8.8.8.8, 1.1.1.1") == 202  # the spoofable part is ignored
    assert call(2, "7.7.7.7, 1.1.1.1") == 429
    assert call(3, "7.7.7.7, 2.2.2.2") == 202  # a different real client


def test_a_cache_failure_fails_open_but_database_limits_still_apply(
    api_client, monkeypatch, caplog
):
    monkeypatch.setattr(OTPRequestThrottle, "cache", BrokenCache())
    first = post_request(api_client, "09123456789")
    second = post_request(api_client, "09123456789")
    assert first.status_code == 202
    assert second.status_code == 429  # the per-phone cooldown, kept in the database
    assert "IP throttle backend failed" in caplog.text


@pytest.mark.redis
def test_throttling_works_with_the_real_redis_cache(api_client, rates, settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": settings.REDIS_URL,
            "KEY_PREFIX": f"test-{uuid.uuid4().hex}",
        }
    }
    rates("otp_request", "2/hour")
    statuses = [post_request(api_client, phone(i)).status_code for i in range(3)]
    assert statuses == [202, 202, 429]
