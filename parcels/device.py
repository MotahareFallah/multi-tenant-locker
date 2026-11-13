"""Which device the API talks to (ADR-0003).

`pickup_parcel` takes the device as an argument; views get theirs from here.
One instance is kept per configured backend so that every request in a process
talks to the same device. The simulator remembers command ids, which is what
stops a retried command from opening a door twice.
"""

import threading

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

_lock = threading.Lock()
_instances = {}


def get_device():
    path = getattr(settings, "DEVICE_BACKEND", "")
    if not path:
        raise ImproperlyConfigured("DEVICE_BACKEND is not set.")
    with _lock:
        device = _instances.get(path)
        if device is None:
            try:
                factory = import_string(path)
            except ImportError as exc:
                raise ImproperlyConfigured(
                    f"DEVICE_BACKEND {path!r} cannot be imported."
                ) from exc
            device = _instances[path] = factory()
    return device


def reset_devices():
    """Forget every instance. For tests."""
    with _lock:
        _instances.clear()
