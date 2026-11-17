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


def _glass_effect_view_class():
    """Return NSGlassEffectView when the host has it (macOS 26+), else None."""
    global _GLASS_EFFECT_VIEW_CLASS
    if _GLASS_EFFECT_VIEW_CLASS is not None:
        return _GLASS_EFFECT_VIEW_CLASS or None
    try:
        import objc  # type: ignore

        _GLASS_EFFECT_VIEW_CLASS = objc.lookUpClass("NSGlassEffectView")
    except Exception:  # noqa: BLE001
        _GLASS_EFFECT_VIEW_CLASS = False
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
        self._glass: list[_AppKitGlassSurface] = []
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

    def create_glass_surface(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        corner_radius: float = 0.0,
        style: str = "regular",
    ) -> "_AppKitGlassSurface":
        self._require_main_thread()
        if not self.available:
            raise RuntimeError("native-control bridge is not available (no live window)")
        surface = _AppKitGlassSurface(
            self,
            x=x,
            y=y,
            width=width,
            height=height,
            corner_radius=corner_radius,
            style=style,
        )
        self._glass.append(surface)
        return surface

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for field in list(self._fields):
            try:
                field.destroy()
            except Exception:  # noqa: BLE001
                pass
        self._fields.clear()
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
        for field in self._fields:
            if field.destroyed or not field.is_visible:
                continue
            fx, fy, fw, fh = field.frame
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
                 corner_radius=0.0, style="regular") -> None:
        from AppKit import NSMakeRect  # type: ignore

        self._bridge = bridge
        self.destroyed = False
        glass_cls = _glass_effect_view_class()
        if glass_cls is not None:
            self._view = glass_cls.alloc().initWithFrame_(
                NSMakeRect(0.0, 0.0, float(width), float(height)))
            if corner_radius:
                try:
                    self._view.setCornerRadius_(float(corner_radius))
                except Exception:  # noqa: BLE001
                    pass
            self._host = self._view.contentView()
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
            self._host = self._view
        bridge._content_view().addSubview_(self._view)
        self._logical_frame = (float(x), float(y), float(width), float(height))
        self.set_frame(x, y, width, height)

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
            self._ns.setBezeled_(False)
            self._ns.setBordered_(False)
            self._ns.setDrawsBackground_(False)
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
