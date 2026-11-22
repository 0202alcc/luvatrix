"""Tests for the luvatrix native-controls feature.

Covers the platform-neutral pieces: the HDI event gate that keeps native
AppKit controls from double-firing into the scene, the null bridge used on
unsupported platforms, and the active-bridge registry. The AppKit bridge
itself only runs on macOS; here we assert it degrades safely elsewhere.
"""
from __future__ import annotations

from collections.abc import Mapping

import pytest

from luvatrix_core.core.hdi_thread import HDIEvent, HDIEventSource
from luvatrix_core.core.native_controls import (
    GatedHDIEventSource,
    NativeControlBridge,
    NativeGlassSurface,
    NativeInputGate,
    NullNativeControlBridge,
    active_native_control_bridge,
    normalize_script_message,
    register_native_control_bridge,
    unregister_native_control_bridge,
)


def _event(device: str, event_type: str, payload: object = None, event_id: int = 1) -> HDIEvent:
    return HDIEvent(
        event_id=event_id,
        ts_ns=1,
        window_id="w",
        device=device,  # type: ignore[arg-type]
        event_type=event_type,
        status="OK",
        payload=payload,
    )


class _ScriptedSource(HDIEventSource):
    def __init__(self, events: list[HDIEvent]) -> None:
        self._events = events
        self.closed = False

    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        out, self._events = self._events, []
        return out

    def close(self) -> None:
        self.closed = True


class _FakeGate:
    def __init__(self, *, suppress: bool = False, consumed_points: set[tuple[int, int]] | None = None):
        self.suppress = suppress
        self.consumed_points = consumed_points or set()
        self.raise_error = False

    def suppress_keyboard(self) -> bool:
        if self.raise_error:
            raise RuntimeError("gate exploded")
        return self.suppress

    def consume_point(self, x: float, y: float) -> bool:
        if self.raise_error:
            raise RuntimeError("gate exploded")
        return (int(x), int(y)) in self.consumed_points


class TestGatedHDIEventSource:
    def test_keyboard_dropped_only_while_suppressed(self):
        source = _ScriptedSource([_event("keyboard", "key_down", {"key": "a"})])
        gate = _FakeGate(suppress=True)
        gated = GatedHDIEventSource(source, gate)
        assert gated.poll(True, 1) == []

        source._events = [_event("keyboard", "key_down", {"key": "a"})]
        gate.suppress = False
        assert len(gated.poll(True, 1)) == 1

    def test_clicks_dropped_only_at_consumed_points(self):
        inside = _event("mouse", "click", {"x": 100.0, "y": 200.0, "phase": "down"})
        outside = _event("mouse", "click", {"x": 300.0, "y": 200.0, "phase": "down"})
        source = _ScriptedSource([inside, outside])
        gate = _FakeGate(consumed_points={(100, 200)})
        gated = GatedHDIEventSource(source, gate)
        events = gated.poll(True, 1)
        assert [e.payload["x"] for e in events] == [300.0]

    def test_scroll_dropped_at_consumed_point(self):
        scroll = _event("trackpad", "scroll", {"x": 100.0, "y": 200.0, "delta_y": 4.0})
        source = _ScriptedSource([scroll])
        gated = GatedHDIEventSource(source, _FakeGate(consumed_points={(100, 200)}))
        assert gated.poll(True, 1) == []

    def test_pointer_move_passes_at_consumed_point(self):
        # Hover over a native control must not freeze scene hover state.
        move = _event("mouse", "pointer_move", {"x": 100.0, "y": 200.0, "buttons_mask": 0})
        source = _ScriptedSource([move])
        gated = GatedHDIEventSource(source, _FakeGate(consumed_points={(100, 200)}))
        assert len(gated.poll(True, 1)) == 1

    def test_gate_failure_is_fail_open(self):
        source = _ScriptedSource([
            _event("keyboard", "key_down", {"key": "a"}),
            _event("mouse", "click", {"x": 1.0, "y": 1.0, "phase": "down"}),
        ])
        gated = GatedHDIEventSource(source, _FakeGate())
        gated._gate.raise_error = True
        assert len(gated.poll(True, 1)) == 2

    def test_close_chains_to_source_and_gate_close_hook(self):
        source = _ScriptedSource([])
        gate = _FakeGate()
        gate.closed = False

        def _close():
            gate.closed = True

        gate.close = _close
        gated = GatedHDIEventSource(source, gate)
        gated.close()
        assert source.closed is True
        assert gate.closed is True

    def test_gate_protocol_is_structural(self):
        assert isinstance(_FakeGate(), NativeInputGate)


class TestNullBridge:
    def test_unavailable_and_stub_handles(self):
        bridge = NullNativeControlBridge()
        assert bridge.available is False
        field = bridge.create_text_field(x=1, y=2, width=3, height=4, placeholder="Client ID")
        assert field.value == ""
        field.set_value("abc")
        assert field.value == "abc"
        field.set_frame(10, 20, 100, 40)
        assert field.frame == (10, 20, 100, 40)
        field.hide()
        assert field.is_visible is False
        field.show()
        assert field.is_visible is True
        field.destroy()
        assert field.destroyed is True

    def test_gate_methods_never_consume(self):
        bridge = NullNativeControlBridge()
        assert bridge.suppress_keyboard() is False
        assert bridge.consume_point(0, 0) is False


class TestBridgeRegistry:
    def teardown_method(self):
        unregister_native_control_bridge()

    def test_empty_by_default(self):
        assert active_native_control_bridge() is None

    def test_register_and_unregister(self):
        bridge = NullNativeControlBridge()
        register_native_control_bridge(bridge)
        assert active_native_control_bridge() is bridge
        unregister_native_control_bridge()
        assert active_native_control_bridge() is None


class TestMacOSBridgeOnUnsupportedPlatforms:
    def test_wire_returns_source_unchanged_without_appkit(self):
        import luvatrix_core.platform.macos.native_controls as mac_native

        source = _ScriptedSource([])
        try:
            wired = mac_native.wire_native_controls(object(), source)
        except RuntimeError:
            pytest.fail("wire_native_controls must degrade silently off-macOS")
        assert wired is source
        assert active_native_control_bridge() is None

    def test_appkit_bridge_construction_requires_pyobjc(self):
        import luvatrix_core.platform.macos.native_controls as mac_native

        try:
            mac_native.AppKitNativeControlBridge(object())
        except RuntimeError as exc:
            assert "PyObjC" in str(exc) or "AppKit" in str(exc)
        else:
            pytest.skip("PyObjC available — construction succeeded (macOS host)")


