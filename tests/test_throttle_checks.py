import pytest

from accounts.checks import (
    proxy_count_is_valid,
    proxy_count_matches_deployment,
    throttle_rates_are_valid,
)


def ids(messages):
    return [message.id for message in messages]


def set_rest_framework(settings, **overrides):
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, **overrides}


def set_rate(settings, scope, rate):
    rates = {**settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], scope: rate}
    set_rest_framework(settings, DEFAULT_THROTTLE_RATES=rates)


def test_the_default_rates_are_valid():
    assert throttle_rates_are_valid(None) == []


@pytest.mark.parametrize("scope", ["otp_request", "otp_verify", "token"])
def test_a_missing_rate_is_an_error(settings, scope):
    rates = dict(settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"])
    del rates[scope]
    set_rest_framework(settings, DEFAULT_THROTTLE_RATES=rates)
    result = throttle_rates_are_valid(None)
    assert ids(result) == ["accounts.E010"]
    assert scope in result[0].msg


def test_missing_throttle_settings_are_reported_not_raised(settings):
    set_rest_framework(settings, DEFAULT_THROTTLE_RATES=None)
    assert ids(throttle_rates_are_valid(None)) == ["accounts.E010"] * 3


@pytest.mark.parametrize(
    "rate", ["abc", "3", "3/", "x/hour", "3/year", "0/hour", "-1/hour", None, 30]
)
def test_an_invalid_rate_is_an_error(settings, rate):
    set_rate(settings, "otp_request", rate)
    assert ids(throttle_rates_are_valid(None)) == ["accounts.E010"]


def test_the_default_proxy_count_is_valid():
    assert proxy_count_is_valid(None) == []


@pytest.mark.parametrize("value", [None, -1, True, "1"])
def test_an_invalid_proxy_count_is_an_error(settings, value):
    set_rest_framework(settings, NUM_PROXIES=value)
    assert ids(proxy_count_is_valid(None)) == ["accounts.E011"]


@pytest.mark.parametrize("value", [0, 1, 2])
def test_a_valid_proxy_count_is_accepted(settings, value):
    set_rest_framework(settings, NUM_PROXIES=value)
    assert proxy_count_is_valid(None) == []


def test_zero_proxies_warns_on_deploy(settings):
    set_rest_framework(settings, NUM_PROXIES=0)
    assert ids(proxy_count_matches_deployment(None)) == ["accounts.W001"]


def test_a_configured_proxy_count_does_not_warn(settings):
    set_rest_framework(settings, NUM_PROXIES=1)
    assert proxy_count_matches_deployment(None) == []


def test_an_invalid_proxy_count_is_left_to_the_error_check(settings):
    set_rest_framework(settings, NUM_PROXIES=None)
    assert proxy_count_matches_deployment(None) == []
