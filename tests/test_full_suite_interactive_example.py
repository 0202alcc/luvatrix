from __future__ import annotations

import unittest

from luvatrix_core.core.sensor_manager import SensorSample
from luvatrix.app import InputState, apply_hdi_events

from examples.full_suite_interactive.app_main import (
    InteractionState,
    _apply_hdi_events,
    _debug_env_default_on,
    _effective_touch_pressure,
    _mouse_label_text,
    _pointer_bubble_radius,
    _touch_bubble_radius,
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

    def test_touch_release_hides_cursor_dot(self) -> None:
        class _Event:
            def __init__(self, payload) -> None:
                self.device = "touch"
                self.event_type = "touch"
                self.status = "OK"
                self.payload = payload

        state = InteractionState()

        _apply_hdi_events(
            state,
            [
                _Event({"touch_id": 1, "phase": "down", "x": 10.0, "y": 20.0, "major_radius": 12.0}),
                _Event({"touch_id": 1, "phase": "up", "x": 10.0, "y": 20.0}),
            ],
            surface_height=100,
        )

        self.assertEqual(state.touch_count, 0)
        self.assertFalse(state.mouse_in_window)
        self.assertEqual(state.pressure, 0.0)

    def test_android_contact_area_imitates_pressure(self) -> None:
        light = _effective_touch_pressure(force=1.0, major_radius=8.0)
        heavy = _effective_touch_pressure(force=1.0, major_radius=26.0)

        self.assertGreater(heavy, light)
        self.assertGreater(heavy, 0.5)

    def test_bubble_radius_has_larger_default_and_cap(self) -> None:
        self.assertEqual(_touch_bubble_radius(0.0), 24.0)
        self.assertEqual(_touch_bubble_radius(1.0), 88.0)
        self.assertEqual(_pointer_bubble_radius(InteractionState()), 30.0)

    def test_debug_mode_defaults_on(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(_debug_env_default_on("LUVATRIX_FSI_DEBUG"))
        with patch.dict(os.environ, {"LUVATRIX_FSI_DEBUG": "0"}):
            self.assertFalse(_debug_env_default_on("LUVATRIX_FSI_DEBUG"))


if __name__ == "__main__":
    unittest.main()
