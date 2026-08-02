from __future__ import annotations

from collections import deque
import json
import struct
import threading
import time
from typing import Any

from luvatrix_core.core.hdi_thread import HDIEvent, HDIEventSource


_EVENT_LOCK = threading.Lock()
_EVENTS: deque[HDIEvent] = deque(maxlen=4096)
_NEXT_ID = 1
_ACTIVE_TOUCH_IDS: set[int] = set()
_TELEMETRY: dict[str, object] = {
    "enqueued": 0,
    "polled": 0,
    "dropped": 0,
    "active_touches": 0,
    "last_phase": "",
    "last_key": "",
}

_BINARY_HEADER = struct.Struct("<4sHH")
_BINARY_PACKET = struct.Struct("<BBBBiffffii32s")
_BINARY_MAGIC = b"LVXI"
_BINARY_VERSION = 1
_BINARY_DEVICE_TOUCH = 1
_BINARY_DEVICE_KEYBOARD = 2
_BINARY_TOUCH_PHASES = {0: "move", 1: "down", 2: "up", 3: "cancel"}
_BINARY_KEY_PHASES = {1: "down", 2: "up"}


def clear_android_input_events() -> None:
    global _NEXT_ID
    with _EVENT_LOCK:
        _EVENTS.clear()
        _ACTIVE_TOUCH_IDS.clear()
        _NEXT_ID = 1
        _TELEMETRY.update(
            {
                "enqueued": 0,
                "polled": 0,
                "dropped": 0,
                "active_touches": 0,
                "last_phase": "",
                "last_key": "",
            }
        )


def enqueue_native_touch_event(
    touch_id: int,
    phase: str,
    x: float,
    y: float,
    *,
    force: float | None = None,
    major_radius: float | None = None,
    tool_type: str | None = None,
) -> None:
    payload: dict[str, object] = {
        "touch_id": int(touch_id),
        "phase": str(phase),
        "x": float(x),
        "y": float(y),
    }
    if force is not None:
        payload["force"] = float(force)
    if major_radius is not None:
        payload["major_radius"] = float(major_radius)
    if tool_type:
        payload["tool_type"] = str(tool_type)
    _enqueue("touch", "touch", payload)


def enqueue_native_key_event(key: str, phase: str, *, scan_code: int | None = None) -> None:
    payload: dict[str, object] = {"key": str(key), "phase": str(phase)}
    if scan_code is not None:
        payload["scan_code"] = int(scan_code)
    normalized_phase = str(phase).lower()
    event_type = "key_up" if normalized_phase == "up" else "key_down"
    _enqueue("keyboard", event_type, payload)


def android_input_telemetry() -> dict[str, object]:
    with _EVENT_LOCK:
        return dict(_TELEMETRY)


def _enqueue(device: str, event_type: str, payload: dict[str, object]) -> None:
    global _NEXT_ID
    with _EVENT_LOCK:
        if len(_EVENTS) == _EVENTS.maxlen:
            _TELEMETRY["dropped"] = int(_TELEMETRY["dropped"]) + 1
        event_id = _NEXT_ID
        _NEXT_ID += 1
        if device == "touch":
            touch_id = int(payload.get("touch_id", 0))
            phase = str(payload.get("phase", ""))
            if phase in ("down", "move"):
                _ACTIVE_TOUCH_IDS.add(touch_id)
            elif phase in ("up", "cancel"):
                _ACTIVE_TOUCH_IDS.discard(touch_id)
            _TELEMETRY["active_touches"] = len(_ACTIVE_TOUCH_IDS)
            _TELEMETRY["last_phase"] = phase
        elif device == "keyboard":
            _TELEMETRY["last_key"] = str(payload.get("key", ""))
        _TELEMETRY["enqueued"] = int(_TELEMETRY["enqueued"]) + 1
        _EVENTS.append(
            HDIEvent(
                event_id=event_id,
                ts_ns=time.time_ns(),
                window_id="android.main",
                device=device,  # type: ignore[arg-type]
                event_type=event_type,
                status="OK",
                payload=payload,
            )
        )


