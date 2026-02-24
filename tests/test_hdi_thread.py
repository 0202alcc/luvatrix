from __future__ import annotations

import time
import unittest

from luvatrix_core.core.hdi_thread import (
    HDIEvent,
    HDIEventSource,
    HDIThread,
)


class _ScriptedHDISource(HDIEventSource):
    def __init__(self, bursts: list[list[HDIEvent]]) -> None:
        self._bursts = bursts
        self._i = 0

    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        if self._i >= len(self._bursts):
            return []
        out = self._bursts[self._i]
        self._i += 1
        return out


class HDIThreadTests(unittest.TestCase):
    def test_coalesces_pointer_move_when_queue_full(self) -> None:
        source = _ScriptedHDISource(
            [
                [
                    HDIEvent(1, 1, "w", "mouse", "pointer_move", "OK", {"x": 1, "y": 1}),
                    HDIEvent(2, 2, "w", "mouse", "pointer_move", "OK", {"x": 2, "y": 2}),
                    HDIEvent(3, 3, "w", "mouse", "pointer_move", "OK", {"x": 3, "y": 3}),
                ]
            ]
        )
        thread = HDIThread(
            source=source,
            max_queue_size=2,
            poll_interval_s=0.001,
            window_geometry_provider=lambda: (0.0, 0.0, 100.0, 100.0),
        )
        thread.start()
        time.sleep(0.01)
        thread.stop()
        events = thread.poll_events(max_events=10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload, {"x": 3.0, "y": 3.0})

    def test_keyboard_transition_not_dropped_under_pointer_pressure(self) -> None:
        source = _ScriptedHDISource(
            [
                [
                    HDIEvent(1, 1, "w", "mouse", "pointer_move", "OK", {"x": 1, "y": 1}),
                    HDIEvent(2, 2, "w", "mouse", "pointer_move", "OK", {"x": 2, "y": 2}),
                    HDIEvent(3, 3, "w", "keyboard", "key_down", "OK", {"key": "a"}),
                ]
            ]
        )
        thread = HDIThread(
            source=source,
            max_queue_size=2,
            poll_interval_s=0.001,
            window_geometry_provider=lambda: (0.0, 0.0, 100.0, 100.0),
        )
        thread.start()
        time.sleep(0.01)
        thread.stop()
        events = thread.poll_events(max_events=10)
        self.assertEqual([e.event_type for e in events], ["pointer_move", "key_down"])

    def test_inactive_window_marks_pointer_not_detected(self) -> None:
        source = _ScriptedHDISource(
            [[HDIEvent(1, 1, "w", "mouse", "pointer_move", "OK", {"x": 1, "y": 2})]]
        )
        thread = HDIThread(
            source=source,
            max_queue_size=8,
            poll_interval_s=0.001,
            window_active_provider=lambda: False,
        )
        thread.start()
        time.sleep(0.01)
        thread.stop()
        events = thread.poll_events(max_events=10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].status, "NOT_DETECTED")
        self.assertIsNone(events[0].payload)

    def test_poll_max_events_is_respected(self) -> None:
        source = _ScriptedHDISource(
            [[HDIEvent(i, i, "w", "keyboard", "key_down", "OK", {"k": i}) for i in range(1, 6)]]
        )
        thread = HDIThread(source=source, max_queue_size=8, poll_interval_s=0.001)
        thread.start()
        time.sleep(0.01)
        thread.stop()
        first = thread.poll_events(max_events=2)
        second = thread.poll_events(max_events=10)
        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 3)

    def test_pointer_screen_coords_are_converted_to_window_relative(self) -> None:
        source = _ScriptedHDISource(
            [
                [
                    HDIEvent(
                        1,
                        1,
                        "w",
                        "mouse",
                        "pointer_move",
                        "OK",
                        {"screen_x": 150, "screen_y": 260, "button": 1},
                    )
                ]
            ]
        )
        thread = HDIThread(
            source=source,
            max_queue_size=8,
            poll_interval_s=0.001,
            window_geometry_provider=lambda: (100.0, 200.0, 300.0, 200.0),
        )
        thread.start()
        time.sleep(0.01)
        thread.stop()
        events = thread.poll_events(max_events=10)
        self.assertEqual(len(events), 1)
        payload = events[0].payload
        assert isinstance(payload, dict)
        self.assertEqual(payload["x"], 50.0)
        self.assertEqual(payload["y"], 60.0)
        self.assertEqual(payload["button"], 1)
        self.assertNotIn("screen_x", payload)
        self.assertNotIn("screen_y", payload)

    def test_pointer_outside_window_is_not_detected(self) -> None:
        source = _ScriptedHDISource(
            [
                [
                    HDIEvent(
                        1,
                        1,
                        "w",
                        "mouse",
                        "pointer_move",
                        "OK",
                        {"screen_x": 1000, "screen_y": 1000},
                    )
                ]
            ]
        )
        thread = HDIThread(
            source=source,
            max_queue_size=8,
            poll_interval_s=0.001,
            window_geometry_provider=lambda: (100.0, 200.0, 300.0, 200.0),
        )
        thread.start()
        time.sleep(0.01)
        thread.stop()
        events = thread.poll_events(max_events=10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].status, "NOT_DETECTED")
        self.assertIsNone(events[0].payload)

    def test_trackpad_pressure_without_coords_is_allowed_when_active(self) -> None:
        source = _ScriptedHDISource(
            [[HDIEvent(1, 1, "w", "trackpad", "pressure", "OK", {"pressure": 0.7, "stage": 2})]]
        )
        thread = HDIThread(
            source=source,
            max_queue_size=8,
            poll_interval_s=0.001,
            window_active_provider=lambda: True,
            window_geometry_provider=lambda: (0.0, 0.0, 300.0, 200.0),
        )
        thread.start()
        time.sleep(0.01)
        thread.stop()
        events = thread.poll_events(max_events=10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].status, "OK")
        payload = events[0].payload
        assert isinstance(payload, dict)
        self.assertEqual(payload["pressure"], 0.7)
        self.assertEqual(payload["stage"], 2)

    def test_trackpad_pressure_denied_when_inactive(self) -> None:
        source = _ScriptedHDISource(
            [[HDIEvent(1, 1, "w", "trackpad", "pressure", "OK", {"pressure": 0.7})]]
        )
        thread = HDIThread(
            source=source,
            max_queue_size=8,
            poll_interval_s=0.001,
            window_active_provider=lambda: False,
            window_geometry_provider=lambda: (0.0, 0.0, 300.0, 200.0),
        )
        thread.start()
        time.sleep(0.01)
        thread.stop()
        events = thread.poll_events(max_events=10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].status, "NOT_DETECTED")
        self.assertIsNone(events[0].payload)

    def test_keyboard_overflow_raises_internal_error(self) -> None:
        source = _ScriptedHDISource(
            [[HDIEvent(i, i, "w", "keyboard", "key_down", "OK", {"k": i}) for i in range(1, 4)]]
        )
        thread = HDIThread(source=source, max_queue_size=2, poll_interval_s=0.001)
        thread.start()
        time.sleep(0.01)
        thread.stop()
        self.assertIsNotNone(thread.last_error)
        self.assertIn("keyboard transitions", str(thread.last_error))


if __name__ == "__main__":
    unittest.main()
