from __future__ import annotations

from collections import deque
import sys
import types
import unittest

from luvatrix_core.platform.macos.hdi_source import MacOSWindowHDISource, _read_pressed_mouse_buttons_mask, _to_top_left_y


class MacOSHDISourceTests(unittest.TestCase):
    def test_to_top_left_y_converts_and_clamps(self) -> None:
        self.assertEqual(_to_top_left_y(99.0, 100.0), 0.0)
        self.assertEqual(_to_top_left_y(0.0, 100.0), 99.0)
        self.assertEqual(_to_top_left_y(-10.0, 100.0), 99.0)
        self.assertEqual(_to_top_left_y(1000.0, 100.0), 0.0)

    def test_poll_prefers_window_local_mouse_location(self) -> None:
        class _Size:
            width = 200.0
            height = 100.0

        class _Bounds:
            size = _Size()

        class _View:
            def bounds(self):
                return _Bounds()

            def convertPoint_fromView_(self, point, _view):
                return point

        class _Window:
            def __init__(self) -> None:
                self._view = _View()

            def contentView(self):
                return self._view

            def mouseLocationOutsideOfEventStream(self):
                return types.SimpleNamespace(x=123.0, y=40.0)

            def convertPointFromScreen_(self, point):
                return point

        fake_appkit = types.SimpleNamespace(
            NSEvent=types.SimpleNamespace(
                mouseLocation=lambda: (_ for _ in ()).throw(RuntimeError("global path should not be used"))
            )
        )

        source = object.__new__(MacOSWindowHDISource)
        source._window_handle = types.SimpleNamespace(window=_Window())
        source._next_id = 1
        source._queued_events = deque()
        source._monitor = None
        source._last_mouse_buttons_mask = 0
        source._iohid = None  # exercise NSEvent fallback path
        source._last_window_active_local = True
        prev = sys.modules.get("AppKit")
        sys.modules["AppKit"] = fake_appkit
        try:
            events = source.poll(window_active=True, ts_ns=42)
        finally:
            if prev is None:
                sys.modules.pop("AppKit", None)
            else:
                sys.modules["AppKit"] = prev

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_type, "pointer_move")
        self.assertEqual(event.status, "OK")
        self.assertIsInstance(event.payload, dict)
        payload = event.payload or {}
        self.assertAlmostEqual(float(payload.get("x", -1.0)), 123.0)
        self.assertAlmostEqual(float(payload.get("y", -1.0)), 59.0)

    def test_poll_synthesizes_click_from_pressed_buttons(self) -> None:
        class _Size:
            width = 200.0
            height = 100.0

        class _Bounds:
            size = _Size()

        class _View:
            def bounds(self):
                return _Bounds()

            def convertPoint_fromView_(self, point, _view):
                return point

        class _Window:
            def __init__(self) -> None:
                self._view = _View()

            def contentView(self):
                return self._view

            def mouseLocationOutsideOfEventStream(self):
                return types.SimpleNamespace(x=50.0, y=30.0)

            def convertPointFromScreen_(self, point):
                return point

        state = {"mask": 0}
        fake_appkit = types.SimpleNamespace(
            NSEvent=types.SimpleNamespace(
                mouseLocation=lambda: types.SimpleNamespace(x=0.0, y=0.0),
                pressedMouseButtons=lambda: state["mask"],
            )
        )

        source = object.__new__(MacOSWindowHDISource)
        source._window_handle = types.SimpleNamespace(window=_Window())
        source._next_id = 1
        source._queued_events = deque()
        source._monitor = None
        source._last_mouse_buttons_mask = 0
        source._iohid = None  # exercise NSEvent fallback path
        source._last_window_active_local = True
        prev = sys.modules.get("AppKit")
        sys.modules["AppKit"] = fake_appkit
        try:
            state["mask"] = 1
            events_down = source.poll(window_active=True, ts_ns=100)
            state["mask"] = 0
            events_up = source.poll(window_active=True, ts_ns=200)
        finally:
            if prev is None:
                sys.modules.pop("AppKit", None)
            else:
                sys.modules["AppKit"] = prev

        click_down = next(e for e in events_down if e.event_type == "click")
        click_up = next(e for e in events_up if e.event_type == "click")
        self.assertEqual(click_down.payload.get("phase"), "down")
        self.assertEqual(click_up.payload.get("phase"), "up")

    def test_read_pressed_mouse_buttons_mask_uses_nsevent_first(self) -> None:
        fake_nsevent = types.SimpleNamespace(pressedMouseButtons=lambda: 3)
        self.assertEqual(_read_pressed_mouse_buttons_mask(NSEvent=fake_nsevent), 3)

    def test_poll_uses_iohid_screen_position(self) -> None:
        """When _iohid is set, poll() emits pointer_move using IOKit screen coords."""

        class _Bounds:
            class size:
                height = 100.0

        class _View:
            def bounds(self):
                return _Bounds()

        class _Frame:
            class origin:
                x = 50.0
                y = 20.0

        class _Window:
            def contentView(self):
                return _View()

            def frame(self):
                return _Frame()

        class _FakeIOHID:
            def drain_events(self):
                return []

            def current_screen_xy(self):
                # Screen x=150, y=70 in NSEvent bottom-left coords.
                return (150.0, 70.0)

            def current_buttons_mask(self):
                return 0

        source = object.__new__(MacOSWindowHDISource)
        source._window_handle = types.SimpleNamespace(window=_Window())
        source._next_id = 1
        source._queued_events = deque()
        source._monitor = None
        source._last_mouse_buttons_mask = 0
        source._iohid = _FakeIOHID()
        source._last_window_active_local = True

        events = source.poll(window_active=True, ts_ns=99)

        move = next(e for e in events if e.event_type == "pointer_move")
        payload = move.payload or {}
        # window-local x: 150 - 50 = 100
        self.assertAlmostEqual(float(payload["x"]), 100.0)
        # window-local y (top-left): _to_top_left_y(70 - 20, 100) = _to_top_left_y(50, 100) = 49
        self.assertAlmostEqual(float(payload["y"]), 49.0)

    def test_poll_iohid_flushes_on_activation(self) -> None:
        """Events accumulated while inactive are discarded on window re-activation."""
        from luvatrix_core.core.hdi_thread import HDIEvent

        class _Bounds:
            class size:
                height = 100.0

        class _View:
            def bounds(self):
                return _Bounds()

        class _Frame:
            class origin:
                x = 0.0
                y = 0.0

        class _Window:
            def contentView(self):
                return _View()

            def frame(self):
                return _Frame()

        stale_event = HDIEvent(
            event_id=0, ts_ns=1, window_id="", device="keyboard",
            event_type="key_down", status="OK", payload={"key": "a", "code": 0},
        )

        drained = []

        class _FakeIOHID:
            def __init__(self):
                self._pending = [stale_event]

            def drain_events(self):
                out = list(self._pending)
                drained.extend(out)
                self._pending.clear()
                return out

            def calibrate_position(self, x, y):
                pass

            def current_screen_xy(self):
                return (0.0, 0.0)

            def current_buttons_mask(self):
                return 0

        fake_appkit = types.SimpleNamespace(
            NSEvent=types.SimpleNamespace(mouseLocation=lambda: types.SimpleNamespace(x=0.0, y=0.0))
        )

        source = object.__new__(MacOSWindowHDISource)
        source._window_handle = types.SimpleNamespace(window=_Window())
        source._next_id = 1
        source._queued_events = deque()
        source._monitor = None
        source._last_mouse_buttons_mask = 0
        source._iohid = _FakeIOHID()
        source._last_window_active_local = False  # was inactive

        prev = sys.modules.get("AppKit")
        sys.modules["AppKit"] = fake_appkit
        try:
            events = source.poll(window_active=True, ts_ns=1)
        finally:
            if prev is None:
                sys.modules.pop("AppKit", None)
            else:
                sys.modules["AppKit"] = prev

        # The stale keyboard event was drained-and-discarded on activation,
        # so it must not appear in the returned events.
        keyboard_events = [e for e in events if e.device == "keyboard"]
        self.assertEqual(keyboard_events, [])
        self.assertEqual(len(drained), 1)  # drain WAS called (to discard)


if __name__ == "__main__":
    unittest.main()
