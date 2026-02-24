from __future__ import annotations

import unittest

from luvatrix_core.core.energy_safety import EnergySafetyPolicy, SensorEnergySafetyController
from luvatrix_core.core.sensor_manager import SensorSample


class _FakeSensorManager:
    def __init__(self, thermal: SensorSample, power: SensorSample) -> None:
        self._thermal = thermal
        self._power = power

    def read_sensor(self, sensor_type: str) -> SensorSample:
        if sensor_type == "thermal.temperature":
            return self._thermal
        if sensor_type == "power.voltage_current":
            return self._power
        raise AssertionError(f"unexpected sensor type: {sensor_type}")


def _sample(sensor_type: str, value: object | None, status: str = "OK") -> SensorSample:
    return SensorSample(
        sample_id=1,
        ts_ns=1,
        sensor_type=sensor_type,
        status=status,  # type: ignore[arg-type]
        value=value,
        unit=None,
    )


class EnergySafetyTests(unittest.TestCase):
    def test_warn_state_throttles(self) -> None:
        mgr = _FakeSensorManager(
            thermal=_sample("thermal.temperature", 88.0),
            power=_sample("power.voltage_current", {"power_w": 20.0}),
        )
        controller = SensorEnergySafetyController(sensor_manager=mgr)  # type: ignore[arg-type]
        decision = controller.evaluate()
        self.assertEqual(decision.state, "WARN")
        self.assertGreater(decision.throttle_multiplier, 1.0)
        self.assertFalse(decision.should_shutdown)

    def test_enforced_critical_shutdown_after_streak(self) -> None:
        mgr = _FakeSensorManager(
            thermal=_sample("thermal.temperature", 99.0),
            power=_sample("power.voltage_current", {"voltage_v": 20.0, "current_a": 4.0}),
        )
        controller = SensorEnergySafetyController(
            sensor_manager=mgr,  # type: ignore[arg-type]
            policy=EnergySafetyPolicy(critical_streak_for_shutdown=2),
            enforce_shutdown=True,
        )
        d1 = controller.evaluate()
        d2 = controller.evaluate()
        self.assertFalse(d1.should_shutdown)
        self.assertTrue(d2.should_shutdown)
        self.assertEqual(d2.reason, "sustained_critical_energy_telemetry")

    def test_monitor_mode_never_shutdowns(self) -> None:
        mgr = _FakeSensorManager(
            thermal=_sample("thermal.temperature", 100.0),
            power=_sample("power.voltage_current", {"power_w": 100.0}),
        )
        controller = SensorEnergySafetyController(
            sensor_manager=mgr,  # type: ignore[arg-type]
            policy=EnergySafetyPolicy(critical_streak_for_shutdown=1),
            enforce_shutdown=False,
        )
        decision = controller.evaluate()
        self.assertEqual(decision.state, "CRITICAL")
        self.assertFalse(decision.should_shutdown)


if __name__ == "__main__":
    unittest.main()
