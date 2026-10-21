import pytest
from django.db import connection

from accounts.checks import (
    database_is_postgresql,
    otp_hmac_key_is_strong,
    otp_settings_are_valid,
    sms_backend_is_importable,
    sms_http_backend_is_configured,
)

HTTP_BACKEND = "accounts.sms.HttpSmsBackend"


def ids(errors):
    return [error.id for error in errors]


def test_hmac_check_rejects_an_empty_key(settings):
    settings.OTP_HMAC_KEY = ""
    assert ids(otp_hmac_key_is_strong(None)) == ["accounts.E002"]


def test_hmac_check_rejects_reuse_of_the_secret_key(settings):
    settings.OTP_HMAC_KEY = settings.SECRET_KEY
    assert ids(otp_hmac_key_is_strong(None)) == ["accounts.E002"]


def test_hmac_check_rejects_a_short_key(settings):
    settings.OTP_HMAC_KEY = "abc123"
    assert ids(otp_hmac_key_is_strong(None)) == ["accounts.E005"]


def test_hmac_check_rejects_a_low_variety_key(settings):
    settings.OTP_HMAC_KEY = "a" * 40
    assert ids(otp_hmac_key_is_strong(None)) == ["accounts.E005"]


def test_hmac_check_accepts_a_strong_key(settings):
    settings.OTP_HMAC_KEY = "0123456789abcdef" * 4
    assert otp_hmac_key_is_strong(None) == []


def test_http_backend_check_requires_url_and_key(settings):
    settings.SMS_BACKEND = HTTP_BACKEND
    settings.SMS_API_URL = ""
    settings.SMS_API_KEY = ""
    assert ids(sms_http_backend_is_configured(None)) == ["accounts.E003"]


def test_http_backend_check_rejects_plain_http(settings):
    settings.SMS_BACKEND = HTTP_BACKEND
    settings.SMS_API_URL = "http://sms.example.test/send"
    settings.SMS_API_KEY = "key"
    assert ids(sms_http_backend_is_configured(None)) == ["accounts.E004"]


def test_http_backend_check_rejects_a_url_without_a_host(settings):
    settings.SMS_BACKEND = HTTP_BACKEND
    settings.SMS_API_URL = "https://"
    settings.SMS_API_KEY = "key"
    assert ids(sms_http_backend_is_configured(None)) == ["accounts.E004"]


def test_http_backend_check_accepts_a_complete_config(settings):
    settings.SMS_BACKEND = HTTP_BACKEND
    settings.SMS_API_URL = "https://sms.example.test/send"
    settings.SMS_API_KEY = "key"
    assert sms_http_backend_is_configured(None) == []


def test_http_backend_check_ignores_other_backends(settings):
    settings.SMS_BACKEND = "accounts.sms.ConsoleSmsBackend"
    settings.SMS_API_URL = ""
    assert sms_http_backend_is_configured(None) == []


def test_http_backend_check_survives_missing_settings(settings):
    settings.SMS_BACKEND = HTTP_BACKEND
    del settings.SMS_API_URL
    del settings.SMS_API_KEY
    assert ids(sms_http_backend_is_configured(None)) == ["accounts.E003"]


def test_otp_settings_check_accepts_the_defaults():
    assert otp_settings_are_valid(None) == []


def test_otp_settings_check_rejects_a_short_code_length(settings):
    settings.OTP_LENGTH = 4
    assert ids(otp_settings_are_valid(None)) == ["accounts.E007"]


def test_otp_settings_check_rejects_non_positive_limits(settings):
    settings.OTP_MAX_ATTEMPTS = 0
    assert ids(otp_settings_are_valid(None)) == ["accounts.E007"]


def test_otp_settings_check_survives_missing_settings(settings):
    del settings.OTP_TTL_SECONDS
    assert ids(otp_settings_are_valid(None)) == ["accounts.E007"]


def test_sms_backend_check_rejects_an_unimportable_backend(settings):
    settings.SMS_BACKEND = "accounts.sms.DoesNotExist"
    assert ids(sms_backend_is_importable(None)) == ["accounts.E008"]


def test_sms_backend_check_rejects_a_missing_setting(settings):
    del settings.SMS_BACKEND
    assert ids(sms_backend_is_importable(None)) == ["accounts.E008"]


def test_database_check_requires_postgresql(monkeypatch):
    monkeypatch.setattr(connection, "vendor", "sqlite")
    assert ids(database_is_postgresql(None)) == ["accounts.E006"]


def test_database_check_accepts_postgresql():
    assert database_is_postgresql(None) == []


def test_sms_backend_check_accepts_the_configured_backend():
    assert sms_backend_is_importable(None) == []


def test_sms_backend_check_rejects_a_class_that_is_not_a_backend(settings):
    settings.SMS_BACKEND = "builtins.dict"
    assert ids(sms_backend_is_importable(None)) == ["accounts.E009"]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("OTP_LENGTH", 5),
        ("OTP_LENGTH", 11),
        ("OTP_MAX_ATTEMPTS", 0),
        ("OTP_TTL_SECONDS", True),
        ("OTP_RATE_WINDOW_SECONDS", "3600"),
    ],
)
def test_otp_settings_check_rejects_invalid_values(settings, name, value):
    setattr(settings, name, value)
    assert ids(otp_settings_are_valid(None)) == ["accounts.E007"]
