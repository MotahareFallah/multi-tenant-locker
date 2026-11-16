import pytest
from django.core.checks.registry import registry

from parcels.checks import (
    device_backend_is_importable,
    device_backend_is_not_the_simulator,
)


def ids(messages):
    return [message.id for message in messages]


def test_the_default_backend_is_importable():
    assert device_backend_is_importable(None) == []


@pytest.mark.parametrize("value", ["", "no.such.Backend", "nodots"])
def test_a_missing_or_unimportable_backend_is_an_error(settings, value):
    settings.DEVICE_BACKEND = value
    assert ids(device_backend_is_importable(None)) == ["parcels.E001"]


def test_an_unset_backend_is_an_error(settings):
    del settings.DEVICE_BACKEND
    assert ids(device_backend_is_importable(None)) == ["parcels.E001"]


def test_the_simulator_is_refused_on_deploy():
    assert ids(device_backend_is_not_the_simulator(None)) == ["parcels.E002"]


def test_another_backend_is_accepted_on_deploy(settings):
    settings.DEVICE_BACKEND = "types.SimpleNamespace"
    assert device_backend_is_not_the_simulator(None) == []


def test_the_simulator_check_runs_only_on_deploy():
    development = registry.get_checks(include_deployment_checks=False)
    deployment = registry.get_checks(include_deployment_checks=True)
    assert device_backend_is_not_the_simulator not in development
    assert device_backend_is_not_the_simulator in deployment
    assert device_backend_is_importable in development
