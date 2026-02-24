from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Callable, Literal, Protocol


SensorStatus = Literal["OK", "DISABLED", "UNAVAILABLE", "DENIED"]
AuditLogger = Callable[[dict[str, object]], None]
ConsentProvider = Callable[[str, bool], bool]
SafetyDisableGuard = Callable[[str], bool]

DEFAULT_ENABLED_SENSORS = {"thermal.temperature", "power.voltage_current"}


@dataclass(frozen=True)
class SensorSample:
    sample_id: int
    ts_ns: int
    sensor_type: str
    status: SensorStatus
    value: object | None
    unit: str | None


class SensorProvider(Protocol):
    def read(self) -> tuple[object, str]:
        ...


class SensorReadDeniedError(RuntimeError):
    pass


class SensorReadUnavailableError(RuntimeError):
    pass


class FallbackSensorProvider:
    """Tries providers in order and returns first successful read."""

    def __init__(self, providers: list[SensorProvider]) -> None:
        if not providers:
            raise ValueError("providers must not be empty")
        self._providers = providers

    def read(self) -> tuple[object, str]:
        last_exc: Exception | None = None
        for provider in self._providers:
            try:
                return provider.read()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                continue
        if last_exc is not None:
            raise SensorReadUnavailableError("all fallback providers failed") from last_exc
        raise SensorReadUnavailableError("all fallback providers failed")


class SensorManagerThread:
    """Sensor manager thread with per-sensor polling and policy enforcement."""

    def __init__(
        self,
        providers: dict[str, SensorProvider],
        poll_interval_s: float = 0.5,
        consent_provider: ConsentProvider | None = None,
        safety_disable_guard: SafetyDisableGuard | None = None,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")
        self._providers = dict(providers)
        self._poll_interval_s = poll_interval_s
        self._consent_provider = consent_provider or (lambda sensor_type, enable: True)
        self._safety_disable_guard = safety_disable_guard or (lambda sensor_type: True)
        self._audit_logger = audit_logger or (lambda entry: None)
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._next_sample_id = 1
        self._denied_sensors: set[str] = set()
        self._enabled: dict[str, bool] = {
            sensor_type: sensor_type in DEFAULT_ENABLED_SENSORS
            for sensor_type in self._providers
        }
        self._samples: dict[str, SensorSample] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._run, name="luvatrix-sensor-manager", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def enabled_sensors(self) -> set[str]:
        with self._lock:
            return {k for k, v in self._enabled.items() if v}

    def set_sensor_enabled(self, sensor_type: str, enabled: bool, actor: str = "runtime") -> bool:
        with self._lock:
            if sensor_type not in self._enabled:
                self._enabled[sensor_type] = False
            if enabled:
                if sensor_type not in DEFAULT_ENABLED_SENSORS and not self._consent_provider(sensor_type, True):
                    self._denied_sensors.add(sensor_type)
                    self._audit("enable_denied", sensor_type, actor)
                    return False
                self._enabled[sensor_type] = True
                self._denied_sensors.discard(sensor_type)
                self._audit("enabled", sensor_type, actor)
                return True

            if sensor_type in DEFAULT_ENABLED_SENSORS and not self._safety_disable_guard(sensor_type):
                self._audit("disable_denied", sensor_type, actor)
                return False
            self._enabled[sensor_type] = False
            self._audit("disabled", sensor_type, actor)
            return True

    def read_sensor(self, sensor_type: str) -> SensorSample:
        with self._lock:
            if sensor_type not in self._providers and sensor_type not in self._enabled:
                return self._sample(sensor_type, "UNAVAILABLE", None, None)
            if sensor_type in self._denied_sensors:
                return self._sample(sensor_type, "DENIED", None, None)
            enabled = self._enabled.get(sensor_type, False)
            if not enabled:
                return self._sample(sensor_type, "DISABLED", None, None)
            if sensor_type not in self._providers:
                return self._sample(sensor_type, "UNAVAILABLE", None, None)
            sample = self._samples.get(sensor_type)
            if sample is None:
                return self._sample(sensor_type, "UNAVAILABLE", None, None)
            return sample

    def _run(self) -> None:
        while self._running.is_set():
            with self._lock:
                enabled_sensors = [s for s, is_enabled in self._enabled.items() if is_enabled]
            for sensor_type in enabled_sensors:
                self._poll_sensor(sensor_type)
            time.sleep(self._poll_interval_s)

    def _poll_sensor(self, sensor_type: str) -> None:
        provider = self._providers.get(sensor_type)
        if provider is None:
            with self._lock:
                self._samples[sensor_type] = self._sample(sensor_type, "UNAVAILABLE", None, None)
            return
        try:
            value, unit = provider.read()
            status: SensorStatus = "OK"
        except SensorReadDeniedError:
            value, unit = None, None
            status = "DENIED"
        except SensorReadUnavailableError:
            value, unit = None, None
            status = "UNAVAILABLE"
        except Exception:  # noqa: BLE001
            value, unit = None, None
            status = "UNAVAILABLE"
        with self._lock:
            self._samples[sensor_type] = self._sample(sensor_type, status, value, unit)

    def _sample(
        self,
        sensor_type: str,
        status: SensorStatus,
        value: object | None,
        unit: str | None,
    ) -> SensorSample:
        sample = SensorSample(
            sample_id=self._next_sample_id,
            ts_ns=time.time_ns(),
            sensor_type=sensor_type,
            status=status,
            value=value,
            unit=unit,
        )
        self._next_sample_id += 1
        return sample

    def _audit(self, action: str, sensor_type: str, actor: str) -> None:
        self._audit_logger(
            {
                "ts_ns": time.time_ns(),
                "action": action,
                "sensor_type": sensor_type,
                "actor": actor,
            }
        )
