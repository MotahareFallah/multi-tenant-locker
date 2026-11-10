import threading

import pytest

from devices.base import DeviceError, DeviceFault, DeviceTimeout
from devices.simulator import Fault, SimulatedDevice


def open_door(device, command_id="cmd-1", locker="one", number=1):
    return device.open_door(
        locker_code=locker, compartment_number=number, command_id=command_id
    )


def test_a_door_opens_and_the_result_names_the_command():
    device = SimulatedDevice()
    result = open_door(device, "cmd-1", "one", 4)
    assert (result.command_id, result.locker_code, result.compartment_number) == (
        "cmd-1",
        "one",
        4,
    )
    assert device.opened == [("one", 4, "cmd-1")]


def test_the_same_command_never_opens_the_door_twice():
    device = SimulatedDevice()
    first = open_door(device, "cmd-1")
    second = open_door(device, "cmd-1")
    assert first == second
    assert len(device.opened) == 1
    assert device.calls == 2


def test_different_commands_each_open_a_door():
    device = SimulatedDevice()
    open_door(device, "cmd-1", number=1)
    open_door(device, "cmd-2", number=2)
    assert len(device.opened) == 2


def test_an_error_keeps_the_door_closed_and_applies_once():
    device = SimulatedDevice()
    device.inject(Fault.ERROR)
    with pytest.raises(DeviceFault):
        open_door(device, "cmd-1")
    assert device.opened == []
    # The fault was used up, so the same command can be sent again and succeeds.
    open_door(device, "cmd-1")
    assert len(device.opened) == 1


def test_a_timeout_can_leave_the_door_closed():
    device = SimulatedDevice()
    device.inject(Fault.TIMEOUT)
    with pytest.raises(DeviceTimeout):
        open_door(device, "cmd-1")
    assert device.opened == []


def test_a_timeout_can_hide_that_the_door_did_open():
    device = SimulatedDevice()
    device.inject(Fault.TIMEOUT, opened=True)
    with pytest.raises(DeviceTimeout):
        open_door(device, "cmd-1")
    assert len(device.opened) == 1
    # Asking again with the same command reveals what happened, without a second opening.
    result = open_door(device, "cmd-1")
    assert result.command_id == "cmd-1"
    assert len(device.opened) == 1


def test_a_slow_device_answers_after_the_delay():
    slept = []
    device = SimulatedDevice(sleep=slept.append)
    device.inject(Fault.SLOW, delay=2.5)
    result = open_door(device, "cmd-1")
    assert result.command_id == "cmd-1"
    assert slept == [2.5]
    assert len(device.opened) == 1


def test_faults_apply_in_the_order_they_were_injected():
    device = SimulatedDevice()
    device.inject(Fault.ERROR)
    device.inject(Fault.TIMEOUT)
    with pytest.raises(DeviceFault):
        open_door(device, "cmd-1")
    with pytest.raises(DeviceTimeout):
        open_door(device, "cmd-2")
    open_door(device, "cmd-3")
    assert [command for _, _, command in device.opened] == ["cmd-3"]


def test_both_failures_are_device_errors():
    assert issubclass(DeviceFault, DeviceError)
    assert issubclass(DeviceTimeout, DeviceError)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fault": Fault.SLOW, "delay": -1},
        {"fault": Fault.ERROR, "opened": True},
        {"fault": Fault.SLOW, "opened": True},
    ],
)
def test_nonsense_faults_are_rejected(kwargs):
    with pytest.raises(ValueError):
        SimulatedDevice().inject(**kwargs)


def test_concurrent_copies_of_one_command_open_the_door_once():
    device = SimulatedDevice()
    start = threading.Barrier(20)
    results = []

    def send():
        start.wait()
        results.append(open_door(device, "cmd-1"))

    threads = [threading.Thread(target=send) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 20
    assert len(set(results)) == 1
    assert len(device.opened) == 1
