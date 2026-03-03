from __future__ import annotations

import unittest

from luvatrix_core.core.app_runtime import AppContext
from luvatrix_core.core.hdi_thread import HDIThread
from luvatrix_core.core.sensor_manager import SensorManagerThread, TTLCachedSensorProvider
from luvatrix_core.core.window_matrix import WindowMatrix


class _NoopHDISource:
    def poll(self, window_active: bool, ts_ns: int):
        _ = (window_active, ts_ns)
        return []


class _FixedProvider:
    def __init__(self, value: object, unit: str) -> None:
        self.value = value
        self.unit = unit

    def read(self) -> tuple[object, str]:
        return (self.value, self.unit)


class SensorModernizationParityTests(unittest.TestCase):
    def test_consent_denial_and_audit_preserved_with_cached_provider(self) -> None:
        logs: list[dict[str, object]] = []
        mgr = SensorManagerThread(
            providers={"camera.device": TTLCachedSensorProvider(_FixedProvider({"available": True}, "metadata"), ttl_s=0.5)},
            poll_interval_s=0.001,
            consent_provider=lambda sensor_type, enable: False,
            audit_logger=logs.append,
        )
        changed = mgr.set_sensor_enabled("camera.device", True, actor="app")
        self.assertFalse(changed)
        self.assertEqual(mgr.read_sensor("camera.device").status, "DENIED")
        self.assertTrue(any(entry.get("action") == "enable_denied" for entry in logs))

    def test_default_sensor_disable_guard_and_audit_preserved(self) -> None:
        logs: list[dict[str, object]] = []
        mgr = SensorManagerThread(
            providers={"thermal.temperature": _FixedProvider(71.0, "C")},
            poll_interval_s=0.001,
            safety_disable_guard=lambda sensor_type: False,
            audit_logger=logs.append,
        )
        changed = mgr.set_sensor_enabled("thermal.temperature", False, actor="app")
        self.assertFalse(changed)
        self.assertTrue(any(entry.get("action") == "disable_denied" for entry in logs))

    def test_capability_denial_parity_with_cached_metadata_provider(self) -> None:
        mgr = SensorManagerThread(
            providers={"camera.device": TTLCachedSensorProvider(_FixedProvider({"available": True}, "metadata"), ttl_s=0.5)},
            poll_interval_s=0.001,
        )
        mgr.set_sensor_enabled("camera.device", True, actor="test")
        ctx = AppContext(
            matrix=WindowMatrix(height=2, width=2),
            hdi=HDIThread(source=_NoopHDISource(), poll_interval_s=0.001),
            sensor_manager=mgr,
            granted_capabilities={"window.write"},
            sensor_read_min_interval_s=0.0,
        )
        sample = ctx.read_sensor("camera.device")
        self.assertEqual(sample.status, "DENIED")


if __name__ == "__main__":
    unittest.main()