class TestNullBridgeGlass:
    def test_glass_surface_stub(self):
        bridge = NullNativeControlBridge()
        surface = bridge.create_glass_surface(x=0, y=0, width=240, height=800,
                                              corner_radius=0.0, style="sidebar")
        assert surface.frame == (0, 0, 240, 800)
        surface.set_frame(1, 2, 3, 4)
        assert surface.frame == (1, 2, 3, 4)
        surface.hide()
        assert surface.is_visible is False
        surface.show()
        assert surface.is_visible is True
        surface.destroy()
        assert surface.destroyed is True

    def test_text_field_accepts_within_and_bordered_kwargs(self):
        bridge = NullNativeControlBridge()
        glass = bridge.create_glass_surface(x=10, y=10, width=100, height=40)
        field = bridge.create_text_field(x=10, y=10, width=100, height=40,
                                         within=glass, bordered=False)
        assert field.frame == (10, 10, 100, 40)

    def test_button_stub(self):
        bridge = NullNativeControlBridge()
        glass = bridge.create_glass_surface(x=10, y=10, width=100, height=40)
        button = bridge.create_button(x=10, y=10, width=100, height=40,
                                      title="Save", within=glass)
        assert button.frame == (10, 10, 100, 40)
        button.set_enabled(False)  # inert, must not raise
        button.destroy()
        assert button.destroyed is True

    def test_web_view_stub(self):
        bridge = NullNativeControlBridge()
        view = bridge.create_web_view(x=0, y=0, width=1280, height=800,
                                      redirect_prefix="http://127.0.0.1:8888/callback",
                                      on_redirect=lambda url: None)
        assert view.frame == (0, 0, 1280, 800)
        view.load_url("https://accounts.spotify.com/authorize?x=1")  # inert, records
        assert view.loaded_urls == ["https://accounts.spotify.com/authorize?x=1"]
        view.destroy()
        assert view.destroyed is True

    def test_web_view_stub_back_navigation_inert(self):
        bridge = NullNativeControlBridge()
        view = bridge.create_web_view(x=0, y=0, width=1280, height=800,
                                      on_navigation_state=lambda: None)
        assert view.can_go_back is False
        view.go_back()  # inert, must not raise
        view.destroy()

    def test_scripted_web_view_stub(self):
        """SL-31: the playback surface's vehicle — a web view with a script
        message channel and a JS evaluation path. The null handle stays inert
        but records, so app tests can assert on the commands that WOULD run."""
        bridge = NullNativeControlBridge()
        messages: list = []
        view = bridge.create_scripted_web_view(
            x=0, y=0, width=1, height=1,
            handler_name="luvatrixPlayer", on_message=messages.append,
            html="<html></html>")
        assert view.frame == (0, 0, 1, 1)
        assert view.handler_name == "luvatrixPlayer"
        view.evaluate_js('window.LuvatrixPlayerHost.invoke("pause", {})')
        assert view.evaluated == ['window.LuvatrixPlayerHost.invoke("pause", {})']
        view.hide()
        assert view.is_visible is False
        view.destroy()
        assert view.destroyed is True


# -- Fake AppKit stack for bridge-level glass tests ----------------------------


class _FakeCALayer:
    def __init__(self) -> None:
        self.corner_radius = None
        self.masks_to_bounds = None
        self.should_rasterize = None
        self.rasterization_scale = None

    def setCornerRadius_(self, radius):
        self.corner_radius = radius

    def setMasksToBounds_(self, value):
        self.masks_to_bounds = value

    def setShouldRasterize_(self, value):
        self.should_rasterize = value

    def setRasterizationScale_(self, scale):
        self.rasterization_scale = scale


class _FakeNSView:
    def __init__(self) -> None:
        self.frame = None
        self.subviews: list = []
        self.positioned: list = []
        self.hidden = False
        self.removed = False
        self.wants_layer = False
        self._layer = None
        self.bounds_width = 1280.0
        self.bounds_height = 800.0
        self.appearance = None

    @classmethod
    def alloc(cls):
        return cls()

    def initWithFrame_(self, frame):
        self.frame = frame
        return self

    def setFrame_(self, frame):
        self.frame = frame

    def addSubview_(self, view):
        self.subviews.append(view)

    def addSubview_positioned_relativeTo_(self, view, mode, relative):
        self.positioned.append((view, mode, relative))
        if mode == 2 and relative is not None and relative in self.subviews:
            # NSWindowBelow a sibling: land directly beneath it.
            self.subviews.insert(self.subviews.index(relative), view)
        elif relative is None and mode == 2:  # NSWindowBelow: bottom of z-order
            self.subviews.insert(0, view)
        else:
            self.subviews.append(view)

    def respondsToSelector_(self, _selector):
        return False

    def removeFromSuperview(self):
        self.removed = True

    def setHidden_(self, hidden):
        self.hidden = hidden

    def isHidden(self):
        return self.hidden

    def setWantsLayer_(self, wants):
        self.wants_layer = wants

    def layer(self):
        if self._layer is None:
            self._layer = _FakeCALayer()
        return self._layer

    def convertPoint_fromView_(self, point, _view):
        # Content view fills the window: window base coords == view coords.
        return point

    def bounds(self):
        size = type("S", (), {"width": self.bounds_width, "height": self.bounds_height})()
        return type("B", (), {"size": size})()

    def setAppearance_(self, appearance):
        self.appearance = appearance


class _FakeNSAppearance:
    """Mirrors AppKit: appearanceNamed: returns nil for unknown names."""

    def __init__(self, name) -> None:
        self.name = name

    @classmethod
    def appearanceNamed_(cls, name):
        if name == "NSAppearanceNameDarkAqua":
            return cls(name)
        return None


class _FakeGlassEffectView(_FakeNSView):
    """Mirrors real AppKit: contentView() is nil until setContentView_ is called."""

    def __init__(self) -> None:
        super().__init__()
        self.corner_radius = None
        self._content = None

    def setCornerRadius_(self, radius):
        self.corner_radius = radius

    def cornerRadius(self):
        return self.corner_radius or 0.0

    def contentView(self):
        return self._content

    def setContentView_(self, view):
        self._content = view


class _FakeVisualEffectView(_FakeNSView):
    def __init__(self) -> None:
        super().__init__()
        self.material = None
        self.blending_mode = None
        self.state = None

    def setMaterial_(self, material):
        self.material = material

    def setBlendingMode_(self, mode):
        self.blending_mode = mode

    def setState_(self, state):
        self.state = state


class _FakeNSTextField(_FakeNSView):
    def __init__(self) -> None:
        super().__init__()
        self.bezeled = None
        self.bordered = None
        self.draws_background = None
        self.focus_ring_type = None
        self.string = ""
        self.placeholder = None
        self.delegate = None
        self.target = None
        self.action = None

    def setBezeled_(self, value):
        self.bezeled = value

    def setBordered_(self, value):
        self.bordered = value

    def setBezelStyle_(self, _style):
        pass

    def setDrawsBackground_(self, value):
        self.draws_background = value

    def setFocusRingType_(self, value):
        self.focus_ring_type = value

    def setEditable_(self, _value):
        pass

    def setSelectable_(self, _value):
        pass

    def setPlaceholderString_(self, value):
        self.placeholder = value

    def setStringValue_(self, value):
        self.string = value

    def stringValue(self):
        return self.string

    def setDelegate_(self, delegate):
        self.delegate = delegate

    def setTarget_(self, target):
        self.target = target

    def setAction_(self, action):
        self.action = action

    def currentEditor(self):
        return None


class _FakeNSButton(_FakeNSView):
    def __init__(self) -> None:
        super().__init__()
        self.title = None
        self.bordered = None
        self.focus_ring_type = None
        self.button_type = None
        self.enabled = True
        self.target = None
        self.action = None
        self.content_tint = None

    def setContentTintColor_(self, color):
        self.content_tint = color

    def setTitle_(self, title):
        self.title = title

    def setBordered_(self, value):
        self.bordered = value

    def setFocusRingType_(self, value):
        self.focus_ring_type = value

    def setButtonType_(self, value):
        self.button_type = value

    def setEnabled_(self, value):
        self.enabled = bool(value)

    def isEnabled(self):
        return self.enabled

    def setTarget_(self, target):
        self.target = target

    def setAction_(self, action):
        self.action = action


class _FakeWindow:
    def __init__(self, content: _FakeNSView) -> None:
        self._content = content

    def isVisible(self):
        return True

    def contentView(self):
        return self._content

    def firstResponder(self):
        return None


class _FakeWindowHandle:
    def __init__(self) -> None:
        self.content = _FakeNSView()
        self.window = _FakeWindow(self.content)


