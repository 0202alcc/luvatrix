"""AppKit native-control bridge: real NSViews over the luvatrix window.

Places genuine AppKit controls (NSTextField first) as subviews of the
window's content view — the same MTKView-overlay pattern games use for HUDs.
The bridge also acts as the ``NativeInputGate`` for the window's HDI source,
solving the two conflicts created by luvatrix's hardware-level input:

- keyboard: IOKit delivers keys even while a native field is first responder,
  so ``suppress_keyboard()`` reports True then and the gate drops them;
- pointer: IOKit clicks land in the scene hit dispatch AND on the control,
  so ``consume_point()`` claims points inside a live control's frame.

Everything here must run on the main thread (AppKit rule); the app loop and
event pump already run there. Off-macOS, ``wire_native_controls`` degrades
silently and returns the original HDI source.
"""
from __future__ import annotations

import sys
import threading

from luvatrix_core.core.native_controls import (
    GatedHDIEventSource,
    NativeInputGate,
    register_native_control_bridge,
    unregister_native_control_bridge,
)

_ROUNDED_BEZEL = 1  # NSTextFieldRoundedBezel

# None = unresolved, False = resolved-absent (pre-Tahoe), else the class.
_GLASS_EFFECT_VIEW_CLASS = None


def _macos_major_version() -> int | None:
    """Marketing major of the host macOS (26 for Tahoe), None off-mac."""
    try:
        import platform

        release = (platform.mac_ver()[0] or "").strip()
        if not release:
            return None
        return int(release.split(".", 1)[0])
    except Exception:  # noqa: BLE001
        return None


def _glass_effect_view_class():
    """Return NSGlassEffectView when the host has it (macOS 26+), else None.

    Resolution order matters: ``objc.lookUpClass`` searches only
    already-loaded classes, so AppKit must be imported FIRST (the 26.6
    compat probe resolved the class only after ``import AppKit``), and the
    OS version gate keeps older hosts on the NSVisualEffectView fallback
    even if some other import made the symbol visible.
    """
    global _GLASS_EFFECT_VIEW_CLASS
    if _GLASS_EFFECT_VIEW_CLASS is not None:
        return _GLASS_EFFECT_VIEW_CLASS or None
    try:
        if _macos_major_version() is None or _macos_major_version() < 26:
            raise RuntimeError("NSGlassEffectView requires macOS 26+")
        import AppKit  # type: ignore  # noqa: F401 — loads AppKit classes into the runtime
        import objc  # type: ignore

        _GLASS_EFFECT_VIEW_CLASS = objc.lookUpClass("NSGlassEffectView")
    except Exception:  # noqa: BLE001
        _GLASS_EFFECT_VIEW_CLASS = False
    resolved = "NSGlassEffectView" if _GLASS_EFFECT_VIEW_CLASS else "NSVisualEffectView (fallback)"
    print(f"[luvatrix] native glass path: {resolved}", file=sys.stderr, flush=True)
    return _GLASS_EFFECT_VIEW_CLASS or None


