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