class _FakeNSObject:
    @classmethod
    def alloc(cls):
        return cls()


class _FakeMouseEvent:
    """Left-mouse-down at a window-base point (AppKit bottom-left origin)."""

    def __init__(self, x: float, y: float) -> None:
        self._point = type("NSPoint", (), {"x": x, "y": y})()

    def locationInWindow(self):
        return self._point


def _fake_appkit_module(glass_view_cls=_FakeGlassEffectView):
    class _FakeNSEvent:
        monitors: list = []
        removed: list = []

        @classmethod
        def addLocalMonitorForEventsMatchingMask_handler_(cls, mask, handler):
            cls.monitors.append((mask, handler))
            return ("monitor", len(cls.monitors))

        @classmethod
        def removeMonitor_(cls, token):
            cls.removed.append(token)

    return type("AppKit", (), {
        "NSTextField": _FakeNSTextField,
        "NSSecureTextField": _FakeNSTextField,
        "NSMakeRect": lambda x, y, w, h: (x, y, w, h),
        "NSView": _FakeNSView,
        "NSButton": _FakeNSButton,
        "NSFocusRingTypeNone": 1,
        "NSEvent": _FakeNSEvent,
        "NSLeftMouseDownMask": 2,
        "NSWindowBelow": 2,
        "NSWindowAbove": 1,
        "NSColor": type("NSColor", (), {"whiteColor": classmethod(lambda cls: "NSColor.white")}),
        "NSVisualEffectView": _FakeVisualEffectView,
        "NSVisualEffectMaterialSidebar": 7,
        "NSVisualEffectMaterialHUD": 10,
        "NSVisualEffectMaterialUnderWindowBackground": 5,
        "NSVisualEffectBlendingModeWithinWindow": 0,
        "NSVisualEffectBlendingModeBehindWindow": 1,
        "NSVisualEffectStateActive": 0,
        "NSAppearance": _FakeNSAppearance,
        "NSAppearanceNameDarkAqua": "NSAppearanceNameDarkAqua",
    })


class _FakeNSURL:
    def __init__(self, string) -> None:
        self._string = string

    @classmethod
    def URLWithString_(cls, string):
        return cls(string)

    def absoluteString(self):
        return self._string


class _FakeNSURLRequest:
    def __init__(self, url) -> None:
        self._url = url

    @classmethod
    def requestWithURL_(cls, url):
        return cls(url)

    def URL(self):
        return self._url


class _FakeWKWebView(_FakeNSView):
    def __init__(self) -> None:
        super().__init__()
        self.navigation_delegate = None
        self.loaded_requests: list = []
        self._can_go_back = False
        self.went_back = 0
        self.kvo_observers: list = []
        self.removed_kvo: list = []

    def setNavigationDelegate_(self, delegate):
        self.navigation_delegate = delegate

    def loadRequest_(self, request):
        self.loaded_requests.append(request)

    def canGoBack(self):
        return self._can_go_back

    def goBack(self):
        self.went_back += 1

    def addObserver_forKeyPath_options_context_(self, observer, key_path, _options, _ctx):
        self.kvo_observers.append((observer, key_path))

    def removeObserver_forKeyPath_(self, observer, key_path):
        self.removed_kvo.append((observer, key_path))

    def set_can_go_back(self, value):
        """Test helper: flip history state and fire KVO like WebKit would."""
        self._can_go_back = value
        for observer, key_path in list(self.kvo_observers):
            if key_path == "canGoBack":
                observer.observeValueForKeyPath_ofObject_change_context_(
                    "canGoBack", self, {}, None)


class _FakeNavigationAction:
    def __init__(self, url: str) -> None:
        self._request = _FakeNSURLRequest(_FakeNSURL(url))

    def request(self):
        return self._request


def _fake_foundation_module():
    return type("Foundation", (), {
        "NSObject": _FakeNSObject,
        "NSURL": _FakeNSURL,
        "NSURLRequest": _FakeNSURLRequest,
    })


def _fake_objc_module(*, with_glass: bool):
    class _ObjC:
        @staticmethod
        def lookUpClass(name):
            if with_glass and name == "NSGlassEffectView":
                return _FakeGlassEffectView
            raise LookupError(name)

    return _ObjC


