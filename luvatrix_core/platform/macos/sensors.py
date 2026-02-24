from __future__ import annotations

import plistlib
import subprocess


def _read_smart_battery_dict() -> dict[str, object]:
    proc = subprocess.run(
        ["ioreg", "-r", "-n", "AppleSmartBattery", "-a"],
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("ioreg AppleSmartBattery query failed")
    payload = proc.stdout
    if not payload:
        raise RuntimeError("ioreg AppleSmartBattery returned empty payload")
    rows = plistlib.loads(payload)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("ioreg AppleSmartBattery payload format unexpected")
    row = rows[0]
    if not isinstance(row, dict):
        raise RuntimeError("ioreg AppleSmartBattery row format unexpected")
    return row


def _read_motion_sensor_dict() -> dict[str, object]:
    proc = subprocess.run(
        ["ioreg", "-r", "-c", "AppleSMCMotionSensor", "-a"],
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("ioreg motion sensor query failed")
    payload = proc.stdout
    if not payload:
        raise RuntimeError("ioreg motion sensor returned empty payload")
    rows = plistlib.loads(payload)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("ioreg motion sensor payload format unexpected")
    row = rows[0]
    if not isinstance(row, dict):
        raise RuntimeError("ioreg motion sensor row format unexpected")
    return row


class MacOSThermalTemperatureProvider:
    """Best-effort thermal sensor from AppleSmartBattery temperature field."""

    def read(self) -> tuple[object, str]:
        battery = _read_smart_battery_dict()
        raw = battery.get("Temperature")
        if raw is None:
            raise RuntimeError("battery temperature field unavailable")
        # AppleSmartBattery Temperature is tenths of Kelvin.
        temp_c = (float(raw) / 10.0) - 273.15
        return round(temp_c, 2), "C"


class MacOSPowerVoltageCurrentProvider:
    """Voltage/current sample from AppleSmartBattery."""

    def read(self) -> tuple[object, str]:
        battery = _read_smart_battery_dict()
        voltage_mv = battery.get("Voltage")
        amperage_ma = battery.get("Amperage")
        if voltage_mv is None or amperage_ma is None:
            raise RuntimeError("battery voltage/current fields unavailable")
        voltage_v = float(voltage_mv) / 1000.0
        current_a = float(amperage_ma) / 1000.0
        return {"voltage_v": round(voltage_v, 3), "current_a": round(current_a, 3)}, "mixed"


class MacOSMotionProvider:
    """Best-effort accelerometer/motion vector from AppleSMCMotionSensor."""

    def read(self) -> tuple[object, str]:
        motion = _read_motion_sensor_dict()
        x = motion.get("X")
        y = motion.get("Y")
        z = motion.get("Z")
        if x is None or y is None or z is None:
            raise RuntimeError("motion sensor X/Y/Z fields unavailable")
        return {"x": float(x), "y": float(y), "z": float(z)}, "raw"
