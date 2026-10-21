from accounts.checks import otp_hmac_key_is_separate, sms_http_backend_is_configured

HTTP_BACKEND = "accounts.sms.HttpSmsBackend"


def ids(errors):
    return [error.id for error in errors]


def test_otp_key_check_rejects_an_empty_key(settings):
    settings.OTP_HMAC_KEY = ""
    assert ids(otp_hmac_key_is_separate(None)) == ["accounts.E002"]


def test_otp_key_check_rejects_reuse_of_the_secret_key(settings):
    settings.OTP_HMAC_KEY = settings.SECRET_KEY
    assert ids(otp_hmac_key_is_separate(None)) == ["accounts.E002"]


def test_otp_key_check_accepts_a_separate_key(settings):
    settings.OTP_HMAC_KEY = "a-different-key"
    assert otp_hmac_key_is_separate(None) == []


def test_http_backend_check_requires_url_and_key(settings):
    settings.SMS_BACKEND = HTTP_BACKEND
    settings.SMS_API_URL = ""
    settings.SMS_API_KEY = ""
    assert ids(sms_http_backend_is_configured(None)) == ["accounts.E003"]


def test_http_backend_check_requires_https(settings):
    settings.SMS_BACKEND = HTTP_BACKEND
    settings.SMS_API_URL = "http://sms.example.test/send"
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