class TestAppKitGlassSurfaces:
    """Bridge-level glass behavior behind fake AppKit/objc modules."""

    def setup_method(self):
        import luvatrix_core.platform.macos.native_controls as mac_native

        self._mac = mac_native
        self._patchers = []
        mac_native._GLASS_EFFECT_VIEW_CLASS = None
        # The fake AppKit/objc environment simulates a macOS 26 host — the
        # resolver's version gate must see it as one.
        from unittest.mock import patch

        version = patch.object(self._mac, "_macos_major_version", lambda: 26)
        version.start()
        self._patchers.append(version)

    def teardown_method(self):
        for patcher in self._patchers:
            patcher.stop()
        self._mac._GLASS_EFFECT_VIEW_CLASS = None
        unregister_native_control_bridge()

    def _bridge(self, *, with_glass: bool):
        from unittest.mock import patch

        handle = _FakeWindowHandle()
        modules = {
            "AppKit": _fake_appkit_module(),
            "objc": _fake_objc_module(with_glass=with_glass),
            "Foundation": type("Foundation", (), {"NSObject": _FakeNSObject}),
        }
        patcher = patch.dict("sys.modules", modules)
        patcher.start()
        self._patchers.append(patcher)
        bridge = self._mac.AppKitNativeControlBridge(handle)
        return bridge, handle

    def test_glass_surface_uses_ns_glass_effect_view_when_present(self):
        bridge, handle = self._bridge(with_glass=True)
        surface = bridge.create_glass_surface(x=0, y=704, width=1280, height=96,
                                              corner_radius=0.0, style="regular")
        view = surface._view
        assert isinstance(view, _FakeGlassEffectView)
        assert view in handle.content.subviews
        # Logical top-left -> AppKit bottom-left Y-flip at 1:1 scale.
        assert view.frame == (0, 800 - 704 - 96, 1280, 96)
        assert surface.frame == (0.0, 704.0, 1280.0, 96.0)

    def test_glass_surface_falls_back_to_visual_effect_view(self):
        bridge, handle = self._bridge(with_glass=False)
        surface = bridge.create_glass_surface(x=0, y=0, width=240, height=800,
                                              corner_radius=0.0, style="sidebar")
        view = surface._view
        assert isinstance(view, _FakeVisualEffectView)
        assert view.material == 7  # NSVisualEffectMaterialSidebar
        assert view.blending_mode == 0  # WithinWindow
        assert view.state == 0  # Active
        assert view in handle.content.subviews

    def test_fallback_visual_effect_view_applies_corner_radius(self):
        """The pre-Tahoe path must round capsules too (via its layer)."""
        bridge, handle = self._bridge(with_glass=False)
        surface = bridge.create_glass_surface(x=450, y=420, width=380, height=40,
                                              corner_radius=20.0, style="regular")
        view = surface._view
        assert view.wants_layer is True
        assert view.layer().corner_radius == 20.0
        assert view.layer().masks_to_bounds is True

    def test_glass_effect_view_rounds_its_layer(self):
        """Mac round-2: NSGlassEffectView accepted setCornerRadius_ without
        error yet rendered pixel-square — the property alone does not produce
        the visible edge. The view's own layer must clip it."""
        bridge, handle = self._bridge(with_glass=True)
        surface = bridge.create_glass_surface(x=450, y=420, width=380, height=40,
                                              corner_radius=20.0, style="regular")
        view = surface._view
        assert view.corner_radius == 20.0  # property still applied
        assert view.wants_layer is True
        assert view.layer().corner_radius == 20.0
        assert view.layer().masks_to_bounds is True

    def test_glass_radius_readback_logged(self, capsys):
        """The Mac pass needs to see what the property actually held."""
        bridge, handle = self._bridge(with_glass=True)
        capsys.readouterr()  # drop the one-time path line
        bridge.create_glass_surface(x=450, y=420, width=380, height=40,
                                    corner_radius=20.0, style="regular")
        err = capsys.readouterr().err
        assert "set=20.0" in err
        assert "readback=20.0" in err

    def test_set_frame_reapplies_with_current_bounds(self):
        """Logical frame unchanged but the content view resized (e.g. window
        grew after creation): re-applying must re-derive the AppKit frame."""
        bridge, handle = self._bridge(with_glass=True)
        handle.content.bounds_height = 772.0  # 800-pt window minus title bar
        field = bridge.create_text_field(x=450, y=420, width=380, height=40,
                                         placeholder="Client ID")
        frame_small = field.ns_field.frame
        handle.content.bounds_height = 800.0
        field.set_frame(450, 420, 380, 40)  # same logical rect, fresh bounds
        frame_full = field.ns_field.frame
        assert frame_small != frame_full
        assert frame_full == (450.0, 800.0 - 420.0 - 40.0, 380.0, 40.0)

    def test_glass_surface_installs_content_view_when_absent(self):
        """NSGlassEffectView does not auto-create its contentView (probe-verified
        on macOS 26.6); the bridge must install one before parenting controls."""
        bridge, handle = self._bridge(with_glass=True)
        surface = bridge.create_glass_surface(x=450, y=420, width=380, height=40,
                                              corner_radius=20.0, style="regular")
        view = surface._view
        assert isinstance(view._content, _FakeNSView)
        assert view._content.frame == (0.0, 0.0, 380.0, 40.0)
        assert surface._content_host() is view._content

    def test_text_field_within_glass_uses_host_local_frame(self):
        bridge, handle = self._bridge(with_glass=True)
        glass = bridge.create_glass_surface(x=450, y=420, width=380, height=40,
                                            corner_radius=20.0, style="regular")
        field = bridge.create_text_field(x=450, y=420, width=380, height=40,
                                         placeholder="Client ID",
                                         within=glass, bordered=False)
        host = glass._view.contentView()
        assert field.ns_field in host.subviews
        # Parent-local frame fills the glass; window-local frame kept for the gate.
        assert field.ns_field.frame == (0.0, 0.0, 380.0, 40.0)
        assert field.frame == (450.0, 420.0, 380.0, 40.0)
        assert field.ns_field.bezeled is False
        assert field.ns_field.bordered is False
        assert field.ns_field.draws_background is False
        # Borderless glass fields suppress the accent-colored focus ring
        # (NSFocusRingTypeNone); the capsule itself is the affordance.
        assert field.ns_field.focus_ring_type == 1
        assert bridge.consume_point(460.0, 430.0) is True

    def test_bordered_field_keeps_default_focus_ring(self):
        bridge, handle = self._bridge(with_glass=True)
        field = bridge.create_text_field(x=10, y=10, width=200, height=30,
                                         placeholder="Name")
        assert field.ns_field.focus_ring_type is None  # never touched
        assert field.ns_field.bezeled is True
        assert field.ns_field.draws_background is True

    def test_glass_only_points_not_consumed_and_close_destroys(self):
        bridge, handle = self._bridge(with_glass=True)
        surface = bridge.create_glass_surface(x=0, y=704, width=1280, height=96)
        # Decorative glass must not claim input: scene hit dispatch owns those.
        assert bridge.consume_point(10.0, 750.0) is False
        bridge.close()
        assert surface._view.removed is True
        assert bridge.available is False


class TestNativeDarkAppearance:
    """SL-36 eyeball follow-up: native surfaces must pin the dark Aqua
    appearance at creation. Unpinned, NSGlassEffectView follows the default
    light appearance and renders WHITE over the near-black scene (Alec's
    screen captures: glass live, correct shape, wrong material). Every
    native view the bridge adds pins dark so the bug class cannot recur."""

    def setup_method(self):
        import luvatrix_core.platform.macos.native_controls as mac_native

        self._mac = mac_native
        self._patchers = []
        mac_native._GLASS_EFFECT_VIEW_CLASS = None
        # The fake AppKit/objc environment simulates a macOS 26 host — the
        # resolver's version gate must see it as one.
        from unittest.mock import patch

        version = patch.object(self._mac, "_macos_major_version", lambda: 26)
        version.start()
        self._patchers.append(version)

    def teardown_method(self):
        for patcher in self._patchers:
            patcher.stop()
        self._mac._GLASS_EFFECT_VIEW_CLASS = None
        unregister_native_control_bridge()

    def _bridge(self, *, with_glass: bool, with_webkit: bool = False):
        from unittest.mock import patch

        handle = _FakeWindowHandle()
        modules = {
            "AppKit": _fake_appkit_module(),
            "objc": _fake_objc_module(with_glass=with_glass),
            "Foundation": _fake_foundation_module(),
        }
        if with_webkit:
            modules["WebKit"] = type("WebKit", (), {"WKWebView": _FakeWKWebView})
        patcher = patch.dict("sys.modules", modules)
        patcher.start()
        self._patchers.append(patcher)
        bridge = self._mac.AppKitNativeControlBridge(handle)
        return bridge, handle

    def test_glass_effect_view_pins_dark_appearance(self):
        bridge, _ = self._bridge(with_glass=True)
        surface = bridge.create_glass_surface(x=0, y=704, width=1280, height=96,
                                              corner_radius=0.0, style="regular")
        appearance = surface._view.appearance
        assert appearance is not None
        assert appearance.name == "NSAppearanceNameDarkAqua"

    def test_visual_effect_fallback_pins_dark_appearance(self):
        bridge, _ = self._bridge(with_glass=False)
        surface = bridge.create_glass_surface(x=0, y=0, width=240, height=800,
                                              corner_radius=0.0, style="sidebar")
        assert isinstance(surface._view, _FakeVisualEffectView)
        appearance = surface._view.appearance
        assert appearance is not None
        assert appearance.name == "NSAppearanceNameDarkAqua"

    def test_oauth_web_view_pins_dark_appearance(self):
        bridge, _ = self._bridge(with_glass=True, with_webkit=True)
        view = bridge.create_web_view(x=0, y=0, width=1280, height=800)
        appearance = view.ns_web_view.appearance
        assert appearance is not None
        assert appearance.name == "NSAppearanceNameDarkAqua"


