import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

REFRESH_URL = "/api/v1/auth/token/refresh/"
BLACKLIST_URL = "/api/v1/auth/token/blacklist/"

pytestmark = pytest.mark.django_db


@pytest.fixture
def refresh_token():
    user = get_user_model().objects.create(phone_number="+989123456789")
    return str(RefreshToken.for_user(user))


@pytest.fixture
def rates(monkeypatch):
    def set_rate(scope, rate):
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, scope, rate)

    return set_rate


def post(url, token):
    return APIClient().post(url, {"refresh": token}, format="json")


def test_blacklisting_revokes_the_refresh_token(refresh_token):
    assert post(BLACKLIST_URL, refresh_token).status_code == 200
    assert post(REFRESH_URL, refresh_token).status_code == 401


def test_blacklisting_an_invalid_token_is_rejected():
    assert post(BLACKLIST_URL, "not-a-token").status_code == 401


def test_refresh_is_throttled_per_ip(rates):
    rates("token", "2/hour")
    statuses = [post(REFRESH_URL, "not-a-token").status_code for _ in range(3)]
    assert statuses == [401, 401, 429]


def test_blacklist_is_throttled_per_ip(rates):
    rates("token", "2/hour")
    statuses = [post(BLACKLIST_URL, "not-a-token").status_code for _ in range(3)]
    assert statuses == [401, 401, 429]