class AppKitNativeControlBridge:
    """Native controls over one AppKit window's content view."""

    def __init__(self, window_handle, logical_extent: tuple[float, float] | None = None) -> None:
        try:
            from AppKit import NSTextField  # type: ignore  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "native controls require PyObjC/AppKit; install "
                "pyobjc-framework-Cocoa (luvatrix[macos])"
            ) from exc
        self._window_handle = window_handle
        self._logical_extent = logical_extent
        self._fields: list[_AppKitTextField] = []
        self._buttons: list[_AppKitButton] = []
        self._web_views: list[_AppKitWebView] = []
        self._glass: list[_AppKitGlassSurface] = []
        self._button_monitor = None
        self._closed = False

    # -- NativeControlBridge ---------------------------------------------------

    @property
    def available(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self._window_handle.window.isVisible())
        except Exception:  # noqa: BLE001
            return False

    @property
    def supports_under_glass(self) -> bool:
        """True when the window has the render-host split AND a Metal layer
        the presenter can make see-through — only then does glass placed
        below the render view actually show."""
        return bool(getattr(self._window_handle, "under_glass_capable", False)
                    and getattr(self._window_handle, "render_view", None) is not None)

    def create_text_field(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        placeholder: str = "",
        value: str = "",
        secure: bool = False,
        within=None,
        bordered: bool = True,
        on_change=None,
        on_submit=None,
    ) -> "_AppKitTextField":
        self._require_main_thread()
        if not self.available:
            raise RuntimeError("native-control bridge is not available (no live window)")
        field = _AppKitTextField(
            self,
            x=x,
            y=y,
            width=width,
            height=height,
            placeholder=placeholder,
            value=value,
            secure=secure,
            within=within,
            bordered=bordered,
            on_change=on_change,
            on_submit=on_submit,
        )
        self._fields.append(field)
        return field

    def create_web_view(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        redirect_prefix: str = "",
        on_redirect=None,
        on_navigation_state=None,
    ) -> "_AppKitWebView":
        self._require_main_thread()
        if not self.available:
            raise RuntimeError("native-control bridge is not available (no live window)")
        try:
            from WebKit import WKWebView  # type: ignore  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "native web view requires pyobjc-framework-WebKit (luvatrix[macos])"
            ) from exc
        view = _AppKitWebView(
            self,
            x=x,
            y=y,
            width=width,
            height=height,
            redirect_prefix=redirect_prefix,
            on_redirect=on_redirect,
            on_navigation_state=on_navigation_state,
        )
        self._web_views.append(view)
        self._install_button_monitor()
        return view

    def create_button(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        title: str = "",
        within=None,
        on_press=None,
    ) -> "_AppKitButton":
        self._require_main_thread()
        if not self.available:
            raise RuntimeError("native-control bridge is not available (no live window)")
        button = _AppKitButton(
            self,
            x=x,
            y=y,
            width=width,
            height=height,
            title=title,
            within=within,
            on_press=on_press,
        )
        self._buttons.append(button)
        # stderr on purpose: piped stdout is block-buffered and loses lines.
        print(f"[luvatrix] native button created title={button._title!r} "
              f"frame={button.frame} buttons={len(self._buttons)}", file=sys.stderr, flush=True)
        return button

    def create_glass_surface(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        corner_radius: float = 0.0,
        style: str = "regular",
        placement: str = "above",
    ) -> "_AppKitGlassSurface":
        self._require_main_thread()
        if not self.available:
            raise RuntimeError("native-control bridge is not available (no live window)")
        if placement == "under" and not self.supports_under_glass:
            raise RuntimeError(
                'placement="under" requires an under-glass-capable window '
                "(render-host split + Metal presenter transparency)")
        surface = _AppKitGlassSurface(
            self,
            x=x,
            y=y,
            width=width,
            height=height,
            corner_radius=corner_radius,
            style=style,
            placement=placement,
        )
        self._glass.append(surface)
        return surface

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._remove_button_monitor()
        for field in list(self._fields):
            try:
                field.destroy()
            except Exception:  # noqa: BLE001
                pass
        self._fields.clear()
        for button in list(self._buttons):
            try:
                button.destroy()
            except Exception:  # noqa: BLE001
                pass
        self._buttons.clear()
        for view in list(self._web_views):
            try:
                view.destroy()
            except Exception:  # noqa: BLE001
                pass
        self._web_views.clear()
        for surface in list(self._glass):
            try:
                surface.destroy()
            except Exception:  # noqa: BLE001
                pass
        self._glass.clear()
        unregister_native_control_bridge(self)

    # -- NativeInputGate ---------------------------------------------------------

    def suppress_keyboard(self) -> bool:
        """True while any bridged field owns the keyboard (first responder)."""
        # A live web view (embedded OAuth) owns the screen: keys go to the
        # page's form, never to app shortcuts.
        for view in self._web_views:
            if not view.destroyed and view.is_visible:
                return True
        try:
            first = self._window_handle.window.firstResponder()
        except Exception:  # noqa: BLE001
            return False
        if first is None:
            return False
        for field in self._fields:
            if field.destroyed or not field.is_visible:
                continue
            ns_field = field.ns_field
            if first is ns_field:
                return True
            # While editing, the first responder is the field editor (NSTextView).
            try:
                if ns_field.currentEditor() is not None and first is ns_field.currentEditor():
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def consume_point(self, x: float, y: float) -> bool:
        """True when the window-local top-left point is inside a live control."""
        for control in (*self._fields, *self._buttons, *self._web_views):
            if control.destroyed or not control.is_visible:
                continue
            fx, fy, fw, fh = control.frame
            if fx <= x <= fx + fw and fy <= y <= fy + fh:
                return True
        return False

    # -- internals ---------------------------------------------------------------

    def _content_view(self):
        return self._window_handle.window.contentView()

    def _view_scale(self) -> tuple[float, float]:
        """Logical (scene) → view points; 1:1 unless the window resized."""
        extent = self._logical_extent
        if not extent or extent[0] <= 0 or extent[1] <= 0:
            return (1.0, 1.0)
        try:
            bounds = self._content_view().bounds().size
            return (float(bounds.width) / float(extent[0]),
                    float(bounds.height) / float(extent[1]))
        except Exception:  # noqa: BLE001
            return (1.0, 1.0)

    def _remove(self, field: "_AppKitTextField") -> None:
        if field in self._fields:
            self._fields.remove(field)

    def _remove_button(self, button: "_AppKitButton") -> None:
        if button in self._buttons:
            self._buttons.remove(button)

    def _remove_web_view(self, view: "_AppKitWebView") -> None:
        if view in self._web_views:
            self._web_views.remove(view)
        if not any(not v.destroyed for v in self._web_views):
            self._remove_button_monitor()

    # -- button event routing while a web view is live --------------------------
    # WKWebView's compositing layer can win AppKit hit-testing over sibling
    # buttons on the CAMetalLayer-hosted content view (embedded-login Cancel
    # rendered but clicks passed through to the page). While a web view is
    # live, left-mouse-downs are matched against native button frames through
    # an NSEvent local monitor instead of relying on view hit-testing.

    def _install_button_monitor(self) -> None:
        if self._button_monitor is not None:
            return
        from AppKit import NSEvent, NSLeftMouseDownMask  # type: ignore

        def _handler(event):
            return self._route_button_mousedown(event)

        self._button_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSLeftMouseDownMask, _handler)
        print(f"[luvatrix] button monitor installed token={self._button_monitor!r}",
              file=sys.stderr, flush=True)

    def _remove_button_monitor(self) -> None:
        token = self._button_monitor
        self._button_monitor = None
        if token is None:
            return
        try:
            from AppKit import NSEvent  # type: ignore

            NSEvent.removeMonitor_(token)
            print(f"[luvatrix] button monitor removed token={token!r}", file=sys.stderr, flush=True)
        except Exception:  # noqa: BLE001
            pass

    def _route_button_mousedown(self, event):
        """Fire the native button under a left-mouse-down, swallowing the event.

        Returns the event untouched when no live, visible, enabled button
        contains the point, so the page and every other responder see it.
        """
        try:
            point = event.locationInWindow()
            content = self._content_view()
            local = content.convertPoint_fromView_(point, None)
            sx, sy = self._view_scale()
            view_h = float(content.bounds().size.height)
            x = float(local.x) / sx
            y = (view_h - float(local.y)) / sy
        except Exception as exc:  # noqa: BLE001
            print(f"[luvatrix] button-monitor click conversion failed: {exc!r}",
                  file=sys.stderr, flush=True)
            return event
        for button in reversed(self._buttons):
            if button.destroyed or not button.is_visible or not button._enabled:
                continue
            fx, fy, fw, fh = button.frame
            if fx <= x <= fx + fw and fy <= y <= fy + fh:
                print(f"[luvatrix] button-monitor click logical=({x:.1f}, {y:.1f}) "
                      f"buttons={len(self._buttons)} match={button._title!r} -> swallowed",
                      file=sys.stderr, flush=True)
                if button._on_press is not None:
                    button._on_press()
                return None  # swallowed: the web page must not see this click
        print(f"[luvatrix] button-monitor click logical=({x:.1f}, {y:.1f}) "
              f"buttons={len(self._buttons)} match=none -> passthrough", file=sys.stderr, flush=True)
        return event

    def _remove_glass(self, surface: "_AppKitGlassSurface") -> None:
        if surface in self._glass:
            self._glass.remove(surface)

    def _set_view_frame(self, view, x: float, y: float, width: float, height: float) -> None:
        """Place a subview using scene logical (top-left) coordinates."""
        from AppKit import NSMakeRect  # type: ignore

        sx, sy = self._view_scale()
        view_h = float(self._content_view().bounds().size.height)
        vx, vw = float(x) * sx, float(width) * sx
        vh = float(height) * sy
        appkit_y = view_h - float(y) * sy - vh
        view.setFrame_(NSMakeRect(vx, appkit_y, vw, vh))

    @staticmethod
    def _require_main_thread() -> None:
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("native controls must be used on the main thread")