class TestGlassEffectResolverGate:
    """SL-36: the NSGlassEffectView runtime gate — import AppKit first, then
    resolve the class, and only on macOS 26+. The 26.6 compat probe showed a
    bare ``objc.lookUpClass`` raises nosuchclass_error because it searches
    only already-loaded classes; the gate must own the AppKit import itself
    instead of piggybacking on some earlier import, and older hosts keep the
    NSVisualEffectView fallback."""

    def setup_method(self):
        import luvatrix_core.platform.macos.native_controls as mac_native

        self._mac = mac_native
        mac_native._GLASS_EFFECT_VIEW_CLASS = None

    def teardown_method(self):
        self._mac._GLASS_EFFECT_VIEW_CLASS = None

    def _resolve(self, *, with_appkit: bool, with_glass: bool, major):
        from unittest.mock import patch

        modules = {"objc": _fake_objc_module(with_glass=with_glass)}
        # None in sys.modules forces ImportError on `import AppKit` — the
        # off-mac / missing-extra path — even if something imported it earlier.
        modules["AppKit"] = _fake_appkit_module() if with_appkit else None
        with patch.dict("sys.modules", modules):
            with patch.object(self._mac, "_macos_major_version", lambda: major):
                return self._mac._glass_effect_view_class()

    def test_resolves_on_macos_26_with_appkit(self):
        assert self._resolve(with_appkit=True, with_glass=True, major=26) is _FakeGlassEffectView

    def test_appkit_import_is_mandatory(self):
        """A bare lookUpClass must never count as resolution: without an
        AppKit import the class may simply not be loaded yet."""
        assert self._resolve(with_appkit=False, with_glass=True, major=26) is None

    def test_macos_version_gate(self):
        assert self._resolve(with_appkit=True, with_glass=True, major=15) is None
        assert self._resolve(with_appkit=True, with_glass=True, major=None) is None

    def test_missing_class_stays_fallback(self):
        assert self._resolve(with_appkit=True, with_glass=False, major=26) is None

    def test_macos_major_version_parsing(self):
        from unittest.mock import patch

        with patch("platform.mac_ver", return_value=("26.6", ("", "", ""), "25G72")):
            assert self._mac._macos_major_version() == 26
        with patch("platform.mac_ver", return_value=("15.7.1", ("", "", ""), "24G90")):
            assert self._mac._macos_major_version() == 15
        with patch("platform.mac_ver", return_value=("", ("", "", ""), "")):
            assert self._mac._macos_major_version() is None


class TestAppKitUnderGlassPlacement:
    """SL-36: glass BELOW the render surface — the pill's Liquid Glass plate
    sits under the Metal-drawn content so scene glyphs stay crisp on top."""

    def setup_method(self):
        import luvatrix_core.platform.macos.native_controls as mac_native

        self._mac = mac_native
        self._patchers = []
        mac_native._GLASS_EFFECT_VIEW_CLASS = None
        # Fake AppKit/objc environment == macOS 26 host for the version gate.
        from unittest.mock import patch

        version = patch.object(self._mac, "_macos_major_version", lambda: 26)
        version.start()
        self._patchers.append(version)

    def teardown_method(self):
        for patcher in self._patchers:
            patcher.stop()
        self._mac._GLASS_EFFECT_VIEW_CLASS = None
        unregister_native_control_bridge()

    def _bridge(self, *, capable: bool):
        from unittest.mock import patch

        handle = _FakeWindowHandle()
        handle.render_view = _FakeNSView() if capable else None
        handle.under_glass_capable = capable
        if capable:
            handle.content.addSubview_(handle.render_view)
        modules = {
            "AppKit": _fake_appkit_module(),
            "objc": _fake_objc_module(with_glass=True),
            "Foundation": type("Foundation", (), {"NSObject": _FakeNSObject}),
        }
        patcher = patch.dict("sys.modules", modules)
        patcher.start()
        self._patchers.append(patcher)
        bridge = self._mac.AppKitNativeControlBridge(handle)
        return bridge, handle

    def test_supports_under_glass_reflects_handle_capability(self):
        bridge, _ = self._bridge(capable=True)
        assert bridge.supports_under_glass is True
        bridge2, _ = self._bridge(capable=False)
        assert bridge2.supports_under_glass is False

    def test_under_placement_inserts_below_render_view(self):
        bridge, handle = self._bridge(capable=True)
        surface = bridge.create_glass_surface(x=100, y=20, width=400, height=84,
                                              corner_radius=18.0, placement="under")
        view = surface._view
        below = [p for p in handle.content.positioned
                 if p[0] is view and p[1] == 2 and p[2] is handle.render_view]
        assert below, "under-glass must insert NSWindowBelow the render view"
        assert (handle.content.subviews.index(view)
                < handle.content.subviews.index(handle.render_view))

    def test_above_placement_remains_default(self):
        bridge, handle = self._bridge(capable=True)
        surface = bridge.create_glass_surface(x=0, y=0, width=100, height=40)
        assert handle.content.subviews[-1] is surface._view
        assert [p for p in handle.content.positioned if p[0] is surface._view] == []

    def test_under_placement_requires_capable_handle(self):
        bridge, _ = self._bridge(capable=False)
        with pytest.raises(RuntimeError, match="under"):
            bridge.create_glass_surface(x=0, y=0, width=100, height=40,
                                        placement="under")

    def test_glass_surface_corner_radius_updates(self):
        bridge, _ = self._bridge(capable=True)
        surface = bridge.create_glass_surface(x=0, y=0, width=100, height=40,
                                              corner_radius=0.0, placement="under")
        surface.set_corner_radius(21.0)
        assert surface._view.corner_radius == 21.0
        assert surface._view.layer().corner_radius == 21.0
        assert surface._view.layer().masks_to_bounds is True


