from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from accounts import otp
from accounts.models import OTPChallenge, OTPCloseReason, User
from accounts.sms import SmsDeliveryError

REQUEST_URL = "/api/v1/auth/otp/request/"
VERIFY_URL = "/api/v1/auth/otp/verify/"
REFRESH_URL = "/api/v1/auth/token/refresh/"
PHONE = "09123456789"
E164 = "+989123456789"

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    return APIClient()


def post(client, url, data, **extra):
    return client.post(url, data, format="json", **extra)


def persian(text):
    return "".join(chr(0x06F0 + int(d)) for d in text)


def sign_in(client):
    """Request a code (fixed to 111111) and verify it; return the verify response."""
    post(client, REQUEST_URL, {"phone_number": PHONE})
    return post(client, VERIFY_URL, {"phone_number": PHONE, "code": "111111"})


# --- request ---------------------------------------------------------------


def test_request_sends_a_code(api_client, fixed_codes, sms_outbox):
    response = post(api_client, REQUEST_URL, {"phone_number": PHONE})
    assert response.status_code == 202
    assert len(sms_outbox) == 1
    assert sms_outbox[0][0] == E164
    assert "111111" not in response.content.decode()


def test_request_accepts_persian_digits(api_client, sms_outbox):
    response = post(api_client, REQUEST_URL, {"phone_number": persian(PHONE)})
    assert response.status_code == 202
    assert sms_outbox[0][0] == E164


def test_request_rejects_an_invalid_phone_number(api_client, sms_outbox):
    response = post(api_client, REQUEST_URL, {"phone_number": "12345"})
    assert response.status_code == 400
    assert "phone_number" in response.json()
    assert sms_outbox == []


def test_request_ignores_a_bad_authorization_header(api_client):
    response = post(
        api_client,
        REQUEST_URL,
        {"phone_number": PHONE},
        HTTP_AUTHORIZATION="Bearer garbage",
    )
    assert response.status_code == 202


def test_request_during_the_cooldown_returns_429_with_retry_after(
    api_client, settings
):
    post(api_client, REQUEST_URL, {"phone_number": PHONE})
    response = post(api_client, REQUEST_URL, {"phone_number": PHONE})
    assert response.status_code == 429
    assert 0 < int(response["Retry-After"]) <= settings.OTP_RESEND_COOLDOWN_SECONDS


def test_request_over_the_hourly_cap_returns_429(api_client, settings):
    for _ in range(settings.OTP_MAX_REQUESTS_PER_WINDOW):
        post(api_client, REQUEST_URL, {"phone_number": PHONE})
        OTPChallenge.objects.update(created_at=timezone.now() - timedelta(minutes=10))
    response = post(api_client, REQUEST_URL, {"phone_number": PHONE})
    assert response.status_code == 429
    assert 0 < int(response["Retry-After"]) <= settings.OTP_RATE_WINDOW_SECONDS


def test_request_maps_an_sms_failure_to_503(api_client, monkeypatch):
    class FailingBackend:
        def send(self, phone_number, message):
            raise SmsDeliveryError("provider down")

    monkeypatch.setattr(otp, "get_sms_backend", lambda: FailingBackend())
    response = post(api_client, REQUEST_URL, {"phone_number": PHONE})
    assert response.status_code == 503
    assert "provider" not in response.content.decode()
    challenge = OTPChallenge.objects.get()
    assert challenge.closed_reason == OTPCloseReason.DELIVERY_FAILED


def test_request_rejects_get(api_client):
    assert api_client.get(REQUEST_URL).status_code == 405


# --- verify ----------------------------------------------------------------


def test_verify_returns_tokens_for_a_valid_code(api_client, fixed_codes):
    response = sign_in(api_client)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access", "refresh"}
    assert AccessToken(body["access"])["user_id"] == str(User.objects.get().id)


def test_verify_accepts_persian_digit_codes(api_client, fixed_codes):
    post(api_client, REQUEST_URL, {"phone_number": PHONE})
    response = post(
        api_client, VERIFY_URL, {"phone_number": PHONE, "code": persian("111111")}
    )
    assert response.status_code == 200


def test_verify_gives_the_same_answer_for_a_wrong_code_and_an_unknown_number(
    api_client, fixed_codes
):
    post(api_client, REQUEST_URL, {"phone_number": PHONE})
    wrong_code = post(api_client, VERIFY_URL, {"phone_number": PHONE, "code": "999999"})
    unknown_number = post(
        api_client, VERIFY_URL, {"phone_number": "09121234567", "code": "111111"}
    )
    assert wrong_code.status_code == unknown_number.status_code == 400
    assert wrong_code.json() == unknown_number.json()


def test_verify_rejects_a_malformed_code_with_a_field_error(api_client):
    response = post(api_client, VERIFY_URL, {"phone_number": PHONE, "code": "abc"})
    assert response.status_code == 400
    assert "code" in response.json()


def test_verify_gives_the_generic_error_for_an_inactive_user(api_client, fixed_codes):
    User.objects.create_user(phone_number=PHONE, is_active=False)
    post(api_client, REQUEST_URL, {"phone_number": PHONE})
    response = post(api_client, VERIFY_URL, {"phone_number": PHONE, "code": "111111"})
    wrong = post(api_client, VERIFY_URL, {"phone_number": PHONE, "code": "999999"})
    assert response.status_code == 400
    assert response.json() == wrong.json()


def test_verify_gives_the_generic_error_for_an_expired_code(api_client, fixed_codes):
    post(api_client, REQUEST_URL, {"phone_number": PHONE})
    OTPChallenge.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    response = post(api_client, VERIFY_URL, {"phone_number": PHONE, "code": "111111"})
    assert response.status_code == 400
    assert response.json()["detail"] == "The code is invalid or expired."


def test_verify_tokens_carry_identity_only(api_client, fixed_codes):
    access = sign_in(api_client).json()["access"]
    claims = set(AccessToken(access).payload)
    assert claims <= {"token_type", "exp", "iat", "jti", "user_id"}


def test_verify_ignores_a_bad_authorization_header(api_client, fixed_codes):
    post(api_client, REQUEST_URL, {"phone_number": PHONE})
    response = post(
        api_client,
        VERIFY_URL,
        {"phone_number": PHONE, "code": "111111"},
        HTTP_AUTHORIZATION="Bearer garbage",
    )
    assert response.status_code == 200


def test_refresh_exchanges_a_refresh_token_for_an_access_token(
    api_client, fixed_codes
):
    refresh = sign_in(api_client).json()["refresh"]
    response = post(api_client, REFRESH_URL, {"refresh": refresh})
    assert response.status_code == 200
    assert "access" in response.json()