class _AppKitGlassSurface:
    """Material plate: NSGlassEffectView (macOS 26+) or NSVisualEffectView below.

    Pure decoration — the input gate never claims its points, so scene hit
    dispatch keeps working underneath it.
    """

    def __init__(self, bridge: AppKitNativeControlBridge, *, x, y, width, height,
                 corner_radius=0.0, style="regular", placement="above") -> None:
        from AppKit import NSMakeRect  # type: ignore

        self._bridge = bridge
        self._placement = placement
        self.destroyed = False
        glass_cls = _glass_effect_view_class()
        self._is_glass_effect = glass_cls is not None
        if glass_cls is not None:
            from AppKit import NSView  # type: ignore

            self._view = glass_cls.alloc().initWithFrame_(
                NSMakeRect(0.0, 0.0, float(width), float(height)))
            # NSGlassEffectView does not auto-create its content view (verified
            # on macOS 26.6); install one before anything parents into it.
            host = self._view.contentView()
            if host is None:
                host = NSView.alloc().initWithFrame_(
                    NSMakeRect(0.0, 0.0, float(width), float(height)))
                self._view.setContentView_(host)
            self._host = host
            if corner_radius:
                self._apply_corner_radius(float(corner_radius))
        else:
            from AppKit import (  # type: ignore
                NSVisualEffectBlendingModeWithinWindow,
                NSVisualEffectMaterialHUD,
                NSVisualEffectMaterialSidebar,
                NSVisualEffectStateActive,
                NSVisualEffectView,
            )

            self._view = NSVisualEffectView.alloc().initWithFrame_(
                NSMakeRect(0.0, 0.0, float(width), float(height)))
            self._view.setMaterial_(
                NSVisualEffectMaterialSidebar if style == "sidebar" else NSVisualEffectMaterialHUD)
            self._view.setBlendingMode_(NSVisualEffectBlendingModeWithinWindow)
            self._view.setState_(NSVisualEffectStateActive)
            if corner_radius:
                # NSVisualEffectView has no corner-radius API; round its layer.
                self._view.setWantsLayer_(True)
                layer = self._view.layer()
                if layer is not None:
                    layer.setCornerRadius_(float(corner_radius))
                    layer.setMasksToBounds_(True)
            self._host = self._view
        if placement == "under":
            from AppKit import NSWindowBelow  # type: ignore

            # Under the render surface: scene content composites crisply on
            # top while the real material shows through the transparent zone.
            bridge._content_view().addSubview_positioned_relativeTo_(
                self._view, NSWindowBelow, bridge._window_handle.render_view)
        else:
            bridge._content_view().addSubview_(self._view)
        self._logical_frame = (float(x), float(y), float(width), float(height))
        self.set_frame(x, y, width, height)

    def _apply_corner_radius(self, radius: float) -> None:
        """Round the visible edge, and log what actually took.

        macOS 26.6 accepted ``setCornerRadius:`` without error yet rendered
        pixel-square (Mac round-2 evidence) — the property alone does not
        drive the effect's shape, so the view's own layer clips the edge as
        well. Applied after the content view is installed.
        """
        try:
            self._view.setCornerRadius_(radius)
        except Exception as exc:  # noqa: BLE001
            print(f"[luvatrix] NSGlassEffectView.setCornerRadius_ failed: {exc!r}",
                  file=sys.stderr, flush=True)
        layer_rounded = False
        try:
            self._view.setWantsLayer_(True)
            layer = self._view.layer()
            if layer is not None:
                layer.setCornerRadius_(radius)
                layer.setMasksToBounds_(True)
                layer_rounded = True
        except Exception:  # noqa: BLE001
            pass
        try:
            readback = float(self._view.cornerRadius())
        except Exception:  # noqa: BLE001
            readback = float("nan")
        try:
            config_sel = bool(self._view.respondsToSelector_("setCornerConfiguration:"))
        except Exception:  # noqa: BLE001
            config_sel = False
        print(f"[luvatrix] glass corner radius: set={radius} readback={readback} "
              f"layer-rounded={layer_rounded} corner-config-selector={config_sel}",
              file=sys.stderr, flush=True)

    def _content_host(self):
        """View that should parent controls placed inside this surface."""
        return self._host

    # -- NativeGlassSurface protocol -------------------------------------------

    @property
    def frame(self) -> tuple[float, float, float, float]:
        return self._logical_frame

    def set_frame(self, x: float, y: float, width: float, height: float) -> None:
        self._logical_frame = (float(x), float(y), float(width), float(height))
        self._bridge._set_view_frame(self._view, x, y, width, height)

    def set_corner_radius(self, radius: float) -> None:
        radius = float(radius)
        if self._is_glass_effect:
            self._apply_corner_radius(radius)
            return
        # NSVisualEffectView fallback: the layer carries the rounding.
        try:
            self._view.setWantsLayer_(True)
            layer = self._view.layer()
            if layer is not None:
                layer.setCornerRadius_(radius)
                layer.setMasksToBounds_(True)
        except Exception:  # noqa: BLE001
            pass

    def show(self) -> None:
        self._view.setHidden_(False)

    def hide(self) -> None:
        self._view.setHidden_(True)

    @property
    def is_visible(self) -> bool:
        return not bool(self._view.isHidden())

    def destroy(self) -> None:
        if self.destroyed:
            return
        self.destroyed = True
        try:
            self._view.removeFromSuperview()
        except Exception:  # noqa: BLE001
            pass
        self._bridge._remove_glass(self)