class TestAppKitWindowBackdrop:
    """SL-38: one window-spanning behind-window material — the whole window is
    glass, not just the pill. Always an NSVisualEffectView (the
    NSGlassEffectView idiom is a foreground effect, not a window backdrop)
    with under-window blending, dark-pinned, at the very back of the content
    view so scene content and the pill's own glass composite above it."""

    def setup_method(self):
        import luvatrix_core.platform.macos.native_controls as mac_native

        self._mac = mac_native
        self._patchers = []
        mac_native._GLASS_EFFECT_VIEW_CLASS = None
        from unittest.mock import patch

        version = patch.object(self._mac, "_macos_major_version", lambda: 26)
        version.start()
        self._patchers.append(version)

    def teardown_method(self):
        for patcher in self._patchers:
            patcher.stop()
        self._mac._GLASS_EFFECT_VIEW_CLASS = None
        unregister_native_control_bridge()

    def _bridge(self, *, capable: bool):
        from unittest.mock import patch

        handle = _FakeWindowHandle()
        handle.render_view = _FakeNSView() if capable else None
        handle.under_glass_capable = capable
        if capable:
            handle.content.addSubview_(handle.render_view)
        modules = {
            "AppKit": _fake_appkit_module(),
            "objc": _fake_objc_module(with_glass=True),
            "Foundation": type("Foundation", (), {"NSObject": _FakeNSObject}),
        }
        patcher = patch.dict("sys.modules", modules)
        patcher.start()
        self._patchers.append(patcher)
        bridge = self._mac.AppKitNativeControlBridge(handle)
        return bridge, handle

    def test_backdrop_is_visual_effect_view_even_on_tahoe(self):
        bridge, _ = self._bridge(capable=True)
        surface = bridge.create_glass_surface(x=0, y=0, width=1280, height=800,
                                              placement="backdrop")
        assert isinstance(surface._view, _FakeVisualEffectView)
        assert not isinstance(surface._view, _FakeGlassEffectView)

    def test_backdrop_material_blending_state(self):
        bridge, _ = self._bridge(capable=True)
        surface = bridge.create_glass_surface(x=0, y=0, width=1280, height=800,
                                              placement="backdrop")
        view = surface._view
        assert view.material == 5  # NSVisualEffectMaterialUnderWindowBackground
        assert view.blending_mode == 1  # NSVisualEffectBlendingModeBehindWindow
        assert view.state == 0  # NSVisualEffectStateActive

    def test_backdrop_inserts_at_very_back(self):
        bridge, handle = self._bridge(capable=True)
        surface = bridge.create_glass_surface(x=0, y=0, width=1280, height=800,
                                              placement="backdrop")
        view = surface._view
        below_nil = [p for p in handle.content.positioned
                     if p[0] is view and p[1] == 2 and p[2] is None]
        assert below_nil, "window backdrop must insert NSWindowBelow nil (very back)"
        assert handle.content.subviews.index(view) == 0
        assert (handle.content.subviews.index(view)
                < handle.content.subviews.index(handle.render_view))

    def test_backdrop_pins_dark_appearance(self):
        bridge, _ = self._bridge(capable=True)
        surface = bridge.create_glass_surface(x=0, y=0, width=1280, height=800,
                                              placement="backdrop")
        assert surface._view.appearance is not None
        assert surface._view.appearance.name == "NSAppearanceNameDarkAqua"

    def test_backdrop_tracks_frame_and_destroys(self):
        bridge, _ = self._bridge(capable=True)
        surface = bridge.create_glass_surface(x=0, y=0, width=1280, height=800,
                                              placement="backdrop")
        assert surface._view.frame == (0, 0, 1280, 800)
        surface.set_frame(0, 0, 1000, 700)
        # Y-flip at 1:1 scale against the fake content view's 800pt bounds.
        assert surface._view.frame == (0, 100, 1000, 700)
        assert surface.frame == (0.0, 0.0, 1000.0, 700.0)
        surface.destroy()
        assert surface._view.removed is True

    def test_backdrop_requires_under_glass_capability(self):
        """The backdrop only reads through a see-through window — same gate
        as the pill's under-glass placement."""
        bridge, _ = self._bridge(capable=False)
        with pytest.raises(RuntimeError, match="backdrop"):
            bridge.create_glass_surface(x=0, y=0, width=100, height=40,
                                        placement="backdrop")

    def test_rasterize_hint_off_by_default(self):
        """SL-41 A/B lever stays inert unless the runner opts in — the
        default build composites the behind-window material live."""
        bridge, _ = self._bridge(capable=True)
        surface = bridge.create_glass_surface(x=0, y=0, width=1280, height=800,
                                              placement="backdrop")
        assert not surface._view.wants_layer
        layer = surface._view._layer
        assert layer is None or not layer.should_rasterize

    def test_rasterize_hint_caches_the_backdrop_effect_when_enabled(self, monkeypatch):
        """SL-41: LUVATRIX_VEV_RASTERIZE=1 asks CA to cache the material's
        rendered effect as a bitmap — while the window is stationary the
        desktop behind it doesn't change, so the per-present recomposite can
        drop to a texture re-blit. Scale must track the backing factor or the
        cached blur goes soft."""
        monkeypatch.setenv("LUVATRIX_VEV_RASTERIZE", "1")
        bridge, _ = self._bridge(capable=True)
        surface = bridge.create_glass_surface(x=0, y=0, width=1280, height=800,
                                              placement="backdrop")
        assert surface._view.wants_layer is True
        layer = surface._view.layer()
        assert layer.should_rasterize is True
        assert layer.rasterization_scale is not None
        assert layer.rasterization_scale >= 1.0

    def test_rasterize_hint_leaves_foreground_placements_alone(self, monkeypatch):
        """Only the window-spanning backdrop recomposites the desktop blur;
        the pill's own glass must not grow a cache knob it never needed."""
        monkeypatch.setenv("LUVATRIX_VEV_RASTERIZE", "1")
        bridge, _ = self._bridge(capable=True)
        surface = bridge.create_glass_surface(x=100, y=20, width=400, height=84,
                                              corner_radius=18.0, placement="under")
        layer = surface._view._layer
        assert layer is None or not layer.should_rasterize


class TestUnderGlassContract:
    """Platform-neutral under-glass contract: the null bridge carries the
    knobs so headless apps can exercise the same code paths."""

    def test_null_bridge_records_placement_and_radius(self):
        bridge = NullNativeControlBridge()
        assert bridge.supports_under_glass is False
        surface = bridge.create_glass_surface(x=0, y=0, width=100, height=40,
                                              placement="under")
        assert surface.placement == "under"
        surface.set_corner_radius(12.0)
        assert surface.corner_radius == 12.0

    def test_null_glass_defaults_to_above(self):
        bridge = NullNativeControlBridge()
        surface = bridge.create_glass_surface(x=0, y=0, width=100, height=40)
        assert surface.placement == "above"
        assert surface.corner_radius == 0.0

    def test_null_bridge_records_backdrop_placement(self):
        """Headless hosts carry the SL-38 window-backdrop knob so app code
        exercises the same sync path without a native window."""
        bridge = NullNativeControlBridge()
        surface = bridge.create_glass_surface(x=0, y=0, width=1280, height=800,
                                              placement="backdrop")
        assert surface.placement == "backdrop"
        surface.set_frame(0, 0, 1000, 700)
        assert surface.frame == (0, 0, 1000, 700)

    def test_protocol_exposes_corner_radius_and_capability(self):
        assert hasattr(NativeGlassSurface, "set_corner_radius")
        assert hasattr(NativeControlBridge, "supports_under_glass")


class TestAppKitNativeButtons:
    """Borderless NSButton on a glass capsule — the auth-wall CTA pattern."""

    def test_button_title_tinted_white(self):
        """A borderless button's title defaults to controlTextColor — black in
        light mode, invisible over the dark login page. Pin a light tint so
        the affordance cannot disappear."""
        bridge, handle = self._bridge()
        button = bridge.create_button(x=1174, y=16, width=90, height=36,
                                      title="Cancel", on_press=lambda: None)
        assert button._ns.content_tint == "NSColor.white"

    def setup_method(self):
        import luvatrix_core.platform.macos.native_controls as mac_native

        self._mac = mac_native
        self._patchers = []
        mac_native._GLASS_EFFECT_VIEW_CLASS = None
        # Fake AppKit/objc environment == macOS 26 host for the version gate.
        from unittest.mock import patch

        version = patch.object(self._mac, "_macos_major_version", lambda: 26)
        version.start()
        self._patchers.append(version)

    def teardown_method(self):
        for patcher in self._patchers:
            patcher.stop()
        self._mac._GLASS_EFFECT_VIEW_CLASS = None
        unregister_native_control_bridge()

    def _bridge(self, *, with_glass: bool = True):
        from unittest.mock import patch

        handle = _FakeWindowHandle()
        modules = {
            "AppKit": _fake_appkit_module(),
            "objc": _fake_objc_module(with_glass=with_glass),
            "Foundation": type("Foundation", (), {"NSObject": _FakeNSObject}),
        }
        patcher = patch.dict("sys.modules", modules)
        patcher.start()
        self._patchers.append(patcher)
        bridge = self._mac.AppKitNativeControlBridge(handle)
        return bridge, handle

    def test_button_within_glass_borderless_no_focus_ring(self):
        bridge, handle = self._bridge()
        capsule = bridge.create_glass_surface(x=580, y=476, width=120, height=40,
                                              corner_radius=20.0, style="regular")
        button = bridge.create_button(x=580, y=476, width=120, height=40,
                                      title="Save", within=capsule, on_press=lambda: None)
        ns = button.ns_button
        assert isinstance(ns, _FakeNSButton)
        assert ns.title == "Save"
        assert ns.bordered is False
        assert ns.focus_ring_type == 1  # NSFocusRingTypeNone
        host = capsule._view.contentView()
        assert ns in host.subviews
        # Parent-local frame fills the capsule; window-local frame kept for the gate.
        assert ns.frame == (0.0, 0.0, 120.0, 40.0)
        assert button.frame == (580.0, 476.0, 120.0, 40.0)

    def test_button_press_invokes_on_press(self):
        bridge, handle = self._bridge()
        pressed = []
        button = bridge.create_button(x=0, y=0, width=100, height=40,
                                      title="Go", on_press=lambda: pressed.append(True))
        ns = button.ns_button
        assert ns.target is not None and ns.action == "onButtonPress:"
        getattr(ns.target, ns.action.replace(":", "_"))(ns)
        assert pressed == [True]

    def test_button_set_enabled(self):
        bridge, handle = self._bridge()
        button = bridge.create_button(x=0, y=0, width=100, height=40, title="Go")
        assert button.ns_button.isEnabled() is True
        button.set_enabled(False)
        assert button.ns_button.isEnabled() is False
        button.set_enabled(True)
        assert button.ns_button.isEnabled() is True

    def test_button_points_consumed_and_close_destroys(self):
        bridge, handle = self._bridge()
        button = bridge.create_button(x=580, y=476, width=120, height=40, title="Save")
        assert bridge.consume_point(600.0, 490.0) is True
        assert bridge.consume_point(10.0, 10.0) is False
        bridge.close()
        assert button.ns_button.removed is True

    def test_button_without_glass_parents_to_content_view(self):
        bridge, handle = self._bridge()
        button = bridge.create_button(x=10, y=10, width=100, height=40, title="Plain")
        assert button.ns_button in handle.content.subviews
        # Window-local frame with Y-flip at 1:1 scale (content height 800).
        assert button.ns_button.frame == (10.0, 800 - 10 - 40, 100.0, 40.0)


