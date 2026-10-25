import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

REFRESH_URL = "/api/v1/auth/token/refresh/"

pytestmark = pytest.mark.django_db


@pytest.fixture
def refresh_token():
    user = get_user_model().objects.create(phone_number="+989123456789")
    return str(RefreshToken.for_user(user))


def refresh(token):
    return APIClient().post(REFRESH_URL, {"refresh": token}, format="json")


def test_access_tokens_are_short_lived(refresh_token):
    response = refresh(refresh_token)
    assert response.status_code == 200
    access = AccessToken(response.data["access"])
    assert access["exp"] - access["iat"] == 15 * 60


def test_refresh_tokens_last_seven_days(refresh_token):
    token = RefreshToken(refresh_token)
    assert token["exp"] - token["iat"] == 7 * 24 * 3600


def test_refreshing_rotates_the_refresh_token(refresh_token):
    response = refresh(refresh_token)
    assert response.status_code == 200
    assert response.data["refresh"] != refresh_token


def test_a_used_refresh_token_cannot_be_used_again(refresh_token):
    assert refresh(refresh_token).status_code == 200
    assert refresh(refresh_token).status_code == 401


def test_the_rotated_refresh_token_keeps_working(refresh_token):
    new_token = refresh(refresh_token).data["refresh"]
    assert refresh(new_token).status_code == 200