class _AppKitWebView:
    """One WKWebView in scene logical coordinates with redirect interception.

    The navigation delegate cancels navigations matching ``redirect_prefix``
    and reports the full URL — the embedded-OAuth pattern: the provider's
    page runs in the view, the loopback redirect never leaves the app.
    """

    _DELEGATE_CLASS = None

    def __init__(self, bridge: AppKitNativeControlBridge, *, x, y, width, height,
                 redirect_prefix, on_redirect, on_navigation_state=None) -> None:
        from AppKit import NSMakeRect  # type: ignore
        from WebKit import WKWebView  # type: ignore

        self._bridge = bridge
        self._redirect_prefix = redirect_prefix
        self._on_redirect = on_redirect
        self._on_nav_state = on_navigation_state
        self.destroyed = False
        self._wk = WKWebView.alloc().initWithFrame_(
            NSMakeRect(0.0, 0.0, float(width), float(height)))
        self._owner_key: int | None = None
        self._delegate = self._make_delegate()
        self._wk.setNavigationDelegate_(self._delegate)
        # WKWebView.canGoBack is KVO-compliant; the delegate doubles as the
        # observer so the app can arm/disarm its Back button on every change.
        try:
            self._wk.addObserver_forKeyPath_options_context_(
                self._delegate, "canGoBack", 0, None)
        except Exception:  # noqa: BLE001
            pass
        # Insert below every sibling: the compositing WKWebView can obscure
        # native controls on the layer tree regardless of NSView add order
        # (Cancel never visibly rendered on the Mac build). Native buttons and
        # glass must always composite above the page.
        from AppKit import NSWindowBelow  # type: ignore

        bridge._content_view().addSubview_positioned_relativeTo_(
            self._wk, NSWindowBelow, None)
        self._logical_frame = (float(x), float(y), float(width), float(height))
        self.set_frame(x, y, width, height)

    # -- NativeWebView protocol -------------------------------------------------

    @property
    def frame(self) -> tuple[float, float, float, float]:
        return self._logical_frame

    def load_url(self, url: str) -> None:
        from Foundation import NSURL, NSURLRequest  # type: ignore

        self._wk.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(str(url))))

    @property
    def can_go_back(self) -> bool:
        try:
            return bool(self._wk.canGoBack())
        except Exception:  # noqa: BLE001
            return False

    def go_back(self) -> None:
        try:
            self._wk.goBack()
        except Exception:  # noqa: BLE001
            pass

    def _notify_nav_state(self) -> None:
        if self._on_nav_state is None:
            return
        try:
            self._on_nav_state()
        except Exception:  # noqa: BLE001
            pass

    def set_frame(self, x: float, y: float, width: float, height: float) -> None:
        self._logical_frame = (float(x), float(y), float(width), float(height))
        self._bridge._set_view_frame(self._wk, x, y, width, height)

    def show(self) -> None:
        self._wk.setHidden_(False)

    def hide(self) -> None:
        self._wk.setHidden_(True)

    @property
    def is_visible(self) -> bool:
        return not bool(self._wk.isHidden())

    def destroy(self) -> None:
        if self.destroyed:
            return
        self.destroyed = True
        if self._owner_key is not None:
            _AppKitWebView._delegate_owners.pop(self._owner_key, None)
            self._owner_key = None
        try:
            # A leaked KVO observer crashes on the next notification.
            self._wk.removeObserver_forKeyPath_(self._delegate, "canGoBack")
        except Exception:  # noqa: BLE001
            pass
        try:
            self._wk.setNavigationDelegate_(None)
            self._wk.removeFromSuperview()
        except Exception:  # noqa: BLE001
            pass
        self._bridge._remove_web_view(self)

    @property
    def ns_web_view(self):
        return self._wk

    # -- navigation delegate ------------------------------------------------------

    @classmethod
    def _delegate_class(cls):
        if cls._DELEGATE_CLASS is not None:
            return cls._DELEGATE_CLASS
        import objc  # type: ignore
        from Foundation import NSObject  # type: ignore

        name = "_LuvatrixWebNavDelegate"
        try:
            existing = objc.lookUpClass(name)
            if existing is not None:
                cls._DELEGATE_CLASS = existing
                return existing
        except Exception:  # noqa: BLE001
            pass

        def webView_decidePolicyForNavigationAction_decisionHandler_(  # noqa: N802
                self, webview, action, handler):
            owner = _AppKitWebView._delegate_owners.get(self._owner_key)
            url = ""
            try:
                url = str(action.request().URL().absoluteString())
            except Exception:  # noqa: BLE001
                pass
            if (owner is not None and owner._redirect_prefix
                    and url.startswith(owner._redirect_prefix)):
                handler(0)  # WKNavigationActionPolicyCancel
                if owner._on_redirect is not None:
                    owner._on_redirect(url)
                return
            handler(1)  # WKNavigationActionPolicyAllow

        def initWithOwnerKey_(self, key):
            self._owner_key = key
            return self

        def observeValueForKeyPath_ofObject_change_context_(  # noqa: N802
                self, key_path, _obj, _change, _ctx):
            owner = _AppKitWebView._delegate_owners.get(self._owner_key)
            if owner is not None and key_path == "canGoBack":
                owner._notify_nav_state()

        cls._DELEGATE_CLASS = type(
            name,
            (NSObject,),
            {
                "webView_decidePolicyForNavigationAction_decisionHandler_":
                    webView_decidePolicyForNavigationAction_decisionHandler_,
                "observeValueForKeyPath_ofObject_change_context_":
                    observeValueForKeyPath_ofObject_change_context_,
                "initWithOwnerKey_": initWithOwnerKey_,
            },
        )
        return cls._DELEGATE_CLASS

    _delegate_owners: dict[int, "_AppKitWebView"] = {}
    _next_owner_key = 1

    def _make_delegate(self):
        delegate_cls = self._delegate_class()
        key = _AppKitWebView._next_owner_key
        _AppKitWebView._next_owner_key += 1
        _AppKitWebView._delegate_owners[key] = self
        self._owner_key = key
        return delegate_cls.alloc().initWithOwnerKey_(key)


