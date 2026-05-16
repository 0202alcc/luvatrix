from __future__ import annotations

import unittest

from luvatrix_core.core.sensor_manager import SensorReadUnavailableError
from luvatrix_core.platform.android.sensors import (
    ANDROID_SENSOR_TYPES,
    make_android_sensor_providers,
    unavailable_android_sensor_sample,
)


class AndroidSensorsTests(unittest.TestCase):
    def test_stub_providers_report_unavailable(self) -> None:
        providers = make_android_sensor_providers()

        self.assertIn("thermal.temperature", providers)
        with self.assertRaises(SensorReadUnavailableError):
            providers["thermal.temperature"].read()

    def test_sensor_inventory_contains_full_suite_metadata_sensors(self) -> None:
        self.assertIn("camera.permission", ANDROID_SENSOR_TYPES)
        self.assertIn("microphone.permission", ANDROID_SENSOR_TYPES)
        self.assertIn("motion.accelerometer", ANDROID_SENSOR_TYPES)

    def test_unavailable_sample_shape(self) -> None:
        sample = unavailable_android_sensor_sample("camera.permission")

        self.assertEqual(sample.sensor_type, "camera.permission")
        self.assertEqual(sample.status, "UNAVAILABLE")
        self.assertIsNone(sample.value)


if __name__ == "__main__":
    unittest.main()
