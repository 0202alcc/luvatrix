__all__ = ["IOSMetalBackend", "UIKitWindowSystem"]


def __getattr__(name: str):  # noqa: N807
    if name in ("IOSMetalBackend",):
        from .metal_backend import IOSMetalBackend  # noqa: PLC0415
        globals()["IOSMetalBackend"] = IOSMetalBackend
        return globals()[name]
    if name in ("UIKitWindowSystem",):
        from .window_system import UIKitWindowSystem  # noqa: PLC0415
        globals()["UIKitWindowSystem"] = UIKitWindowSystem
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
