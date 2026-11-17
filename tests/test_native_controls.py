"""Tests for the luvatrix native-controls feature.

Covers the platform-neutral pieces: the HDI event gate that keeps native
AppKit controls from double-firing into the scene, the null bridge used on
unsupported platforms, and the active-bridge registry. The AppKit bridge
itself only runs on macOS; here we assert it degrades safely elsewhere.
"""
from __future__ import annotations

import pytest

from luvatrix_core.core.hdi_thread import HDIEvent, HDIEventSource
from luvatrix_core.core.native_controls import (
    GatedHDIEventSource,
    NativeInputGate,
    NullNativeControlBridge,
    active_native_control_bridge,
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


# -- Fake AppKit stack for bridge-level glass tests ----------------------------


class _FakeNSView:
    def __init__(self) -> None:
        self.frame = None
        self.subviews: list = []
        self.hidden = False
        self.removed = False
        self.wants_layer = False

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

    def removeFromSuperview(self):
        self.removed = True

    def setHidden_(self, hidden):
        self.hidden = hidden

    def isHidden(self):
        return self.hidden

    def setWantsLayer_(self, wants):
        self.wants_layer = wants

    def bounds(self):
        size = type("S", (), {"width": 1280.0, "height": 800.0})()
        return type("B", (), {"size": size})()


class _FakeGlassEffectView(_FakeNSView):
    def __init__(self) -> None:
        super().__init__()
        self.corner_radius = None
        self._content = _FakeNSView()

    def setCornerRadius_(self, radius):
        self.corner_radius = radius

    def contentView(self):
        return self._content


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


def _fake_appkit_module(glass_view_cls=_FakeGlassEffectView):
    return type("AppKit", (), {
        "NSTextField": _FakeNSTextField,
        "NSSecureTextField": _FakeNSTextField,
        "NSMakeRect": lambda x, y, w, h: (x, y, w, h),
        "NSVisualEffectView": _FakeVisualEffectView,
        "NSVisualEffectMaterialSidebar": 7,
        "NSVisualEffectMaterialHUD": 10,
        "NSVisualEffectBlendingModeWithinWindow": 0,
        "NSVisualEffectStateActive": 0,
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
        assert bridge.consume_point(460.0, 430.0) is True

    def test_glass_only_points_not_consumed_and_close_destroys(self):
        bridge, handle = self._bridge(with_glass=True)
        surface = bridge.create_glass_surface(x=0, y=704, width=1280, height=96)
        # Decorative glass must not claim input: scene hit dispatch owns those.
        assert bridge.consume_point(10.0, 750.0) is False
        bridge.close()
        assert surface._view.removed is True
        assert bridge.available is False


class TestGlassEffectViewClassSelection:
    def setup_method(self):
        import luvatrix_core.platform.macos.native_controls as mac_native

        self._mac = mac_native
        mac_native._GLASS_EFFECT_VIEW_CLASS = None

    def teardown_method(self):
        self._mac._GLASS_EFFECT_VIEW_CLASS = None

    def test_prefers_ns_glass_effect_view(self):
        from unittest.mock import patch

        with patch.dict("sys.modules", {"objc": _fake_objc_module(with_glass=True)}):
            assert self._mac._glass_effect_view_class() is _FakeGlassEffectView

    def test_returns_none_below_tahoe(self):
        from unittest.mock import patch

        with patch.dict("sys.modules", {"objc": _fake_objc_module(with_glass=False)}):
            assert self._mac._glass_effect_view_class() is None
