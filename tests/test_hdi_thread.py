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
        self.assertEqual([e.event_type for e in events], ["pointer_move", "press"])
        payload = events[1].payload
        assert isinstance(payload, dict)
        self.assertEqual(payload.get("phase"), "down")

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

    def test_pointer_coords_are_projected_to_target_extent(self) -> None:
        source = _ScriptedHDISource(
            [[HDIEvent(1, 1, "w", "mouse", "pointer_move", "OK", {"x": 199.0, "y": 99.0})]]
        )
        thread = HDIThread(
            source=source,
            max_queue_size=8,
            poll_interval_s=0.001,
            window_geometry_provider=lambda: (0.0, 0.0, 200.0, 100.0),
            target_extent_provider=lambda: (100.0, 50.0),
        )
        thread.start()
        time.sleep(0.01)
        thread.stop()
        events = thread.poll_events(max_events=10)
        self.assertEqual(len(events), 1)
        payload = events[0].payload
        assert isinstance(payload, dict)
        self.assertAlmostEqual(payload["x"], 99.0, places=4)
        self.assertAlmostEqual(payload["y"], 49.0, places=4)

    def test_pointer_in_letterbox_region_is_not_detected(self) -> None:
        source = _ScriptedHDISource(
            [[HDIEvent(1, 1, "w", "mouse", "pointer_move", "OK", {"x": 10.0, "y": 10.0})]]
        )
        thread = HDIThread(
            source=source,
            max_queue_size=8,
            poll_interval_s=0.001,
            window_geometry_provider=lambda: (0.0, 0.0, 300.0, 200.0),
            target_extent_provider=lambda: (100.0, 100.0),
            source_content_rect_provider=lambda: (50.0, 20.0, 200.0, 160.0),
        )
        thread.start()
        time.sleep(0.01)
        thread.stop()
        events = thread.poll_events(max_events=10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].status, "NOT_DETECTED")
        self.assertIsNone(events[0].payload)

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

    def test_keyboard_up_generates_press_release_and_single(self) -> None:
        source = _ScriptedHDISource(
            [
                [
                    HDIEvent(1, 1, "w", "keyboard", "key_down", "OK", {"key": "a"}),
                    HDIEvent(2, 2, "w", "keyboard", "key_up", "OK", {"key": "a"}),
                ]
            ]
        )
        thread = HDIThread(source=source, poll_interval_s=0.001)
        thread.start()
        time.sleep(0.01)
        thread.stop()
        events = thread.poll_events(max_events=10)
        press_phases = [
            e.payload.get("phase")
            for e in events
            if e.device == "keyboard" and e.event_type == "press" and isinstance(e.payload, dict)
        ]
        self.assertIn("down", press_phases)
        self.assertIn("up", press_phases)
        self.assertIn("single", press_phases)

    def test_tab_key_is_not_normalized_to_cancel(self) -> None:
        source = _ScriptedHDISource(
            [
                [
                    HDIEvent(1, 1, "w", "keyboard", "key_down", "OK", {"key": "\t", "code": 48}),
                    HDIEvent(2, 2, "w", "keyboard", "key_up", "OK", {"key": "\t", "code": 48}),
                ]
            ]
        )
        thread = HDIThread(source=source, poll_interval_s=0.001)
        thread.start()
        time.sleep(0.01)
        thread.stop()
        events = thread.poll_events(max_events=10)
        press_events = [
            e
            for e in events
            if e.device == "keyboard" and e.event_type == "press" and isinstance(e.payload, dict)
        ]
        phases = [str(e.payload.get("phase")) for e in press_events]
        self.assertIn("down", phases)
        self.assertIn("up", phases)
        self.assertIn("single", phases)
        self.assertNotIn("cancel", phases)

    def test_keyboard_double_press_is_emitted(self) -> None:
        source = _ScriptedHDISource(
            [
                [
                    HDIEvent(1, 1, "w", "keyboard", "key_down", "OK", {"key": "a"}),
                    HDIEvent(2, 2, "w", "keyboard", "key_up", "OK", {"key": "a"}),
                    HDIEvent(3, 3, "w", "keyboard", "key_down", "OK", {"key": "a"}),
                    HDIEvent(4, 4, "w", "keyboard", "key_up", "OK", {"key": "a"}),
                ]
            ]
        )
        thread = HDIThread(source=source, poll_interval_s=0.001, double_press_threshold_s=1.0)
        thread.start()
        time.sleep(0.01)
        thread.stop()
        events = thread.poll_events(max_events=20)
        phases = [
            e.payload.get("phase")
            for e in events
            if e.device == "keyboard" and e.event_type == "press" and isinstance(e.payload, dict)
        ]
        self.assertIn("double", phases)

    def test_keyboard_hold_events_are_emitted(self) -> None:
        source = _ScriptedHDISource(
            [
                [HDIEvent(1, 1, "w", "keyboard", "key_down", "OK", {"key": "a"})],
                [],
                [],
                [],
            ]
        )
        thread = HDIThread(
            source=source,
            poll_interval_s=0.005,
            hold_threshold_s=0.005,
            hold_tick_interval_s=0.005,
        )
        thread.start()
        time.sleep(0.03)
        thread.stop()
        events = thread.poll_events(max_events=50)
        phases = [
            e.payload.get("phase")
            for e in events
            if e.device == "keyboard" and e.event_type == "press" and isinstance(e.payload, dict)
        ]
        self.assertIn("hold_start", phases)
        self.assertIn("hold_tick", phases)

    def test_multiple_keyboard_down_events_are_preserved(self) -> None:
        source = _ScriptedHDISource(
            [
                [
                    HDIEvent(1, 1, "w", "keyboard", "key_down", "OK", {"key": "a"}),
                    HDIEvent(2, 2, "w", "keyboard", "key_down", "OK", {"key": "b"}),
                ]
            ]
        )
        thread = HDIThread(source=source, poll_interval_s=0.001)
        thread.start()
        time.sleep(0.01)
        thread.stop()
        events = thread.poll_events(max_events=10)
        key_downs = [
            e.payload.get("key")
            for e in events
            if e.device == "keyboard"
            and e.event_type == "press"
            and isinstance(e.payload, dict)
            and e.payload.get("phase") == "down"
        ]
        self.assertIn("a", key_downs)
        self.assertIn("b", key_downs)

    def test_keyboard_active_keys_reports_simultaneous_state(self) -> None:
        source = _ScriptedHDISource(
            [
                [
                    HDIEvent(1, 1, "w", "keyboard", "key_down", "OK", {"key": "a"}),
                    HDIEvent(2, 2, "w", "keyboard", "key_down", "OK", {"key": "b"}),
                ]
            ]
        )
        thread = HDIThread(source=source, poll_interval_s=0.001)
        thread.start()
        time.sleep(0.01)
        thread.stop()
        events = thread.poll_events(max_events=10)
        press_events = [
            e
            for e in events
            if e.device == "keyboard" and e.event_type == "press" and isinstance(e.payload, dict)
        ]
        self.assertGreaterEqual(len(press_events), 2)
        last = press_events[-1]
        payload = last.payload
        assert isinstance(payload, dict)
        self.assertEqual(payload.get("phase"), "down")
        self.assertEqual(sorted(payload.get("active_keys", [])), ["a", "b"])

    def test_scroll_events_are_coalesced_deterministically_for_mouse(self) -> None:
        thread = HDIThread(source=_ScriptedHDISource([]), max_queue_size=4, poll_interval_s=0.001)
        thread._enqueue(  # type: ignore[attr-defined]
            HDIEvent(1, 1, "w", "mouse", "scroll", "OK", {"delta_x": 1.0, "delta_y": -2.0})
        )
        thread._enqueue(  # type: ignore[attr-defined]
            HDIEvent(2, 2, "w", "mouse", "scroll", "OK", {"delta_x": 2.0, "delta_y": -3.0})
        )
        events = thread.poll_events(max_events=10)
        self.assertEqual(len(events), 1)
        payload = events[0].payload
        assert isinstance(payload, dict)
        self.assertAlmostEqual(float(payload.get("delta_x", 0.0)), 3.0, places=6)
        self.assertAlmostEqual(float(payload.get("delta_y", 0.0)), -5.0, places=6)
        self.assertEqual(int(payload.get("coalesced_count", 0)), 2)
        self.assertEqual(str(payload.get("coalesce_mode", "")), "sum")
        telemetry = thread.consume_telemetry()
        self.assertEqual(int(telemetry.get("events_coalesced", 0)), 1)
        self.assertEqual(int(telemetry.get("events_dequeued", 0)), 1)

    def test_queue_latency_telemetry_reports_non_negative_values(self) -> None:
        thread = HDIThread(source=_ScriptedHDISource([]), max_queue_size=8, poll_interval_s=0.001)
        now_ns = time.time_ns()
        thread._enqueue(  # type: ignore[attr-defined]
            HDIEvent(1, now_ns - 2_000_000, "w", "mouse", "pointer_move", "OK", {"x": 10.0, "y": 10.0})
        )
        thread._enqueue(  # type: ignore[attr-defined]
            HDIEvent(2, now_ns - 1_000_000, "w", "keyboard", "key_down", "OK", {"key": "a"})
        )
        _ = thread.poll_events(max_events=10)
        telemetry = thread.consume_telemetry()
        self.assertGreaterEqual(int(telemetry.get("events_enqueued", -1)), 2)
        self.assertGreaterEqual(int(telemetry.get("events_dequeued", -1)), 1)
        self.assertGreaterEqual(int(telemetry.get("queue_latency_ns_p95", -1)), 0)
        self.assertGreaterEqual(int(telemetry.get("queue_latency_ns_max", -1)), 0)
        self.assertGreaterEqual(
            int(telemetry.get("queue_latency_ns_max", -1)),
            int(telemetry.get("queue_latency_ns_p95", -1)),
        )


if __name__ == "__main__":
    unittest.main()
