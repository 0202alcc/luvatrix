from __future__ import annotations

import unittest

from luvatrix_core.core.sensor_manager import SensorSample

from examples.app_protocol.full_suite_interactive.app_main import (
    InteractionState,
    _build_scene_svg,
    _detect_frame_switch,
    _mouse_label_text,
    _next_coord_frame,
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
        state = InteractionState(mouse_in_window=False, mouse_error="window not active / pointer out of bounds")
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

    def test_build_scene_svg_contains_cursor_circle_when_mouse_visible(self) -> None:
        state = InteractionState(mouse_x=20.0, mouse_y=30.0, mouse_in_window=True)
        markup = _build_scene_svg(120, 80, state)
        self.assertIn("<svg", markup)
        self.assertIn("<circle", markup)

    def test_coord_frame_switch_mapping(self) -> None:
        self.assertEqual(_next_coord_frame("screen_tl", "1"), "screen_tl")
        self.assertEqual(_next_coord_frame("screen_tl", "2"), "cartesian_bl")
        self.assertEqual(_next_coord_frame("screen_tl", "3"), "cartesian_center")
        self.assertEqual(_next_coord_frame("screen_tl", "c"), "cartesian_bl")

    def test_detect_frame_switch_from_keyboard_press_event(self) -> None:
        class _Event:
            def __init__(self, payload) -> None:
                self.device = "keyboard"
                self.status = "OK"
                self.payload = payload

        events = [_Event({"phase": "down", "key": "2"})]
        self.assertEqual(_detect_frame_switch(events, "screen_tl"), "cartesian_bl")


if __name__ == "__main__":
    unittest.main()
