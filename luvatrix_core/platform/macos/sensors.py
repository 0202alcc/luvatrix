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


def _read_system_profiler_rows(data_type: str) -> list[dict[str, object]]:
    proc = subprocess.run(
        ["system_profiler", data_type, "-xml"],
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"system_profiler {data_type} query failed")
    payload = proc.stdout
    if not payload:
        raise RuntimeError(f"system_profiler {data_type} returned empty payload")
    rows = plistlib.loads(payload)
    if not isinstance(rows, list):
        raise RuntimeError(f"system_profiler {data_type} payload format unexpected")
    out: list[dict[str, object]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(row)
    return out


def _collect_items(node: object) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    if isinstance(node, dict):
        out.append(node)
        for v in node.values():
            out.extend(_collect_items(v))
    elif isinstance(node, list):
        for x in node:
            out.extend(_collect_items(x))
    return out


def _is_truthy_audio_flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"spaudio_yes", "yes", "true", "1"}
    return False


def _item_has_io_flag(item: dict[str, object], io_kind: str) -> bool:
    needle = io_kind.lower()
    for key, value in item.items():
        key_l = str(key).lower()
        if needle not in key_l:
            continue
        if _is_truthy_audio_flag(value):
            return True
    return False


def _item_is_default_io(item: dict[str, object], io_kind: str) -> bool:
    needle = io_kind.lower()
    for key, value in item.items():
        key_l = str(key).lower()
        if "default" not in key_l or needle not in key_l:
            continue
        if _is_truthy_audio_flag(value):
            return True
    return False


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


class MacOSCameraDeviceProvider:
    """Reports camera device availability metadata (no frame data)."""

    def read(self) -> tuple[object, str]:
        rows = _read_system_profiler_rows("SPCameraDataType")
        items = _collect_items(rows)
        device_count = 0
        for item in items:
            if "_name" in item:
                device_count += 1
        return {"available": device_count > 0, "device_count": device_count}, "metadata"


class MacOSMicrophoneDeviceProvider:
    """Reports microphone availability metadata (no captured audio)."""

    def read(self) -> tuple[object, str]:
        rows = _read_system_profiler_rows("SPAudioDataType")
        items = _collect_items(rows)
        input_names: set[str] = set()
        default_present = False
        for idx, item in enumerate(items):
            if _item_is_default_io(item, "input"):
                default_present = True
            if _item_has_io_flag(item, "input"):
                input_names.add(str(item.get("_name", f"<unnamed-input-device-{idx}>")))
        if not input_names:
            # Fallback for profiles that don't expose explicit input flags.
            for idx, item in enumerate(items):
                name = str(item.get("_name", "")).lower()
                if "microphone" in name or "mic" in name:
                    input_names.add(str(item.get("_name", f"<unnamed-input-device-{idx}>")))
        input_devices = len(input_names)
        return {
            "available": input_devices > 0,
            "device_count": input_devices,
            "default_present": default_present,
        }, "metadata"


class MacOSSpeakerDeviceProvider:
    """Reports speaker/output availability metadata (no output capture)."""

    def read(self) -> tuple[object, str]:
        rows = _read_system_profiler_rows("SPAudioDataType")
        items = _collect_items(rows)
        output_names: set[str] = set()
        default_present = False
        for idx, item in enumerate(items):
            if _item_is_default_io(item, "output"):
                default_present = True
            if _item_has_io_flag(item, "output"):
                output_names.add(str(item.get("_name", f"<unnamed-output-device-{idx}>")))
        if not output_names:
            # Fallback for profiles that don't expose explicit output flags.
            for idx, item in enumerate(items):
                name = str(item.get("_name", "")).lower()
                if any(token in name for token in ("speaker", "output", "headphone", "airpods")):
                    output_names.add(str(item.get("_name", f"<unnamed-output-device-{idx}>")))
        output_devices = len(output_names)
        return {
            "available": output_devices > 0,
            "device_count": output_devices,
            "default_present": default_present,
        }, "metadata"
