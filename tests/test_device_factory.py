from concurrent.futures import ThreadPoolExecutor

import pytest
from django.core.exceptions import ImproperlyConfigured

from devices.simulator import SimulatedDevice
from parcels.device import get_device, reset_devices


@pytest.fixture(autouse=True)
def fresh_devices():
    reset_devices()
    yield
    reset_devices()


def test_the_default_backend_is_the_simulator():
    assert isinstance(get_device(), SimulatedDevice)


def test_every_call_returns_the_same_device():
    assert get_device() is get_device()


def test_reset_gives_a_new_device():
    first = get_device()
    reset_devices()
    assert get_device() is not first


def test_each_backend_path_has_its_own_device(settings):
    simulator = get_device()
    settings.DEVICE_BACKEND = "types.SimpleNamespace"
    other = get_device()
    assert other is not simulator
    settings.DEVICE_BACKEND = "devices.simulator.SimulatedDevice"
    assert get_device() is simulator


def test_concurrent_first_calls_share_one_device():
    with ThreadPoolExecutor(max_workers=8) as pool:
        devices = list(pool.map(lambda _: get_device(), range(32)))
    assert all(device is devices[0] for device in devices)


@pytest.mark.parametrize("value", ["", "no.such.Backend", "nodots"])
def test_a_missing_or_unimportable_backend_is_a_configuration_error(settings, value):
    settings.DEVICE_BACKEND = value
    with pytest.raises(ImproperlyConfigured):
        get_device()


def test_an_unset_backend_is_a_configuration_error(settings):
    del settings.DEVICE_BACKEND
    with pytest.raises(ImproperlyConfigured):
        get_device()
