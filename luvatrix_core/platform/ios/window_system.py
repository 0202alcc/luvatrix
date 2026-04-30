from __future__ import annotations


class UIKitWindowHandle:
    def __init__(self, layer: object) -> None:
        self.layer = layer


class UIKitWindowSystem:
    """
    UIKit window system for iOS/iPadOS.

    The CAMetalLayer is created by runner.setup_ui() on the main thread and
    passed in here. create_window() simply wraps it in a handle so IOSMetalBackend
    can call layer APIs. pump_events() is a no-op — UIKit owns the main-thread
    runloop. is_window_open() always returns True; iOS handles app termination.
    """

    def __init__(self, layer: object) -> None:
        self._layer = layer

    def create_window(
        self,
        width: int,
        height: int,
        title: str,
        use_metal_layer: bool = True,
        preserve_aspect_ratio: bool = False,
        **kwargs,
    ) -> UIKitWindowHandle:
        return UIKitWindowHandle(layer=self._layer)

    def destroy_window(self, handle: UIKitWindowHandle) -> None:
        pass

    def pump_events(self) -> None:
        pass

    def is_window_open(self, handle: UIKitWindowHandle) -> bool:
        return True