class AndroidHDISource(HDIEventSource):
    """Polls input events enqueued by the Android view bridge."""

    def __init__(
        self,
        input_bridge: object | None = None,
        *,
        logical_width: float | None = None,
        logical_height: float | None = None,
    ) -> None:
        self.input_bridge = input_bridge
        self.logical_width = logical_width
        self.logical_height = logical_height

    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        _ = ts_ns
        if not window_active:
            return []
        self._drain_input_bridge()
        out: list[HDIEvent] = []
        with _EVENT_LOCK:
            while _EVENTS:
                out.append(_EVENTS.popleft())
            _TELEMETRY["polled"] = int(_TELEMETRY["polled"]) + len(out)
        return out

    def _drain_input_bridge(self) -> None:
        if self.input_bridge is None:
            return
        drain_binary = getattr(self.input_bridge, "drainInputEventsBinary", None) or getattr(
            self.input_bridge, "drain_input_events_binary", None
        )
        if callable(drain_binary):
            try:
                raw_binary = drain_binary()
            except Exception:
                return
            for event in _coalesce_touch_moves(_decode_binary_input_events(raw_binary)):
                self._scale_touch_event(event)
                _enqueue_bridge_event(event)
            return
        drain = getattr(self.input_bridge, "drainInputEventsJson", None) or getattr(
            self.input_bridge, "drain_input_events_json", None
        )
        if not callable(drain):
            return
        try:
            raw_events = drain()
        except Exception:
            return
        parsed: list[dict[str, Any]] = []
        for raw in raw_events or ():
            try:
                event = json.loads(str(raw))
            except Exception:
                continue
            if not isinstance(event, dict):
                continue
            parsed.append(event)
        for event in _coalesce_touch_moves(parsed):
            self._scale_touch_event(event)
            _enqueue_bridge_event(event)

    def _scale_touch_event(self, event: dict[str, Any]) -> None:
        if str(event.get("device", "")) != "touch" or self.input_bridge is None:
            return
        logical_width = _float(self.logical_width, 0.0)
        logical_height = _float(self.logical_height, 0.0)
        if logical_width <= 0.0 or logical_height <= 0.0:
            return
        try:
            view_width = float(self.input_bridge.getWidth())
            view_height = float(self.input_bridge.getHeight())
        except Exception:
            return
        if view_width <= 0.0 or view_height <= 0.0:
            return
        event["x"] = _float(event.get("x"), 0.0) * (logical_width / view_width)
        event["y"] = _float(event.get("y"), 0.0) * (logical_height / view_height)
        event["major_radius"] = _float(event.get("major_radius"), 0.0) * min(
            logical_width / view_width,
            logical_height / view_height,
        )


def _enqueue_bridge_event(event: dict[str, Any]) -> None:
    device = str(event.get("device", ""))
    phase = str(event.get("phase", ""))
    if device == "touch":
        enqueue_native_touch_event(
            _int(event.get("touch_id"), 0),
            phase,
            _float(event.get("x"), 0.0),
            _float(event.get("y"), 0.0),
            force=_float(event.get("force"), 0.0),
            major_radius=_float(event.get("major_radius"), 0.0),
            tool_type=str(event.get("tool_type", "")),
        )
    elif device == "keyboard":
        enqueue_native_key_event(
            str(event.get("key", "")),
            phase,
            scan_code=_int(event.get("scan_code"), 0),
        )


def _coalesce_touch_moves(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pending_moves: dict[int, dict[str, Any]] = {}

    def flush_moves() -> None:
        nonlocal pending_moves
        if pending_moves:
            out.extend(pending_moves.values())
            pending_moves = {}

    for event in events:
        device = str(event.get("device", ""))
        phase = str(event.get("phase", "")).lower()
        if device == "touch" and phase == "move":
            pending_moves[_int(event.get("touch_id"), 0)] = event
            continue
        flush_moves()
        out.append(event)
    flush_moves()
    return out


def _decode_binary_input_events(raw: object) -> list[dict[str, Any]]:
    try:
        data = bytes(raw)
    except (TypeError, ValueError):
        return []
    if len(data) < _BINARY_HEADER.size:
        return []
    magic, version, count = _BINARY_HEADER.unpack_from(data)
    if magic != _BINARY_MAGIC or version != _BINARY_VERSION:
        return []
    expected_size = _BINARY_HEADER.size + int(count) * _BINARY_PACKET.size
    if len(data) != expected_size:
        return []

    out: list[dict[str, Any]] = []
    offset = _BINARY_HEADER.size
    for _ in range(int(count)):
        (
            device,
            phase_code,
            tool_type,
            key_length,
            touch_id,
            x,
            y,
            force,
            major_radius,
            scan_code,
            _key_code,
            key_raw,
        ) = _BINARY_PACKET.unpack_from(data, offset)
        offset += _BINARY_PACKET.size
        if device == _BINARY_DEVICE_TOUCH:
            phase = _BINARY_TOUCH_PHASES.get(int(phase_code))
            if phase is None:
                continue
            out.append(
                {
                    "device": "touch",
                    "touch_id": int(touch_id),
                    "phase": phase,
                    "x": float(x),
                    "y": float(y),
                    "force": float(force),
                    "major_radius": float(major_radius),
                    "tool_type": str(int(tool_type)),
                }
            )
        elif device == _BINARY_DEVICE_KEYBOARD:
            phase = _BINARY_KEY_PHASES.get(int(phase_code))
            if phase is None:
                continue
            key_size = min(len(key_raw), int(key_length))
            key = key_raw[:key_size].decode("utf-8", errors="replace")
            out.append(
                {
                    "device": "keyboard",
                    "phase": phase,
                    "key": key,
                    "scan_code": int(scan_code),
                }
            )
    return out


def _float(value: object, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _int(value: object, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
