from __future__ import annotations

from dataclasses import dataclass

from luvatrix_core.core.sensor_manager import SensorReadUnavailableError, SensorSample


ANDROID_SENSOR_TYPES = (
    "thermal.temperature",
    "power.voltage_current",
    "motion.accelerometer",
    "motion.gyroscope",
    "camera.permission",
    "microphone.permission",
)


@dataclass(frozen=True)
class AndroidUnavailableSensorProvider:
    sensor_type: str
    reason: str = "android bridge unavailable"

    def read(self) -> tuple[object, str]:
        raise SensorReadUnavailableError(self.reason)


def make_android_sensor_providers(bridge: object | None = None) -> dict[str, object]:
    if bridge is None:
        return {sensor_type: AndroidUnavailableSensorProvider(sensor_type) for sensor_type in ANDROID_SENSOR_TYPES}
    out: dict[str, object] = {}
    for sensor_type in ANDROID_SENSOR_TYPES:
        out[sensor_type] = _BridgeSensorProvider(bridge, sensor_type)
    return out


def unavailable_android_sensor_sample(sensor_type: str) -> SensorSample:
    import time

    return SensorSample(
        sample_id=1,
        ts_ns=time.time_ns(),
        sensor_type=sensor_type,
        status="UNAVAILABLE",
        value=None,
        unit=None,
    )


class _BridgeSensorProvider:
    def __init__(self, bridge: object, sensor_type: str) -> None:
        self._bridge = bridge
        self._sensor_type = sensor_type

    def read(self) -> tuple[object, str]:
        reader = getattr(self._bridge, "readSensor", None) or getattr(self._bridge, "read_sensor", None)
        if not callable(reader):
            raise SensorReadUnavailableError("android sensor bridge has no readSensor/read_sensor method")
        raw = reader(self._sensor_type)
        if isinstance(raw, dict):
            status = str(raw.get("status", "UNAVAILABLE"))
            if status != "OK":
                raise SensorReadUnavailableError(status)
            return raw.get("value"), str(raw.get("unit", ""))
        if isinstance(raw, (tuple, list)) and len(raw) == 2:
            return raw[0], str(raw[1])
        raise SensorReadUnavailableError("android sensor bridge returned unsupported payload")
