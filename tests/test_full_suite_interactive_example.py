from __future__ import annotations

import unittest

from luvatrix_core.core.sensor_manager import SensorSample

from examples.app_protocol.full_suite_interactive.app_main import (
    InteractionState,
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


if __name__ == "__main__":
    unittest.main()
