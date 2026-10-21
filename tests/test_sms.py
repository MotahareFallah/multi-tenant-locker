import logging

import pytest
import requests
from django.core.exceptions import ImproperlyConfigured

from accounts.checks import sms_backend_is_not_console
from accounts.sms import (
    ConsoleSmsBackend,
    HttpSmsBackend,
    SmsBackend,
    SmsDeliveryError,
)


@pytest.fixture
def http_settings(settings):
    settings.SMS_API_URL = "https://sms.example.test/send"
    settings.SMS_API_KEY = "secret-key"
    settings.SMS_SENDER = "LOCKER"
    settings.SMS_TIMEOUT = 3.0
    return settings


def test_abstract_backend_cannot_be_instantiated():
    with pytest.raises(TypeError):
        SmsBackend()


def test_http_backend_requires_url_and_key(settings):
    settings.SMS_API_URL = ""
    settings.SMS_API_KEY = ""
    with pytest.raises(ImproperlyConfigured):
        HttpSmsBackend()


def test_http_backend_posts_with_timeout_and_auth(http_settings, monkeypatch):
    calls = {}

    class Response:
        def raise_for_status(self):
            pass

    def fake_post(url, json, headers, timeout):
        calls.update(url=url, json=json, headers=headers, timeout=timeout)
        return Response()

    monkeypatch.setattr(requests, "post", fake_post)
    HttpSmsBackend().send("+989123456789", "hello")
    assert calls["url"] == "https://sms.example.test/send"
    assert calls["json"] == {
        "to": "+989123456789",
        "message": "hello",
        "from": "LOCKER",
    }
    assert calls["headers"] == {"Authorization": "Bearer secret-key"}
    assert calls["timeout"] == 3.0


def test_http_backend_wraps_provider_errors_without_logging_the_message(
    http_settings, monkeypatch, caplog
):
    def failing_post(*args, **kwargs):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(requests, "post", failing_post)
    with caplog.at_level(logging.ERROR), pytest.raises(SmsDeliveryError):
        HttpSmsBackend().send("+989123456789", "code 555777")
    assert "555777" not in caplog.text


def test_console_backend_logs_instead_of_printing(caplog, capsys):
    with caplog.at_level(logging.WARNING):
        ConsoleSmsBackend().send("+989123456789", "hi")
    assert "hi" in caplog.text
    assert capsys.readouterr().out == ""


def test_deploy_check_rejects_the_console_backend(settings):
    settings.SMS_BACKEND = "accounts.sms.ConsoleSmsBackend"
    errors = sms_backend_is_not_console(None)
    assert [e.id for e in errors] == ["accounts.E001"]


def test_deploy_check_accepts_a_real_backend(settings):
    settings.SMS_BACKEND = "accounts.sms.HttpSmsBackend"
    assert sms_backend_is_not_console(None) == []