class _AppKitButton:
    """Borderless NSButton (Liquid Glass family) in scene logical coordinates.

    Always borderless with the focus ring suppressed — the enclosing glass
    capsule is the affordance. Fires ``on_press`` via a dynamic delegate.
    """

    _DELEGATE_CLASS = None

    def __init__(self, bridge: AppKitNativeControlBridge, *, x, y, width, height,
                 title, within=None, on_press) -> None:
        from AppKit import NSButton, NSColor, NSFocusRingTypeNone, NSMakeRect  # type: ignore

        self._bridge = bridge
        self._within = within
        self._on_press = on_press
        self._title = str(title)
        self.destroyed = False
        self._enabled = True
        self._ns = NSButton.alloc().initWithFrame_(
            NSMakeRect(0.0, 0.0, float(width), float(height)))
        self._ns.setTitle_(self._title)
        self._ns.setBordered_(False)
        self._ns.setFocusRingType_(NSFocusRingTypeNone)
        self._ns.setButtonType_(7)  # NSMomentaryPushInButton
        # Borderless titles default to controlTextColor — black in light mode,
        # invisible over the dark login page. Pin a light tint.
        self._ns.setContentTintColor_(NSColor.whiteColor())
        self._owner_key: int | None = None
        self._delegate = self._make_delegate()
        self._ns.setTarget_(self._delegate)
        self._ns.setAction_("onButtonPress:")
        parent = within._content_host() if within is not None else bridge._content_view()
        parent.addSubview_(self._ns)
        self._logical_frame = (float(x), float(y), float(width), float(height))
        self.set_frame(x, y, width, height)

    # -- NativeButton protocol --------------------------------------------------

    @property
    def frame(self) -> tuple[float, float, float, float]:
        return self._logical_frame

    def set_frame(self, x: float, y: float, width: float, height: float) -> None:
        from AppKit import NSMakeRect  # type: ignore

        self._logical_frame = (float(x), float(y), float(width), float(height))
        if self._within is not None:
            # Parent-local frame inside the glass surface's content host; the
            # stored logical frame stays window-local for the input gate.
            gx, gy, _gw, gh = self._within.frame
            sx, sy = self._bridge._view_scale()
            parent_h = float(gh) * sy
            lx = (float(x) - gx) * sx
            ly = parent_h - (float(y) - gy) * sy - float(height) * sy
            self._ns.setFrame_(NSMakeRect(lx, ly, float(width) * sx, float(height) * sy))
            return
        self._bridge._set_view_frame(self._ns, x, y, width, height)

    def show(self) -> None:
        self._ns.setHidden_(False)

    def hide(self) -> None:
        self._ns.setHidden_(True)

    @property
    def is_visible(self) -> bool:
        return not bool(self._ns.isHidden())

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self._ns.setEnabled_(bool(enabled))

    def destroy(self) -> None:
        if self.destroyed:
            return
        self.destroyed = True
        if self._owner_key is not None:
            _AppKitButton._delegate_owners.pop(self._owner_key, None)
            self._owner_key = None
        try:
            self._ns.setTarget_(None)
            self._ns.removeFromSuperview()
        except Exception:  # noqa: BLE001
            pass
        self._bridge._remove_button(self)

    @property
    def ns_button(self):
        return self._ns

    # -- delegate ----------------------------------------------------------------

    @classmethod
    def _delegate_class(cls):
        if cls._DELEGATE_CLASS is not None:
            return cls._DELEGATE_CLASS
        import objc  # type: ignore
        from Foundation import NSObject  # type: ignore

        name = "_LuvatrixNativeButtonDelegate"
        try:
            existing = objc.lookUpClass(name)
            if existing is not None:
                cls._DELEGATE_CLASS = existing
                return existing
        except Exception:  # noqa: BLE001
            pass

        def onButtonPress_(self, sender):  # noqa: N802
            owner = _AppKitButton._delegate_owners.get(self._owner_key)
            if owner is not None and owner._on_press is not None:
                owner._on_press()

        def initWithOwnerKey_(self, key):
            self._owner_key = key
            return self

        cls._DELEGATE_CLASS = type(
            name,
            (NSObject,),
            {
                "onButtonPress_": onButtonPress_,
                "initWithOwnerKey_": initWithOwnerKey_,
            },
        )
        return cls._DELEGATE_CLASS

    _delegate_owners: dict[int, "_AppKitButton"] = {}
    _next_owner_key = 1

    def _make_delegate(self):
        delegate_cls = self._delegate_class()
        key = _AppKitButton._next_owner_key
        _AppKitButton._next_owner_key += 1
        _AppKitButton._delegate_owners[key] = self
        self._owner_key = key
        return delegate_cls.alloc().initWithOwnerKey_(key)


