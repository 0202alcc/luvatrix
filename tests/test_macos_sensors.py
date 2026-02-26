from __future__ import annotations

import unittest
from unittest.mock import patch

from luvatrix_core.platform.macos.sensors import (
    MacOSCameraDeviceProvider,
    MacOSMicrophoneDeviceProvider,
    MacOSMotionProvider,
    MacOSPowerVoltageCurrentProvider,
    MacOSSpeakerDeviceProvider,
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

    def test_camera_provider_reports_device_count(self) -> None:
        provider = MacOSCameraDeviceProvider()
        fake_rows = [{"_items": [{"_name": "FaceTime HD Camera"}, {"_name": "External USB Camera"}]}]
        with patch("luvatrix_core.platform.macos.sensors._read_system_profiler_rows", return_value=fake_rows):
            value, unit = provider.read()
        self.assertEqual(unit, "metadata")
        assert isinstance(value, dict)
        self.assertTrue(value["available"])
        self.assertEqual(value["device_count"], 2)

    def test_microphone_provider_reports_input_devices(self) -> None:
        provider = MacOSMicrophoneDeviceProvider()
        fake_rows = [
            {
                "_items": [
                    {"coreaudio_device_input": "spaudio_yes", "coreaudio_default_audio_input_device": "spaudio_yes"},
                    {"coreaudio_device_input": "spaudio_yes"},
                ]
            }
        ]
        with patch("luvatrix_core.platform.macos.sensors._read_system_profiler_rows", return_value=fake_rows):
            value, unit = provider.read()
        self.assertEqual(unit, "metadata")
        assert isinstance(value, dict)
        self.assertTrue(value["available"])
        self.assertEqual(value["device_count"], 2)
        self.assertTrue(value["default_present"])

    def test_speaker_provider_reports_output_devices(self) -> None:
        provider = MacOSSpeakerDeviceProvider()
        fake_rows = [
            {
                "_items": [
                    {"coreaudio_device_output": "spaudio_yes", "coreaudio_default_audio_output_device": "spaudio_yes"},
                    {"coreaudio_device_output": "spaudio_yes"},
                ]
            }
        ]
        with patch("luvatrix_core.platform.macos.sensors._read_system_profiler_rows", return_value=fake_rows):
            value, unit = provider.read()
        self.assertEqual(unit, "metadata")
        assert isinstance(value, dict)
        self.assertTrue(value["available"])
        self.assertEqual(value["device_count"], 2)
        self.assertTrue(value["default_present"])

    def test_microphone_provider_accepts_bool_yes_variants(self) -> None:
        provider = MacOSMicrophoneDeviceProvider()
        fake_rows = [
            {
                "_items": [
                    {"_name": "MacBook Pro Microphone", "coreaudio_device_input": True},
                    {"_name": "USB Mic", "coreaudio_default_audio_input_device": "yes", "coreaudio_device_input": 1},
                ]
            }
        ]
        with patch("luvatrix_core.platform.macos.sensors._read_system_profiler_rows", return_value=fake_rows):
            value, unit = provider.read()
        self.assertEqual(unit, "metadata")
        assert isinstance(value, dict)
        self.assertTrue(value["available"])
        self.assertEqual(value["device_count"], 2)
        self.assertTrue(value["default_present"])

    def test_speaker_provider_falls_back_to_name_inference(self) -> None:
        provider = MacOSSpeakerDeviceProvider()
        fake_rows = [
            {
                "_items": [
                    {"_name": "MacBook Pro Speakers"},
                    {"_name": "Headphones"},
                ]
            }
        ]
        with patch("luvatrix_core.platform.macos.sensors._read_system_profiler_rows", return_value=fake_rows):
            value, unit = provider.read()
        self.assertEqual(unit, "metadata")
        assert isinstance(value, dict)
        self.assertTrue(value["available"])
        self.assertEqual(value["device_count"], 2)


if __name__ == "__main__":
    unittest.main()
