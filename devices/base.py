"""The contract between the backend and a physical locker (ADR-0003).

Nothing here depends on Django: a real driver and the simulator implement the
same interface.
"""

from dataclasses import dataclass
from typing import Protocol


class DeviceError(Exception):
    """Base class for everything a device can do wrong."""


class DeviceFault(DeviceError):
    """The device reported a failure. The door did not open."""


class DeviceTimeout(DeviceError):
    """No answer in time. The door may or may not have opened."""


@dataclass(frozen=True)
class DoorOpenResult:
    command_id: str
    locker_code: str
    compartment_number: int


class DeviceClient(Protocol):
    def open_door(
        self, *, locker_code: str, compartment_number: int, command_id: str
    ) -> DoorOpenResult:
        """Open one door.

        Sending the same `command_id` again must not open the door a second
        time; the device answers with the result of the first command.
        """
        ...