class TestAppKitWebViews:
    """Embedded WKWebView for OAuth: load, redirect intercept, dismiss."""

    def setup_method(self):
        import luvatrix_core.platform.macos.native_controls as mac_native

        self._mac = mac_native
        self._patchers = []
        mac_native._GLASS_EFFECT_VIEW_CLASS = None

    def teardown_method(self):
        for patcher in self._patchers:
            patcher.stop()
        self._mac._GLASS_EFFECT_VIEW_CLASS = None
        unregister_native_control_bridge()

    def _bridge(self, *, with_webkit: bool = True):
        from unittest.mock import patch

        handle = _FakeWindowHandle()
        modules = {
            "AppKit": _fake_appkit_module(),
            "objc": _fake_objc_module(with_glass=True),
            "Foundation": _fake_foundation_module(),
        }
        if with_webkit:
            modules["WebKit"] = type("WebKit", (), {"WKWebView": _FakeWKWebView})
        self.appkit = modules["AppKit"]
        patcher = patch.dict("sys.modules", modules)
        patcher.start()
        self._patchers.append(patcher)
        bridge = self._mac.AppKitNativeControlBridge(handle)
        return bridge, handle

    def _monitor(self):
        monitors = self.appkit.NSEvent.monitors
        assert len(monitors) == 1
        mask, handler = monitors[0]
        assert mask == 2  # NSLeftMouseDownMask
        return handler

    def test_load_url_builds_and_loads_request(self):
        bridge, handle = self._bridge()
        view = bridge.create_web_view(x=0, y=0, width=1280, height=800)
        url = "https://accounts.spotify.com/authorize?client_id=cid"
        view.load_url(url)
        assert view in bridge._web_views
        requests = view.ns_web_view.loaded_requests
        assert len(requests) == 1
        assert requests[0].URL().absoluteString() == url
        assert view.ns_web_view in handle.content.subviews

    def test_redirect_matching_prefix_cancels_and_reports(self):
        bridge, _ = self._bridge()
        seen = []
        view = bridge.create_web_view(
            x=0, y=0, width=1280, height=800,
            redirect_prefix="http://127.0.0.1:8888/callback",
            on_redirect=seen.append)
        delegate = view.ns_web_view.navigation_delegate
        assert delegate is not None
        policies = []
        callback_url = "http://127.0.0.1:8888/callback?code=abc&state=s"
        delegate.webView_decidePolicyForNavigationAction_decisionHandler_(
            view.ns_web_view, _FakeNavigationAction(callback_url), policies.append)
        assert policies == [0]  # WKNavigationActionPolicyCancel
        assert seen == [callback_url]

    def test_non_matching_navigation_allows(self):
        bridge, _ = self._bridge()
        seen = []
        view = bridge.create_web_view(
            x=0, y=0, width=1280, height=800,
            redirect_prefix="http://127.0.0.1:8888/callback",
            on_redirect=seen.append)
        delegate = view.ns_web_view.navigation_delegate
        policies = []
        delegate.webView_decidePolicyForNavigationAction_decisionHandler_(
            view.ns_web_view,
            _FakeNavigationAction("https://accounts.spotify.com/login"),
            policies.append)
        assert policies == [1]  # WKNavigationActionPolicyAllow
        assert seen == []

    def test_web_view_consumes_points_and_suppresses_keyboard(self):
        bridge, _ = self._bridge()
        view = bridge.create_web_view(x=0, y=0, width=1280, height=800)
        assert bridge.consume_point(640.0, 400.0) is True
        # Typing into Spotify's form must not leak to app shortcuts.
        assert bridge.suppress_keyboard() is True
        view.destroy()
        assert view.ns_web_view.removed is True
        assert bridge.consume_point(640.0, 400.0) is False
        assert bridge.suppress_keyboard() is False

    def test_create_web_view_without_webkit_raises_actionable(self):
        bridge, _ = self._bridge(with_webkit=False)
        with pytest.raises(RuntimeError, match="pyobjc-framework-WebKit"):
            bridge.create_web_view(x=0, y=0, width=100, height=100)

    # -- back navigation --------------------------------------------------------

    def test_can_go_back_and_go_back(self):
        """The sheet's Back button reads canGoBack (via KVO-driven refresh)
        and presses through to WKWebView.goBack."""
        bridge, handle = self._bridge()
        states = []
        view = bridge.create_web_view(
            x=0, y=0, width=1280, height=800,
            on_navigation_state=lambda: states.append(view.can_go_back))
        assert view.can_go_back is False
        view._wk.set_can_go_back(True)
        assert view.can_go_back is True
        assert states == [True]  # KVO change notified the app callback
        view.go_back()
        assert view._wk.went_back == 1

    def test_kvo_observer_removed_on_destroy(self):
        """A leaked KVO observer crashes the process on the next notification."""
        bridge, handle = self._bridge()
        view = bridge.create_web_view(x=0, y=0, width=1280, height=800,
                                      on_navigation_state=lambda: None)
        view.destroy()
        assert len(view._wk.removed_kvo) == 1
        assert view._wk.removed_kvo[0][1] == "canGoBack"

    def test_monitor_routes_top_left_back_button(self):
        """The Back button sits top-LEFT (Cancel is top-right); the monitor
        must route its clicks the same way."""
        bridge, handle = self._bridge()
        fired = []
        view = bridge.create_web_view(x=0, y=0, width=1280, height=800)
        button = bridge.create_button(x=16, y=16, width=90, height=36,
                                      title="Back", on_press=lambda: fired.append(True))
        handler = self._monitor()
        event = _FakeMouseEvent(61, 800 - 34)  # Back frame center
        assert handler(event) is None
        assert fired == [True]

    # -- button event routing while a web view is live --------------------------
    # WKWebView's remote layer tree can win AppKit hit-testing over siblings on
    # the CAMetalLayer-hosted content view (Cancel never fired on the Mac
    # build). While a web view is live, the bridge routes left-mouse-downs to
    # native buttons through an NSEvent monitor instead of view hit-testing.

    def test_mousedown_inside_button_fires_and_swallows(self):
        bridge, handle = self._bridge()
        fired = []
        view = bridge.create_web_view(x=0, y=0, width=1280, height=800)
        button = bridge.create_button(x=1174, y=16, width=90, height=36,
                                      title="Cancel", on_press=lambda: fired.append(True))
        handler = self._monitor()
        # Button center (1219, 34) logical top-left -> window base y = 800-34.
        event = _FakeMouseEvent(1219, 800 - 34)
        assert handler(event) is None  # swallowed: the page must not see it
        assert fired == [True]

    def test_mousedown_outside_button_passes_through(self):
        bridge, handle = self._bridge()
        fired = []
        view = bridge.create_web_view(x=0, y=0, width=1280, height=800)
        button = bridge.create_button(x=1174, y=16, width=90, height=36,
                                      title="Cancel", on_press=lambda: fired.append(True))
        handler = self._monitor()
        event = _FakeMouseEvent(640, 400)
        assert handler(event) is event
        assert fired == []

    def test_mousedown_on_disabled_button_passes_through(self):
        bridge, handle = self._bridge()
        fired = []
        view = bridge.create_web_view(x=0, y=0, width=1280, height=800)
        button = bridge.create_button(x=1174, y=16, width=90, height=36,
                                      title="Cancel", on_press=lambda: fired.append(True))
        button.set_enabled(False)
        handler = self._monitor()
        event = _FakeMouseEvent(1219, 800 - 34)
        assert handler(event) is event
        assert fired == []

    def test_monitor_removed_when_last_web_view_destroyed(self):
        bridge, handle = self._bridge()
        first_appkit = self.appkit
        view = bridge.create_web_view(x=0, y=0, width=1280, height=800)
        assert len(first_appkit.NSEvent.monitors) == 1
        view.destroy()
        assert len(first_appkit.NSEvent.removed) == 1
        # No monitor installed until a web view exists.
        bridge2, handle2 = self._bridge()
        assert len(self.appkit.NSEvent.monitors) == 0
        assert len(first_appkit.NSEvent.monitors) == 1  # still just the first

    def test_web_view_inserts_below_native_buttons(self):
        """Mac round-2: the compositing WKWebView can obscure sibling native
        controls on the layer tree (Cancel never visibly rendered). Web views
        must insert at the bottom of the z-order so controls composite above."""
        bridge, handle = self._bridge()
        button = bridge.create_button(x=1174, y=16, width=90, height=36,
                                      title="Cancel", on_press=lambda: None)
        view = bridge.create_web_view(x=0, y=0, width=1280, height=800)
        subs = handle.content.subviews
        assert subs.index(view._wk) < subs.index(button._ns)

    def test_create_button_logs_completion(self, capsys):
        """Disambiguates 'create_button threw' from 'button not matched' on the
        Mac pass (stdout is block-buffered when piped — must be stderr)."""
        bridge, handle = self._bridge()
        capsys.readouterr()
        bridge.create_button(x=1174, y=16, width=90, height=36,
                             title="Cancel", on_press=lambda: None)
        err = capsys.readouterr().err
        assert "Cancel" in err
        assert "1174.0" in err

    def test_button_monitor_logs_install_and_route(self, capsys):
        bridge, handle = self._bridge()
        fired = []
        view = bridge.create_web_view(x=0, y=0, width=1280, height=800)
        button = bridge.create_button(x=1174, y=16, width=90, height=36,
                                      title="Cancel", on_press=lambda: fired.append(True))
        err = capsys.readouterr().err
        assert "button monitor installed" in err
        handler = self._monitor()
        handler(_FakeMouseEvent(1219, 800 - 34))
        err = capsys.readouterr().err
        assert "match" in err and "Cancel" in err
        assert fired == [True]


