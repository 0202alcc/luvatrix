from __future__ import annotations

import unittest
import json

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
        self.assertIn("camera.device", ANDROID_SENSOR_TYPES)
        self.assertIn("display.refresh", ANDROID_SENSOR_TYPES)
        self.assertIn("microphone.permission", ANDROID_SENSOR_TYPES)
        self.assertIn("motion.accelerometer", ANDROID_SENSOR_TYPES)

    def test_unavailable_sample_shape(self) -> None:
        sample = unavailable_android_sensor_sample("camera.permission")

        self.assertEqual(sample.sensor_type, "camera.permission")
        self.assertEqual(sample.status, "UNAVAILABLE")
        self.assertIsNone(sample.value)

    def test_camera_device_provider_reads_view_telemetry_json(self) -> None:
        class _Bridge:
            def cameraTelemetryJson(self) -> str:
                return json.dumps(
                    {
                        "status": "running",
                        "width": 1920,
                        "height": 1080,
                        "camera_id": "0",
                        "inventory": {
                            "cameras": [
                                {"camera_id": "0", "facing": "back"},
                                {"camera_id": "1", "facing": "front"},
                            ]
                        },
                    }
                )

        providers = make_android_sensor_providers(_Bridge())
        value, unit = providers["camera.device"].read()

        self.assertEqual(unit, "metadata")
        self.assertEqual(value["status"], "running")
        self.assertEqual(value["width"], 1920)
        self.assertTrue(value["available"])
        self.assertEqual(value["device_count"], 2)
        self.assertTrue(value["default_present"])

    def test_camera_permission_provider_reads_view_telemetry_json(self) -> None:
        class _Bridge:
            def cameraTelemetryJson(self) -> str:
                return json.dumps({"permission": "granted"})

        providers = make_android_sensor_providers(_Bridge())
        value, unit = providers["camera.permission"].read()

        self.assertEqual(unit, "metadata")
        self.assertEqual(value, {"permission": "granted", "granted": True})

    def test_display_refresh_provider_reads_view_telemetry_json(self) -> None:
        class _Bridge:
            def displayRefreshTelemetryJson(self) -> str:
                return json.dumps(
                    {
                        "requested_refresh_hz": 120,
                        "actual_refresh_hz": 60,
                        "honored": False,
                    }
                )

        providers = make_android_sensor_providers(_Bridge())
        value, unit = providers["display.refresh"].read()

        self.assertEqual(unit, "metadata")
        self.assertEqual(value["requested_refresh_hz"], 120)
        self.assertEqual(value["actual_refresh_hz"], 60)
        self.assertFalse(value["honored"])


if __name__ == "__main__":
    unittest.main()
