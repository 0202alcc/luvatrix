from __future__ import annotations

from collections import deque
import threading

from luvatrix_core.core.hdi_thread import HDIEvent, HDIEventSource


_EVENT_LOCK = threading.Lock()
_EVENTS: deque[HDIEvent] = deque(maxlen=4096)
_NEXT_ID = 1
_TELEMETRY = {
    "enqueued": 0,
    "polled": 0,
    "dropped": 0,
    "active_touches": 0,
    "last_phase": "",
}
_ACTIVE_TOUCH_IDS: set[int] = set()


def enqueue_native_touch_event(
    touch_id: int,
    phase: str,
    x: float,
    y: float,
    *,
    force: float | None = None,
    major_radius: float | None = None,
    tap_count: int | None = None,
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
    if tap_count is not None:
        payload["tap_count"] = int(tap_count)
    _enqueue("touch", "touch", payload)


def enqueue_native_touch_events(events: list[dict[str, object]]) -> None:
    for event in events:
        enqueue_native_touch_event(
            int(event.get("touch_id", 0)),
            str(event.get("phase", "move")),
            float(event.get("x", 0.0)),
            float(event.get("y", 0.0)),
            force=None if event.get("force") is None else float(event["force"]),
            major_radius=None if event.get("major_radius") is None else float(event["major_radius"]),
            tap_count=None if event.get("tap_count") is None else int(event["tap_count"]),
        )


def enqueue_touch_event(event_type: str, x: float, y: float, *, phase: str, touch_id: int = 0) -> None:
    """Compatibility shim for the first iOS bridge; prefer enqueue_native_touch_event."""
    if event_type == "touch":
        enqueue_native_touch_event(touch_id, phase, x, y)
        return
    payload = {
        "x": float(x),
        "y": float(y),
        "touch_id": int(touch_id),
        "button": 0,
        "phase": str(phase),
    }
    _enqueue("mouse", event_type, payload)


def ios_touch_telemetry() -> dict[str, object]:
    with _EVENT_LOCK:
        return dict(_TELEMETRY)


def _enqueue(device: str, event_type: str, payload: dict[str, object]) -> None:
    global _NEXT_ID
    with _EVENT_LOCK:
        if len(_EVENTS) == _EVENTS.maxlen:
            _TELEMETRY["dropped"] = int(_TELEMETRY["dropped"]) + 1
        event_id = _NEXT_ID
        _NEXT_ID += 1
        import time

        if device == "touch":
            touch_id = int(payload.get("touch_id", 0))
            phase = str(payload.get("phase", ""))
            if phase in ("down", "move"):
                _ACTIVE_TOUCH_IDS.add(touch_id)
            elif phase in ("up", "cancel"):
                _ACTIVE_TOUCH_IDS.discard(touch_id)
            _TELEMETRY["active_touches"] = len(_ACTIVE_TOUCH_IDS)
            _TELEMETRY["last_phase"] = phase
        _TELEMETRY["enqueued"] = int(_TELEMETRY["enqueued"]) + 1
        _EVENTS.append(
            HDIEvent(
                event_id=event_id,
                ts_ns=time.time_ns(),
                window_id="ios.main",
                device=device,  # type: ignore[arg-type]
                event_type=event_type,
                status="OK",
                payload=payload,
            )
        )


class IOSUIKitHDISource(HDIEventSource):
    """Polls touch events enqueued by the UIKit view bridge."""

    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        _ = ts_ns
        if not window_active:
            return []
        out: list[HDIEvent] = []
        with _EVENT_LOCK:
            while _EVENTS:
                out.append(_EVENTS.popleft())
            _TELEMETRY["polled"] = int(_TELEMETRY["polled"]) + len(out)
        return out
