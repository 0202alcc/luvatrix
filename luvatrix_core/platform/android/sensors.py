from __future__ import annotations

from dataclasses import dataclass
import json

from luvatrix_core.core.sensor_manager import SensorReadUnavailableError, SensorSample


ANDROID_SENSOR_TYPES = (
    "thermal.temperature",
    "power.voltage_current",
    "motion.accelerometer",
    "motion.gyroscope",
    "display.refresh",
    "camera.permission",
    "camera.device",
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
            if self._sensor_type == "camera.permission":
                telemetry = getattr(self._bridge, "cameraTelemetryJson", None) or getattr(
                    self._bridge, "camera_telemetry_json", None
                )
                if callable(telemetry):
                    try:
                        payload = json.loads(str(telemetry()))
                    except json.JSONDecodeError:
                        payload = {}
                    permission = str(payload.get("permission", "unknown")) if isinstance(payload, dict) else "unknown"
                    return {"permission": permission, "granted": permission == "granted"}, "metadata"
            if self._sensor_type == "camera.device":
                telemetry = getattr(self._bridge, "cameraTelemetryJson", None) or getattr(
                    self._bridge, "camera_telemetry_json", None
                )
                if callable(telemetry):
                    raw_telemetry = str(telemetry())
                    try:
                        payload = json.loads(raw_telemetry)
                        if isinstance(payload, dict):
                            inventory = payload.get("inventory") if isinstance(payload.get("inventory"), dict) else {}
                            cameras = inventory.get("cameras") if isinstance(inventory.get("cameras"), list) else []
                            payload.setdefault("available", bool(cameras))
                            payload.setdefault("device_count", len(cameras))
                            payload.setdefault("default_present", bool(payload.get("camera_id")))
                        return payload, "metadata"
                    except json.JSONDecodeError:
                        return {"raw": raw_telemetry}, "metadata"
            if self._sensor_type == "display.refresh":
                telemetry = getattr(self._bridge, "displayRefreshTelemetryJson", None) or getattr(
                    self._bridge, "display_refresh_telemetry_json", None
                )
                if callable(telemetry):
                    raw_telemetry = str(telemetry())
                    try:
                        payload = json.loads(raw_telemetry)
                        return payload, "metadata"
                    except json.JSONDecodeError:
                        return {"raw": raw_telemetry}, "metadata"
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
