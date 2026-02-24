from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Protocol

from .sensor_manager import SensorManagerThread, SensorSample


AuditLogger = Callable[[dict[str, object]], None]


@dataclass(frozen=True)
class EnergySafetyPolicy:
    thermal_warn_c: float = 85.0
    thermal_critical_c: float = 95.0
    power_warn_w: float = 45.0
    power_critical_w: float = 65.0
    critical_streak_for_shutdown: int = 3
    throttle_multiplier_on_warn: float = 1.5
    throttle_multiplier_on_critical: float = 2.5


@dataclass(frozen=True)
class EnergySafetyDecision:
    state: str
    throttle_multiplier: float
    should_shutdown: bool
    reason: str | None
    thermal_c: float | None
    power_w: float | None


class EnergySafetyController(Protocol):
    def evaluate(self) -> EnergySafetyDecision:
        ...


class SensorEnergySafetyController:
    """Evaluates thermal/power telemetry and recommends runtime pacing safeguards."""

    def __init__(
        self,
        sensor_manager: SensorManagerThread,
        policy: EnergySafetyPolicy | None = None,
        audit_logger: AuditLogger | None = None,
        enforce_shutdown: bool = True,
    ) -> None:
        self._sensor_manager = sensor_manager
        self._policy = policy or EnergySafetyPolicy()
        self._audit_logger = audit_logger or (lambda entry: None)
        self._enforce_shutdown = enforce_shutdown
        self._critical_streak = 0
        self._last_state = "OK"

    def evaluate(self) -> EnergySafetyDecision:
        thermal_sample = self._sensor_manager.read_sensor("thermal.temperature")
        power_sample = self._sensor_manager.read_sensor("power.voltage_current")
        thermal_c = _extract_thermal_c(thermal_sample)
        power_w = _extract_power_w(power_sample)

        thermal_state = _state_for_value(
            thermal_c, self._policy.thermal_warn_c, self._policy.thermal_critical_c
        )
        power_state = _state_for_value(power_w, self._policy.power_warn_w, self._policy.power_critical_w)
        state = _max_state(thermal_state, power_state)

        should_shutdown = False
        reason: str | None = None
        if state == "CRITICAL":
            self._critical_streak += 1
            if self._enforce_shutdown and self._critical_streak >= self._policy.critical_streak_for_shutdown:
                should_shutdown = True
                reason = "sustained_critical_energy_telemetry"
        else:
            self._critical_streak = 0

        throttle_multiplier = 1.0
        if state == "WARN":
            throttle_multiplier = max(1.0, self._policy.throttle_multiplier_on_warn)
        elif state == "CRITICAL":
            throttle_multiplier = max(1.0, self._policy.throttle_multiplier_on_critical)

        decision = EnergySafetyDecision(
            state=state,
            throttle_multiplier=throttle_multiplier,
            should_shutdown=should_shutdown,
            reason=reason,
            thermal_c=thermal_c,
            power_w=power_w,
        )
        self._audit(decision)
        self._last_state = state
        return decision

    def _audit(self, decision: EnergySafetyDecision) -> None:
        if decision.state == self._last_state and not decision.should_shutdown:
            return
        self._audit_logger(
            {
                "ts_ns": time.time_ns(),
                "action": "energy_safety_state",
                "state": decision.state,
                "should_shutdown": decision.should_shutdown,
                "reason": decision.reason,
                "thermal_c": decision.thermal_c,
                "power_w": decision.power_w,
                "actor": "energy_safety",
            }
        )


def _extract_thermal_c(sample: SensorSample) -> float | None:
    if sample.status != "OK" or sample.value is None:
        return None
    if isinstance(sample.value, (int, float)):
        return float(sample.value)
    if isinstance(sample.value, dict):
        value = sample.value.get("celsius") if "celsius" in sample.value else sample.value.get("temperature_c")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _extract_power_w(sample: SensorSample) -> float | None:
    if sample.status != "OK" or sample.value is None:
        return None
    if isinstance(sample.value, (int, float)):
        return float(sample.value)
    if isinstance(sample.value, dict):
        watts = sample.value.get("power_w")
        if isinstance(watts, (int, float)):
            return float(watts)
        voltage = sample.value.get("voltage_v")
        current = sample.value.get("current_a")
        if isinstance(voltage, (int, float)) and isinstance(current, (int, float)):
            return float(voltage) * float(current)
    return None


def _state_for_value(value: float | None, warn: float, critical: float) -> str:
    if value is None:
        return "OK"
    if value >= critical:
        return "CRITICAL"
    if value >= warn:
        return "WARN"
    return "OK"


def _max_state(lhs: str, rhs: str) -> str:
    order = {"OK": 0, "WARN": 1, "CRITICAL": 2}
    return lhs if order[lhs] >= order[rhs] else rhs