class TestGlassEffectViewClassSelection:
    def setup_method(self):
        import luvatrix_core.platform.macos.native_controls as mac_native

        self._mac = mac_native
        mac_native._GLASS_EFFECT_VIEW_CLASS = None

    def teardown_method(self):
        self._mac._GLASS_EFFECT_VIEW_CLASS = None

    def test_prefers_ns_glass_effect_view(self):
        from unittest.mock import patch

        modules = {"objc": _fake_objc_module(with_glass=True),
                   "AppKit": _fake_appkit_module()}
        with patch.dict("sys.modules", modules):
            with patch.object(self._mac, "_macos_major_version", lambda: 26):
                assert self._mac._glass_effect_view_class() is _FakeGlassEffectView

    def test_returns_none_below_tahoe(self):
        from unittest.mock import patch

        # Pre-Tahoe host: the version gate holds the fallback even when the
        # class symbol happens to resolve.
        modules = {"objc": _fake_objc_module(with_glass=True),
                   "AppKit": _fake_appkit_module()}
        with patch.dict("sys.modules", modules):
            with patch.object(self._mac, "_macos_major_version", lambda: 15):
                assert self._mac._glass_effect_view_class() is None


class _NsDictLike(Mapping):
    """PyObjC __NSDictionaryM stand-in: a Mapping that is NOT a dict —
    isinstance(x, dict) is False, exactly the wire shape that broke live."""

    def __init__(self, data):
        self._data = dict(data)

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)


class _NsNumberLike:
    """PyObjC NSNumber duck-type: answers doubleValue, is not an int."""

    def __init__(self, value):
        self._value = float(value)

    def doubleValue(self):
        return self._value


class TestNormalizeScriptMessage:
    """The boundary converter: WKScriptMessage bodies arrive as __NSDictionaryM
    /__NSArrayM/NSNumber/NSNull — none pass isinstance(dict/list/int), and every
    consumer gates on those checks (the round-47 live break)."""

    def test_primitives_pass_through(self):
        assert normalize_script_message("s") == "s"
        assert normalize_script_message(7) == 7
        assert normalize_script_message(0.5) == 0.5
        assert normalize_script_message(True) is True
        assert normalize_script_message(None) is None

    def test_nsdict_like_deep_converts(self):
        body = _NsDictLike({
            "type": "player_state_changed",
            "payload": _NsDictLike({"paused": 1, "track": _NsDictLike({"name": "T"})}),
        })
        out = normalize_script_message(body)
        assert type(out) is dict
        assert type(out["payload"]) is dict
        assert type(out["payload"]["track"]) is dict
        assert out["payload"]["track"]["name"] == "T"

    def test_nsarray_like_converts_to_list(self):
        body = _NsDictLike({"items": ("a", "b")})
        out = normalize_script_message(body)
        assert out["items"] == ["a", "b"]
        assert type(out["items"]) is list

    def test_nsnull_maps_to_none(self):
        nsnull = type("NSNull", (), {})()
        assert normalize_script_message(_NsDictLike({"track": nsnull}))["track"] is None

    def test_nsnumber_maps_to_int_or_float(self):
        out = normalize_script_message(_NsDictLike({
            "position_ms": _NsNumberLike(61000),
            "volume": _NsNumberLike(0.5),
        }))
        assert out["position_ms"] == 61000 and type(out["position_ms"]) is int
        assert out["volume"] == 0.5 and type(out["volume"]) is float

    def test_plain_dicts_untouched_in_content(self):
        body = {"type": "ready", "payload": {"device_id": "d1"}}
        assert normalize_script_message(body) == body


class TestReceiveMessageBoundary:
    """_receive_message is the real boundary: the inverted isinstance guard
    passed __NSDictionaryM through untouched. Constructed without AppKit —
    _receive_message only needs _on_message and destroyed."""

    def test_nsdict_like_body_arrives_as_plain_data(self):
        from luvatrix_core.platform.macos.native_controls import _AppKitScriptedWebView

        view = object.__new__(_AppKitScriptedWebView)
        received = []
        view._on_message = received.append
        view.destroyed = False
        view._receive_message(_NsDictLike({
            "type": "host_ready",
            "payload": _NsDictLike({"n": _NsNumberLike(3)}),
        }))
        assert len(received) == 1
        message = received[0]
        assert type(message) is dict
        assert type(message["payload"]) is dict
        assert message == {"type": "host_ready", "payload": {"n": 3}}
