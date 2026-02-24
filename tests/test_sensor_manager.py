from __future__ import annotations

import time
import unittest

from luvatrix_core.core.sensor_manager import (
    DEFAULT_ENABLED_SENSORS,
    SensorManagerThread,
    SensorProvider,
)


class _FixedProvider(SensorProvider):
    def __init__(self, value: object, unit: str) -> None:
        self.value = value
        self.unit = unit
        self.reads = 0

    def read(self) -> tuple[object, str]:
        self.reads += 1
        return self.value, self.unit


class _FailingProvider(SensorProvider):
    def read(self) -> tuple[object, str]:
        raise RuntimeError("sensor read failed")


class SensorManagerThreadTests(unittest.TestCase):
    def test_defaults_enabled_and_produce_samples(self) -> None:
        providers = {
            "thermal.temperature": _FixedProvider(72.5, "C"),
            "power.voltage_current": _FixedProvider({"v": 12.2, "a": 1.3}, "mixed"),
        }
        mgr = SensorManagerThread(providers=providers, poll_interval_s=0.001)
        self.assertTrue(DEFAULT_ENABLED_SENSORS.issubset(mgr.enabled_sensors()))
        mgr.start()
        time.sleep(0.01)
        mgr.stop()
        s1 = mgr.read_sensor("thermal.temperature")
        s2 = mgr.read_sensor("power.voltage_current")
        self.assertEqual(s1.status, "OK")
        self.assertEqual(s2.status, "OK")

    def test_enable_non_default_requires_consent(self) -> None:
        providers = {"sensor.custom": _FixedProvider(1, "u")}
        mgr = SensorManagerThread(
            providers=providers,
            poll_interval_s=0.001,
            consent_provider=lambda sensor_type, enable: False,
        )
        changed = mgr.set_sensor_enabled("sensor.custom", True, actor="app")
        self.assertFalse(changed)
        self.assertEqual(mgr.read_sensor("sensor.custom").status, "DENIED")

    def test_disabling_safety_sensor_requires_guard_and_audit(self) -> None:
        logs: list[dict[str, object]] = []
        mgr = SensorManagerThread(
            providers={"thermal.temperature": _FixedProvider(70, "C")},
            poll_interval_s=0.001,
            safety_disable_guard=lambda sensor_type: False,
            audit_logger=logs.append,
        )
        changed = mgr.set_sensor_enabled("thermal.temperature", False, actor="app")
        self.assertFalse(changed)
        self.assertTrue(any(e["action"] == "disable_denied" for e in logs))

    def test_provider_failure_is_unavailable(self) -> None:
        mgr = SensorManagerThread(
            providers={"thermal.temperature": _FailingProvider()},
            poll_interval_s=0.001,
        )
        mgr.start()
        time.sleep(0.01)
        mgr.stop()
        sample = mgr.read_sensor("thermal.temperature")
        self.assertEqual(sample.status, "UNAVAILABLE")
        self.assertIsNone(sample.value)

    def test_unknown_sensor_returns_unavailable(self) -> None:
        mgr = SensorManagerThread(providers={}, poll_interval_s=0.001)
        sample = mgr.read_sensor("sensor.unknown")
        self.assertEqual(sample.status, "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
