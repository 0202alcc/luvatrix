from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class MacOSWindowHandle:
    window: object
    layer: object


class MacOSWindowSystem(Protocol):
    def create_window(
        self,
        width: int,
        height: int,
        title: str,
        use_metal_layer: bool = True,
        preserve_aspect_ratio: bool = False,
    ) -> MacOSWindowHandle:
        ...

    def destroy_window(self, handle: MacOSWindowHandle) -> None:
        ...

    def pump_events(self) -> None:
        ...

    def is_window_open(self, handle: MacOSWindowHandle) -> bool:
        ...


class AppKitWindowSystem:
    """Best-effort AppKit/CAMetalLayer bootstrap for macOS."""

    def _imports(self):
        try:
            from AppKit import (  # type: ignore
                NSApp,
                NSApplication,
                NSApplicationActivationPolicyRegular,
                NSBackingStoreBuffered,
                NSMakeRect,
                NSWindow,
                NSWindowStyleMaskClosable,
                NSWindowStyleMaskMiniaturizable,
                NSWindowStyleMaskResizable,
                NSWindowStyleMaskTitled,
            )
            try:
                # Preferred PyObjC import path.
                from Quartz import CALayer, CAMetalLayer  # type: ignore
            except Exception:
                # Fallback for environments exposing QuartzCore directly.
                from QuartzCore import CALayer, CAMetalLayer  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "AppKit window bootstrap unavailable. Install PyObjC packages "
                "(pyobjc-core, pyobjc-framework-Cocoa, pyobjc-framework-Quartz)."
            ) from exc

        return {
            "NSApp": NSApp,
            "NSApplication": NSApplication,
            "NSApplicationActivationPolicyRegular": NSApplicationActivationPolicyRegular,
            "NSBackingStoreBuffered": NSBackingStoreBuffered,
            "NSMakeRect": NSMakeRect,
            "NSWindow": NSWindow,
            "NSWindowStyleMaskClosable": NSWindowStyleMaskClosable,
            "NSWindowStyleMaskMiniaturizable": NSWindowStyleMaskMiniaturizable,
            "NSWindowStyleMaskResizable": NSWindowStyleMaskResizable,
            "NSWindowStyleMaskTitled": NSWindowStyleMaskTitled,
            "CAMetalLayer": CAMetalLayer,
            "CALayer": CALayer,
        }

    def create_window(
        self,
        width: int,
        height: int,
        title: str,
        use_metal_layer: bool = True,
        preserve_aspect_ratio: bool = False,
    ) -> MacOSWindowHandle:
        ns = self._imports()
        app = ns["NSApp"]() or ns["NSApplication"].sharedApplication()
        app.setActivationPolicy_(ns["NSApplicationActivationPolicyRegular"])
        style = (
            ns["NSWindowStyleMaskTitled"]
            | ns["NSWindowStyleMaskClosable"]
            | ns["NSWindowStyleMaskResizable"]
            | ns["NSWindowStyleMaskMiniaturizable"]
        )
        frame = ns["NSMakeRect"](0.0, 0.0, float(width), float(height))
        window = ns["NSWindow"].alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style, ns["NSBackingStoreBuffered"], False
        )
        window.setTitle_(title)
        layer_cls = ns["CAMetalLayer"] if use_metal_layer else ns["CALayer"]
        layer = layer_cls.layer()
        if preserve_aspect_ratio:
            layer.setContentsGravity_("resizeAspect")
            try:
                import Quartz  # type: ignore

                layer.setBackgroundColor_(Quartz.CGColorCreateGenericRGB(0.0, 0.0, 0.0, 1.0))
            except Exception:
                pass
        else:
            layer.setContentsGravity_("resize")
        content_view = window.contentView()
        content_view.setWantsLayer_(True)
        content_view.setLayer_(layer)
        window.makeKeyAndOrderFront_(None)
        app.activateIgnoringOtherApps_(True)
        return MacOSWindowHandle(window=window, layer=layer)

    def destroy_window(self, handle: MacOSWindowHandle) -> None:
        window = handle.window
        try:
            window.orderOut_(None)
            window.close()
        except Exception:  # noqa: BLE001
            # shutdown path should be best-effort
            return

    def pump_events(self) -> None:
        ns = self._imports()
        app = ns["NSApp"]()
        if app is None:
            return
        from AppKit import NSDefaultRunLoopMode, NSEventMaskAny  # type: ignore
        from Foundation import NSDate  # type: ignore

        while True:
            event = app.nextEventMatchingMask_untilDate_inMode_dequeue_(
                NSEventMaskAny,
                NSDate.dateWithTimeIntervalSinceNow_(0.0),
                NSDefaultRunLoopMode,
                True,
            )
            if event is None:
                break
            app.sendEvent_(event)
        app.updateWindows()

    def is_window_open(self, handle: MacOSWindowHandle) -> bool:
        window = handle.window
        try:
            return bool(window.isVisible())
        except Exception:  # noqa: BLE001
            return False