class _AppKitTextField:
    """One NSTextField positioned in scene (top-left logical) coordinates."""

    _DELEGATE_CLASS = None

    def __init__(self, bridge: AppKitNativeControlBridge, *, x, y, width, height,
                 placeholder, value, secure, within=None, bordered=True,
                 on_change, on_submit) -> None:
        from AppKit import NSMakeRect, NSSecureTextField, NSTextField  # type: ignore

        self._bridge = bridge
        self._within = within
        self._on_change = on_change
        self._on_submit = on_submit
        self.destroyed = False
        cls = NSSecureTextField if secure else NSTextField
        self._ns = cls.alloc().initWithFrame_(NSMakeRect(0.0, 0.0, float(width), float(height)))
        if bordered:
            self._ns.setBezeled_(True)
            self._ns.setBezelStyle_(_ROUNDED_BEZEL)
            self._ns.setDrawsBackground_(True)
        else:
            from AppKit import NSFocusRingTypeNone  # type: ignore

            self._ns.setBezeled_(False)
            self._ns.setBordered_(False)
            self._ns.setDrawsBackground_(False)
            # The glass capsule is the affordance; an accent-colored ring
            # around a borderless field reads as a stray rectangle.
            self._ns.setFocusRingType_(NSFocusRingTypeNone)
        self._ns.setEditable_(True)
        self._ns.setSelectable_(True)
        if placeholder:
            self._ns.setPlaceholderString_(str(placeholder))
        if value:
            self._ns.setStringValue_(str(value))
        self._owner_key: int | None = None
        self._delegate = self._make_delegate()
        self._ns.setDelegate_(self._delegate)
        if on_submit is not None:
            self._ns.setTarget_(self._delegate)
            self._ns.setAction_("onFieldSubmit:")
        parent = within._content_host() if within is not None else bridge._content_view()
        parent.addSubview_(self._ns)
        self._logical_frame = (float(x), float(y), float(width), float(height))
        self.set_frame(x, y, width, height)

    # -- NativeTextField protocol ---------------------------------------------

    @property
    def value(self) -> str:
        return str(self._ns.stringValue())

    def set_value(self, value: str) -> None:
        self._ns.setStringValue_(str(value))

    def set_frame(self, x: float, y: float, width: float, height: float) -> None:
        from AppKit import NSMakeRect  # type: ignore

        self._logical_frame = (float(x), float(y), float(width), float(height))
        if self._within is not None:
            # Parent-local frame inside the glass surface's content host; the
            # stored logical frame stays window-local for the input gate.
            gx, gy, _gw, gh = self._within.frame
            sx, sy = self._bridge._view_scale()
            parent_h = float(gh) * sy
            lx = (float(x) - gx) * sx
            ly = parent_h - (float(y) - gy) * sy - float(height) * sy
            self._ns.setFrame_(NSMakeRect(lx, ly, float(width) * sx, float(height) * sy))
            return
        self._bridge._set_view_frame(self._ns, x, y, width, height)

    @property
    def frame(self) -> tuple[float, float, float, float]:
        """Logical (scene, top-left) frame — the same space HDI events use."""
        return self._logical_frame

    def show(self) -> None:
        self._ns.setHidden_(False)

    def hide(self) -> None:
        self._ns.setHidden_(True)

    @property
    def is_visible(self) -> bool:
        return not bool(self._ns.isHidden())

    def focus(self) -> None:
        self._bridge._window_handle.window.makeFirstResponder_(self._ns)

    def resign(self) -> None:
        self._bridge._window_handle.window.makeFirstResponder_(None)

    def destroy(self) -> None:
        if self.destroyed:
            return
        self.destroyed = True
        if self._owner_key is not None:
            _AppKitTextField._delegate_owners.pop(self._owner_key, None)
            self._owner_key = None
        try:
            self._ns.setDelegate_(None)
            self._ns.setTarget_(None)
            self._ns.removeFromSuperview()
        except Exception:  # noqa: BLE001
            pass
        self._bridge._remove(self)

    @property
    def ns_field(self):
        return self._ns

    # -- delegate ----------------------------------------------------------------

    @classmethod
    def _delegate_class(cls):
        if cls._DELEGATE_CLASS is not None:
            return cls._DELEGATE_CLASS
        import objc  # type: ignore
        from Foundation import NSObject  # type: ignore

        name = "_LuvatrixNativeFieldDelegate"
        try:
            existing = objc.lookUpClass(name)
            if existing is not None:
                cls._DELEGATE_CLASS = existing
                return existing
        except Exception:  # noqa: BLE001
            pass

        def controlTextDidChange_(self, notification):  # noqa: N802
            owner = _AppKitTextField._delegate_owners.get(self._owner_key)
            if owner is not None and owner._on_change is not None:
                owner._on_change(owner.value)

        def onFieldSubmit_(self, sender):  # noqa: N802
            owner = _AppKitTextField._delegate_owners.get(self._owner_key)
            if owner is not None and owner._on_submit is not None:
                owner._on_submit(owner.value)

        def initWithOwnerKey_(self, key):
            self._owner_key = key
            return self

        cls._DELEGATE_CLASS = type(
            name,
            (NSObject,),
            {
                "controlTextDidChange_": controlTextDidChange_,
                "onFieldSubmit_": onFieldSubmit_,
                "initWithOwnerKey_": initWithOwnerKey_,
            },
        )
        return cls._DELEGATE_CLASS

    _delegate_owners: dict[int, "_AppKitTextField"] = {}
    _next_owner_key = 1

    def _make_delegate(self):
        delegate_cls = self._delegate_class()
        key = _AppKitTextField._next_owner_key
        _AppKitTextField._next_owner_key += 1
        _AppKitTextField._delegate_owners[key] = self
        self._owner_key = key
        return delegate_cls.alloc().initWithOwnerKey_(key)


def wire_native_controls(window_handle, source, logical_extent: tuple[float, float] | None = None):
    """Create + register the bridge and wrap the window's HDI source with its gate.

    Degrades silently: without PyObjC (or any failure) the app keeps the plain
    source and no bridge is registered, so ``luvatrix.app.native_controls()``
    returns None and apps keep drawn components.
    """
    try:
        bridge = AppKitNativeControlBridge(window_handle, logical_extent=logical_extent)
    except Exception:  # noqa: BLE001
        return source
    register_native_control_bridge(bridge)
    assert isinstance(bridge, NativeInputGate)
    return GatedHDIEventSource(source, bridge)
