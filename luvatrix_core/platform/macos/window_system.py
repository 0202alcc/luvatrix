from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass
class MacOSWindowHandle:
    window: object
    layer: object


@dataclass(frozen=True)
class MacOSDebugMenuAction:
    action_id: str
    label: str
    enabled: bool


@dataclass(frozen=True)
class MacOSMenuConfig:
    app_title: str
    debug_actions: tuple[MacOSDebugMenuAction, ...]
    on_debug_action: Callable[[str], None]


class MacOSWindowSystem(Protocol):
    def create_window(
        self,
        width: int,
        height: int,
        title: str,
        use_metal_layer: bool = True,
        preserve_aspect_ratio: bool = False,
        menu_config: MacOSMenuConfig | None = None,
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

    def __init__(self) -> None:
        self._menu_targets: list[object] = []

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
        menu_config: MacOSMenuConfig | None = None,
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
        self._install_main_menu(app=app, menu_config=menu_config)
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

    def _install_main_menu(self, *, app, menu_config: MacOSMenuConfig | None) -> None:
        try:
            from AppKit import NSMenu, NSMenuItem  # type: ignore
        except Exception:
            return
        app_name = menu_config.app_title if menu_config is not None else "Luvatrix"
        main_menu = NSMenu.alloc().initWithTitle_(app_name)
        top_sections = ("Luvatrix", "File", "Edit", "View", "Debug", "Window", "Help")
        self._menu_targets = []
        for section in top_sections:
            section_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(section, None, "")
            section_menu = NSMenu.alloc().initWithTitle_(section)
            if section == "Debug":
                self._populate_debug_section(section_menu=section_menu, menu_config=menu_config)
            else:
                placeholder = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("No Action", None, "")
                placeholder.setEnabled_(False)
                section_menu.addItem_(placeholder)
            main_menu.addItem_(section_item)
            main_menu.setSubmenu_forItem_(section_menu, section_item)
        app.setMainMenu_(main_menu)

    def _populate_debug_section(self, *, section_menu, menu_config: MacOSMenuConfig | None) -> None:
        from AppKit import NSMenuItem  # type: ignore

        if menu_config is None or not menu_config.debug_actions:
            placeholder = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Debug Menu Unavailable", None, "")
            placeholder.setEnabled_(False)
            section_menu.addItem_(placeholder)
            return
        callback = menu_config.on_debug_action
        for idx, action in enumerate(menu_config.debug_actions):
            target = _MenuActionTarget.alloc().initWithCallback_actionId_(callback, action.action_id)
            self._menu_targets.append(target)
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(action.label, "onMenuAction:", "")
            item.setTarget_(target)
            item.setTag_(idx)
            item.setEnabled_(bool(action.enabled))
            section_menu.addItem_(item)


_MENU_ACTION_TARGET_CLASS_NAME = "_LuvatrixDebugMenuTarget"
_MENU_ACTION_TARGET_CLASS: type[object] | None = None


def _resolve_menu_action_target_class() -> type[object] | None:
    global _MENU_ACTION_TARGET_CLASS
    if _MENU_ACTION_TARGET_CLASS is not None:
        return _MENU_ACTION_TARGET_CLASS
    try:
        from Foundation import NSObject  # type: ignore
    except Exception:
        return None
    try:
        import objc  # type: ignore

        existing = objc.lookUpClass(_MENU_ACTION_TARGET_CLASS_NAME)
        if existing is not None:
            _MENU_ACTION_TARGET_CLASS = existing
            return existing
    except Exception:
        pass
    dynamic = type(
        _MENU_ACTION_TARGET_CLASS_NAME,
        (NSObject,),
        {
            "initWithCallback_actionId_": _MenuActionTarget.initWithCallback_actionId_,
            "onMenuAction_": _MenuActionTarget.onMenuAction_,
        },
    )
    _MENU_ACTION_TARGET_CLASS = dynamic
    return dynamic


class _MenuActionTarget:
    @classmethod
    def alloc(cls):
        target_cls = _resolve_menu_action_target_class()
        if target_cls is None:
            return cls()
        return target_cls.alloc()

    def initWithCallback_actionId_(self, callback, action_id):
        self._callback = callback
        self._action_id = action_id
        return self

    def onMenuAction_(self, _sender):
        try:
            self._callback(str(self._action_id))
        except Exception:
            return
