"""Android platform integration for the native Luvatrix runtime."""

from __future__ import annotations

__all__ = [
    "AndroidHDISource",
    "android_input_telemetry",
    "enqueue_native_key_event",
    "enqueue_native_touch_event",
]

_MODULE_MAP = {
    "AndroidHDISource": ".hdi_source",
    "android_input_telemetry": ".hdi_source",
    "enqueue_native_key_event": ".hdi_source",
    "enqueue_native_touch_event": ".hdi_source",
}


def __getattr__(name: str):
    if name not in _MODULE_MAP:
        raise AttributeError(name)
    from importlib import import_module

    module = import_module(f"{__name__}{_MODULE_MAP[name]}")
    value = getattr(module, name)
    globals()[name] = value
    return value
