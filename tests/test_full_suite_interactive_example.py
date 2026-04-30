from __future__ import annotations

import unittest

from luvatrix_core.core.sensor_manager import SensorSample
from luvatrix.app import InputState, apply_hdi_events

from examples.full_suite_interactive.app_main import (
    _mouse_label_text,
    format_dashboard,
    select_sensors,
)


class FullSuiteInteractiveExampleTests(unittest.TestCase):
    def test_select_sensors_defaults_to_all(self) -> None:
        available = ["thermal.temperature", "power.voltage_current"]
        selected = select_sensors([], available)
        self.assertEqual(selected, available)

    def test_select_sensors_rejects_unknown_sensor(self) -> None:
        with self.assertRaises(ValueError):
            select_sensors(["sensor.unknown"], ["thermal.temperature"])

    def test_format_dashboard_reports_out_of_bounds(self) -> None:
        state = InputState(mouse_in_window=False, mouse_error="window not active / pointer out of bounds")
        samples = {
            "thermal.temperature": SensorSample(
                sample_id=1,
                ts_ns=1,
                sensor_type="thermal.temperature",
                status="UNAVAILABLE",
                value=None,
                unit="C",
            )
        }
        text = format_dashboard(state, samples, ["thermal.temperature"], "stretch", 60.0)
        self.assertIn("out-of-bounds", text)
        self.assertIn("thermal.temperature", text)
        self.assertIn("hdi telemetry", text)
        self.assertIn("mouse_xy", text)
        self.assertIn("key_last", text)
        self.assertIn("keys_down", text)
        self.assertIn("+", text)
        self.assertIn("| sensor", text)

    def test_mouse_label_text_includes_frame_and_coords(self) -> None:
        label = _mouse_label_text("cartesian_bl", 20.0, 49.0)
        self.assertIn("cartesian_bl", label)
        self.assertIn("x=20.0", label)
        self.assertIn("y=49.0", label)

    def test_apply_hdi_events_tracks_native_touches_and_gestures(self) -> None:
        class _Event:
            def __init__(self, event_type, payload) -> None:
                self.device = "touch"
                self.event_type = event_type
                self.status = "OK"
                self.payload = payload

        state = InputState()
        apply_hdi_events(
            state,
            [
                _Event("touch", {"touch_id": 1, "phase": "down", "x": 10.0, "y": 20.0}),
                _Event("touch", {"touch_id": 2, "phase": "down", "x": 30.0, "y": 40.0}),
                _Event(
                    "gesture",
                    {
                        "kind": "pinch",
                        "phase": "move",
                        "centroid_x": 20.0,
                        "centroid_y": 30.0,
                        "translation_x": 0.0,
                        "translation_y": 0.0,
                        "scale": 1.25,
                        "rotation": 0.0,
                    },
                ),
            ],
        )
        self.assertEqual(state.touch_count, 2)
        self.assertEqual(state.active_touches[1], (10.0, 20.0))
        self.assertEqual(state.gesture_scale, 1.25)
        self.assertTrue(state.mouse_in_window)


if __name__ == "__main__":
    unittest.main()
