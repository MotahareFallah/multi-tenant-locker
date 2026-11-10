"""An in-memory locker that can be told to misbehave, for tests and local runs."""

import enum
import threading
import time
from collections import deque
from dataclasses import dataclass

from devices.base import DeviceFault, DeviceTimeout, DoorOpenResult


class Fault(enum.Enum):
    ERROR = "error"  # the device answers with a failure; the door stays closed
    TIMEOUT = "timeout"  # no answer; the door may have opened (see `opened`)
    SLOW = "slow"  # the door opens, but only after a delay


@dataclass(frozen=True)
class _Planned:
    fault: Fault
    opened: bool
    delay: float


class SimulatedDevice:
    def __init__(self, *, sleep=time.sleep):
        self._sleep = sleep
        self._lock = threading.Lock()
        self._plan = deque()
        self._results = {}
        self.calls = 0
        # Every physical opening: (locker_code, compartment_number, command_id).
        self.opened = []

    def inject(self, fault, *, opened=False, delay=0.0):
        """Queue a fault for an upcoming command. Faults apply once, in order."""
        if delay < 0:
            raise ValueError("delay cannot be negative")
        if opened and fault is not Fault.TIMEOUT:
            raise ValueError("`opened` only applies to Fault.TIMEOUT")
        with self._lock:
            self._plan.append(_Planned(fault, opened, delay))

    def open_door(self, *, locker_code, compartment_number, command_id):
        with self._lock:
            self.calls += 1
            known = self._results.get(command_id)
            if known is not None:
                return known  # same command again: the door is not opened twice

            planned = self._plan.popleft() if self._plan else None
            if planned is not None and planned.fault is Fault.ERROR:
                raise DeviceFault(f"{locker_code}/{compartment_number} reported an error")
            if (
                planned is not None
                and planned.fault is Fault.TIMEOUT
                and not planned.opened
            ):
                raise DeviceTimeout(f"{locker_code}/{compartment_number} did not answer")

            result = DoorOpenResult(command_id, locker_code, compartment_number)
            self._results[command_id] = result
            self.opened.append((locker_code, compartment_number, command_id))
            if planned is not None and planned.fault is Fault.TIMEOUT:
                # It opened, but we never hear back.
                raise DeviceTimeout(f"{locker_code}/{compartment_number} did not answer")

        if planned is not None and planned.fault is Fault.SLOW:
            self._sleep(planned.delay)
        return result
