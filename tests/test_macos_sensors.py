from __future__ import annotations

import unittest
from unittest.mock import patch

from luvatrix_core.platform.macos.sensors import (
    MacOSMotionProvider,
    MacOSPowerVoltageCurrentProvider,
    MacOSThermalTemperatureProvider,
)


class MacOSSensorProviderTests(unittest.TestCase):
    def test_thermal_provider_converts_tenths_kelvin_to_celsius(self) -> None:
        provider = MacOSThermalTemperatureProvider()
        with patch("luvatrix_core.platform.macos.sensors._read_smart_battery_dict", return_value={"Temperature": 2982}):
            value, unit = provider.read()
        self.assertEqual(unit, "C")
        self.assertAlmostEqual(float(value), 25.05, places=2)

    def test_power_provider_converts_mv_ma(self) -> None:
        provider = MacOSPowerVoltageCurrentProvider()
        with patch(
            "luvatrix_core.platform.macos.sensors._read_smart_battery_dict",
            return_value={"Voltage": 12034, "Amperage": -1550},
        ):
            value, unit = provider.read()
        self.assertEqual(unit, "mixed")
        assert isinstance(value, dict)
        self.assertEqual(value["voltage_v"], 12.034)
        self.assertEqual(value["current_a"], -1.55)

    def test_motion_provider_reads_xyz(self) -> None:
        provider = MacOSMotionProvider()
        with patch(
            "luvatrix_core.platform.macos.sensors._read_motion_sensor_dict",
            return_value={"X": 12, "Y": -3, "Z": 100},
        ):
            value, unit = provider.read()
        self.assertEqual(unit, "raw")
        assert isinstance(value, dict)
        self.assertEqual(value["x"], 12.0)
        self.assertEqual(value["y"], -3.0)
        self.assertEqual(value["z"], 100.0)


if __name__ == "__main__":
    unittest.main()
