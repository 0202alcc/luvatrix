from __future__ import annotations

import plistlib
import subprocess

from luvatrix_core.core.sensor_manager import SensorProvider, TTLCachedSensorProvider


def _read_ioreg_rows(io_class: str) -> list[dict[str, object]]:
    proc = subprocess.run(
        ["ioreg", "-r", "-c", io_class, "-a"],
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ioreg {io_class} query failed")
    payload = proc.stdout
    if not payload:
        raise RuntimeError(f"ioreg {io_class} returned empty payload")
    rows = plistlib.loads(payload)
    if not isinstance(rows, list):
        raise RuntimeError(f"ioreg {io_class} payload format unexpected")
    out: list[dict[str, object]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(row)
    return out


def _read_smart_battery_dict() -> dict[str, object]:
    rows = _read_ioreg_rows("AppleSmartBattery")
    if not rows:
        raise RuntimeError("ioreg AppleSmartBattery payload format unexpected")
    row = rows[0]
    if not isinstance(row, dict):
        raise RuntimeError("ioreg AppleSmartBattery row format unexpected")
    return row


def _read_motion_sensor_dict() -> dict[str, object]:
    rows = _read_ioreg_rows("AppleSMCMotionSensor")
    if not rows:
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


def _item_name(item: dict[str, object], idx: int, label: str) -> str:
    for key in ("_name", "IOAudioDeviceName", "IOAudioEngineDescription", "USB Product Name"):
        value = item.get(key)
        if value is not None:
            return str(value)
    return f"<unnamed-{label}-{idx}>"


def _item_numeric(item: dict[str, object], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            text = value.strip()
            if text.isdigit():
                return int(text)
    return None


def _count_camera_devices_ioreg() -> int:
    rows: list[dict[str, object]] = []
    for io_class in ("IOCameraInterface", "AppleCameraInterface"):
        try:
            rows.extend(_read_ioreg_rows(io_class))
        except Exception:  # noqa: BLE001
            continue
    unique_names = {str(row.get("_name", "")).strip() for row in rows if str(row.get("_name", "")).strip()}
    if unique_names:
        return len(unique_names)
    return len(rows)


def _probe_audio_devices_ioreg(io_kind: str) -> tuple[int, bool]:
    rows = _read_ioreg_rows("IOAudioDevice")
    items = _collect_items(rows)
    names: set[str] = set()
    default_present = False
    needle = io_kind.lower()
    for idx, item in enumerate(items):
        name = _item_name(item, idx, io_kind).lower()
        input_count = _item_numeric(item, ("IOAudioEngineNumInputs", "IOAudioInputChannels"))
        output_count = _item_numeric(item, ("IOAudioEngineNumOutputs", "IOAudioOutputChannels"))
        if needle == "input":
            has_kind = (input_count is not None and input_count > 0) or ("mic" in name or "microphone" in name)
        else:
            has_kind = (output_count is not None and output_count > 0) or any(
                token in name for token in ("speaker", "headphone", "airpods", "output")
            )
        if not has_kind:
            continue
        names.add(_item_name(item, idx, io_kind))
        for key, value in item.items():
            key_l = str(key).lower()
            if "default" in key_l and needle in key_l and _is_truthy_audio_flag(value):
                default_present = True
    return (len(names), default_present)


def _probe_audio_devices_system_profiler(io_kind: str) -> tuple[int, bool]:
    rows = _read_system_profiler_rows("SPAudioDataType")
    items = _collect_items(rows)
    names: set[str] = set()
    default_present = False
    for idx, item in enumerate(items):
        if _item_is_default_io(item, io_kind):
            default_present = True
        if _item_has_io_flag(item, io_kind):
            names.add(_item_name(item, idx, io_kind))
    if not names:
        for idx, item in enumerate(items):
            raw_name = str(item.get("_name", "")).strip()
            if not raw_name:
                continue
            name = raw_name.lower()
            if io_kind == "input":
                if "microphone" in name or "mic" in name:
                    names.add(raw_name)
            elif any(token in name for token in ("speaker", "output", "headphone", "airpods")):
                names.add(raw_name)
    return (len(names), default_present)


class MacOSThermalTemperatureProvider:
    """Best-effort thermal sensor from AppleSmartBattery temperature field."""

    path_class = "fast_path"

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

    path_class = "fast_path"

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

    path_class = "fast_path"

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

    path_class = "cached_path"

    def read(self) -> tuple[object, str]:
        device_count = _count_camera_devices_ioreg()
        if device_count == 0:
            rows = _read_system_profiler_rows("SPCameraDataType")
            items = _collect_items(rows)
            device_count = sum(1 for item in items if "_name" in item)
        return {"available": device_count > 0, "device_count": device_count}, "metadata"


class MacOSMicrophoneDeviceProvider:
    """Reports microphone availability metadata (no captured audio)."""

    path_class = "cached_path"

    def read(self) -> tuple[object, str]:
        try:
            input_devices, default_present = _probe_audio_devices_ioreg("input")
        except Exception:  # noqa: BLE001
            input_devices, default_present = _probe_audio_devices_system_profiler("input")
        if input_devices == 0:
            input_devices, default_present = _probe_audio_devices_system_profiler("input")
        return {
            "available": input_devices > 0,
            "device_count": input_devices,
            "default_present": default_present,
        }, "metadata"


class MacOSSpeakerDeviceProvider:
    """Reports speaker/output availability metadata (no output capture)."""

    path_class = "cached_path"

    def read(self) -> tuple[object, str]:
        try:
            output_devices, default_present = _probe_audio_devices_ioreg("output")
        except Exception:  # noqa: BLE001
            output_devices, default_present = _probe_audio_devices_system_profiler("output")
        if output_devices == 0:
            output_devices, default_present = _probe_audio_devices_system_profiler("output")
        return {
            "available": output_devices > 0,
            "device_count": output_devices,
            "default_present": default_present,
        }, "metadata"


def make_default_macos_sensor_providers(metadata_ttl_s: float = 5.0) -> dict[str, SensorProvider]:
    return {
        "thermal.temperature": MacOSThermalTemperatureProvider(),
        "power.voltage_current": MacOSPowerVoltageCurrentProvider(),
        "sensor.motion": MacOSMotionProvider(),
        "camera.device": TTLCachedSensorProvider(MacOSCameraDeviceProvider(), ttl_s=metadata_ttl_s),
        "microphone.device": TTLCachedSensorProvider(MacOSMicrophoneDeviceProvider(), ttl_s=metadata_ttl_s),
        "speaker.device": TTLCachedSensorProvider(MacOSSpeakerDeviceProvider(), ttl_s=metadata_ttl_s),
    }
