import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

ORIGIN = "http://127.0.0.1:8080"
OTHER = "http://other.example"
API = "/api/v1/auth/otp/request/"


@pytest.fixture(autouse=True)
def portal_origin(settings):
    settings.CORS_ALLOWED_ORIGINS = [ORIGIN]


def preflight(origin, path=API):
    return APIClient().options(
        path,
        HTTP_ORIGIN=origin,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type, idempotency-key, authorization",
    )


def allowed_headers(response):
    return {h.strip() for h in response["Access-Control-Allow-Headers"].split(",")}


def test_a_configured_origin_passes_the_preflight():
    response = preflight(ORIGIN)
    assert response.status_code == 200
    assert response["Access-Control-Allow-Origin"] == ORIGIN
    assert {"authorization", "content-type", "idempotency-key"} <= allowed_headers(
        response
    )


def test_credentials_are_not_allowed():
    assert "Access-Control-Allow-Credentials" not in preflight(ORIGIN).headers


def test_another_origin_gets_no_cors_headers():
    assert "Access-Control-Allow-Origin" not in preflight(OTHER).headers


def test_without_configured_origins_nothing_is_allowed(settings):
    settings.CORS_ALLOWED_ORIGINS = []
    assert "Access-Control-Allow-Origin" not in preflight(ORIGIN).headers


def test_only_the_api_is_open_to_other_origins():
    assert "Access-Control-Allow-Origin" not in preflight(ORIGIN, "/admin/login/").headers


def test_a_real_request_carries_the_origin_and_exposes_the_replay_header():
    response = APIClient().get("/api/v1/orgs/acme/my/parcels/", HTTP_ORIGIN=ORIGIN)
    assert response.status_code == 401
    assert response["Access-Control-Allow-Origin"] == ORIGIN
    assert "Idempotent-Replayed" in response["Access-Control-Expose-Headers"]
