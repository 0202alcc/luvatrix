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



if __name__ == "__main__":
    unittest.main()
