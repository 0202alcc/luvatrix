from __future__ import annotations

import unittest

from luvatrix_core.platform.android.hdi_source import (
    AndroidHDISource,
    android_input_telemetry,
    clear_android_input_events,
    enqueue_native_key_event,
    enqueue_native_touch_event,
)


class AndroidHDISourceTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_android_input_events()

    def test_touch_events_are_polled_as_hdi_events(self) -> None:
        enqueue_native_touch_event(7, "down", 12.5, 30.0, force=0.4, major_radius=9.0)

        events = AndroidHDISource().poll(window_active=True, ts_ns=1)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].device, "touch")
        self.assertEqual(events[0].event_type, "touch")
        self.assertEqual(events[0].payload["touch_id"], 7)
        self.assertEqual(events[0].payload["phase"], "down")
        self.assertEqual(android_input_telemetry()["active_touches"], 1)

    def test_key_events_are_polled_as_hdi_events(self) -> None:
        enqueue_native_key_event("A", "down", scan_code=29)

        events = AndroidHDISource().poll(window_active=True, ts_ns=1)

        self.assertEqual(events[0].device, "keyboard")
        self.assertEqual(events[0].event_type, "key_down")
        self.assertEqual(events[0].payload["key"], "A")
        self.assertEqual(events[0].payload["scan_code"], 29)
        self.assertEqual(android_input_telemetry()["last_key"], "A")

    def test_inactive_window_does_not_consume_events(self) -> None:
        source = AndroidHDISource()
        enqueue_native_touch_event(1, "down", 1.0, 2.0)

        self.assertEqual(source.poll(window_active=False, ts_ns=1), [])
        self.assertEqual(len(source.poll(window_active=True, ts_ns=2)), 1)

    def test_cancel_removes_active_touch(self) -> None:
        source = AndroidHDISource()
        enqueue_native_touch_event(1, "down", 1.0, 2.0)
        enqueue_native_touch_event(1, "cancel", 1.0, 2.0)

        source.poll(window_active=True, ts_ns=1)

        self.assertEqual(android_input_telemetry()["active_touches"], 0)
        self.assertEqual(android_input_telemetry()["last_phase"], "cancel")


if __name__ == "__main__":
    unittest.main()
