from __future__ import annotations

from collections import deque
import json
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
        drain = getattr(self.input_bridge, "drainInputEventsJson", None) or getattr(
            self.input_bridge, "drain_input_events_json", None
        )
        if not callable(drain):
            return
        try:
            raw_events = drain()
        except Exception:
            return
        for raw in raw_events or ():
            try:
                event = json.loads(str(raw))
            except Exception:
                continue
            if not isinstance(event, dict):
                continue
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
