from django.conf import settings
from django.core.checks import Error, Tags, register
from django.utils.module_loading import import_string

SIMULATOR = "devices.simulator.SimulatedDevice"


@register()
def device_backend_is_importable(app_configs, **kwargs):
    path = getattr(settings, "DEVICE_BACKEND", "")
    if not path:
        return [Error("DEVICE_BACKEND is not set.", id="parcels.E001")]
    try:
        import_string(path)
    except Exception as exc:
        return [
            Error(
                f"DEVICE_BACKEND {path!r} cannot be imported ({type(exc).__name__}).",
                id="parcels.E001",
            )
        ]
    return []


@register(Tags.security, deploy=True)
def device_backend_is_not_the_simulator(app_configs, **kwargs):
    if getattr(settings, "DEVICE_BACKEND", "") == SIMULATOR:
        return [
            Error(
                "DEVICE_BACKEND is the simulator; no door would really open.",
                hint="Set DEVICE_BACKEND to a real driver (see docs/known-gaps.md).",
                id="parcels.E002",
            )
        ]
    return []
