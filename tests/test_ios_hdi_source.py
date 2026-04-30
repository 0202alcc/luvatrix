from __future__ import annotations

import unittest

from luvatrix_core.platform.ios.hdi_source import (
    IOSUIKitHDISource,
    enqueue_native_touch_event,
    enqueue_native_touch_events,
    enqueue_touch_event,
    ios_touch_telemetry,
)


class IOSHDISourceTests(unittest.TestCase):
    def test_ios_touch_events_are_polled_as_mouse_hdi_events(self) -> None:
        source = IOSUIKitHDISource()
        self.assertEqual(source.poll(window_active=True, ts_ns=1), [])

        enqueue_touch_event("pointer_move", 12.5, 34.0, phase="move", touch_id=7)
        events = source.poll(window_active=True, ts_ns=2)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.device, "mouse")
        self.assertEqual(event.event_type, "pointer_move")
        self.assertEqual(event.status, "OK")
        self.assertEqual(event.payload["x"], 12.5)
        self.assertEqual(event.payload["y"], 34.0)
        self.assertEqual(event.payload["touch_id"], 7)

    def test_ios_native_touch_events_are_polled_as_touch_hdi_events(self) -> None:
        source = IOSUIKitHDISource()
        source.poll(window_active=True, ts_ns=1)

        enqueue_native_touch_event(1, "down", 10.0, 20.0, force=0.5, major_radius=12.0, tap_count=1)
        enqueue_native_touch_events([
            {"touch_id": 2, "phase": "down", "x": 30.0, "y": 40.0},
            {"touch_id": 1, "phase": "move", "x": 12.0, "y": 22.0},
        ])
        events = source.poll(window_active=True, ts_ns=2)
        self.assertEqual([event.device for event in events], ["touch", "touch", "touch"])
        self.assertEqual([event.event_type for event in events], ["touch", "touch", "touch"])
        self.assertEqual(events[0].payload["touch_id"], 1)
        self.assertEqual(events[0].payload["phase"], "down")
        self.assertEqual(events[0].payload["force"], 0.5)
        self.assertEqual(events[1].payload["touch_id"], 2)
        self.assertEqual(events[2].payload["x"], 12.0)

        telemetry = ios_touch_telemetry()
        self.assertGreaterEqual(int(telemetry["enqueued"]), 3)
        self.assertGreaterEqual(int(telemetry["polled"]), 3)
        self.assertEqual(telemetry["active_touches"], 2)


if __name__ == "__main__":
    unittest.main()
