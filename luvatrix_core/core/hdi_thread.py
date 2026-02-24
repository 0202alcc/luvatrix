from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
import threading
import time
from typing import Callable, Literal, Protocol


HDIDevice = Literal["keyboard", "mouse", "trackpad"]
HDIStatus = Literal["OK", "NOT_DETECTED", "UNAVAILABLE", "DENIED"]


@dataclass(frozen=True)
class HDIEvent:
    event_id: int
    ts_ns: int
    window_id: str
    device: HDIDevice
    event_type: str
    status: HDIStatus
    payload: object | None


class HDIEventSource(Protocol):
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        ...


class HDIThread:
    """Bounded HDI event collector with move coalescing and keyboard safety guarantees."""

    def __init__(
        self,
        source: HDIEventSource,
        max_queue_size: int = 1024,
        poll_interval_s: float = 1 / 240,
        window_active_provider: Callable[[], bool] | None = None,
        window_geometry_provider: Callable[[], tuple[float, float, float, float]] | None = None,
    ) -> None:
        if max_queue_size <= 0:
            raise ValueError("max_queue_size must be > 0")
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")
        self._source = source
        self._max_queue_size = max_queue_size
        self._poll_interval_s = poll_interval_s
        self._window_active_provider = window_active_provider or (lambda: True)
        self._window_geometry_provider = window_geometry_provider or (lambda: (0.0, 0.0, 1.0, 1.0))
        self._queue: deque[HDIEvent] = deque()
        self._lock = threading.Lock()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error: Exception | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._run, name="luvatrix-hdi", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def poll_events(self, max_events: int) -> list[HDIEvent]:
        if max_events <= 0:
            raise ValueError("max_events must be > 0")
        out: list[HDIEvent] = []
        with self._lock:
            while self._queue and len(out) < max_events:
                out.append(self._queue.popleft())
        return out

    def pending_count(self) -> int:
        with self._lock:
            return len(self._queue)

    @property
    def last_error(self) -> Exception | None:
        return self._last_error

    def _run(self) -> None:
        while self._running.is_set():
            try:
                active = bool(self._window_active_provider())
                events = self._source.poll(window_active=active, ts_ns=time.time_ns())
                for event in events:
                    self._enqueue(self._normalize_event(event, active))
            except Exception as exc:  # noqa: BLE001
                self._last_error = exc
                self._running.clear()
                break
            time.sleep(self._poll_interval_s)

    def _normalize_event(self, event: HDIEvent, active: bool) -> HDIEvent:
        if event.device in ("mouse", "trackpad"):
            return self._normalize_pointer_event(event, active)
        if active:
            return event
        if event.device == "keyboard":
            return replace(event, status="NOT_DETECTED", payload=None)
        return event

    def _normalize_pointer_event(self, event: HDIEvent, active: bool) -> HDIEvent:
        if not active:
            return replace(event, status="NOT_DETECTED", payload=None)
        requires_position = _requires_pointer_position(event.event_type)
        if event.payload is None:
            return replace(event, status="NOT_DETECTED", payload=None) if requires_position else event
        if not isinstance(event.payload, dict):
            return replace(event, status="NOT_DETECTED", payload=None) if requires_position else replace(
                event, payload=None
            )
        payload = dict(event.payload)
        left, top, width, height = self._window_geometry_provider()
        if width <= 0 or height <= 0:
            return replace(event, status="NOT_DETECTED", payload=None)
        x: float | None = None
        y: float | None = None
        if "screen_x" in payload and "screen_y" in payload:
            try:
                x = float(payload["screen_x"]) - float(left)
                y = float(payload["screen_y"]) - float(top)
            except (TypeError, ValueError):
                if requires_position:
                    return replace(event, status="NOT_DETECTED", payload=None)
        elif "x" in payload and "y" in payload:
            try:
                x = float(payload["x"])
                y = float(payload["y"])
            except (TypeError, ValueError):
                if requires_position:
                    return replace(event, status="NOT_DETECTED", payload=None)
        if requires_position and (x is None or y is None):
            return replace(event, status="NOT_DETECTED", payload=None)
        if x is not None and y is not None:
            if x < 0 or y < 0 or x >= float(width) or y >= float(height):
                return replace(event, status="NOT_DETECTED", payload=None)
        safe_payload: dict[str, object] = {}
        if x is not None and y is not None:
            safe_payload["x"] = x
            safe_payload["y"] = y
        for key in (
            "button",
            "delta_x",
            "delta_y",
            "pressure",
            "stage",
            "magnification",
            "rotation",
            "click_count",
            "phase",
        ):
            if key in payload:
                safe_payload[key] = payload[key]
        if not safe_payload and requires_position:
            return replace(event, status="NOT_DETECTED", payload=None)
        return replace(event, payload=safe_payload, status="OK")

    def _enqueue(self, event: HDIEvent) -> None:
        with self._lock:
            if _is_move_event(event):
                idx = self._find_last_move_index(event)
                if idx is not None:
                    self._queue[idx] = event
                    return
            if len(self._queue) < self._max_queue_size:
                self._queue.append(event)
                return
            if _is_keyboard_transition(event):
                if self._drop_one_non_keyboard():
                    self._queue.append(event)
                    return
                raise RuntimeError("HDI queue saturated with keyboard transitions; refusing to drop keyboard events")
            if _is_move_event(event):
                return
            self._queue.popleft()
            self._queue.append(event)

    def _find_last_move_index(self, incoming: HDIEvent) -> int | None:
        for i in range(len(self._queue) - 1, -1, -1):
            e = self._queue[i]
            if _is_move_event(e) and e.device == incoming.device and e.window_id == incoming.window_id:
                return i
        return None

    def _drop_one_non_keyboard(self) -> bool:
        for i, event in enumerate(self._queue):
            if not _is_keyboard_transition(event):
                del self._queue[i]
                return True
        return False


def _is_keyboard_transition(event: HDIEvent) -> bool:
    return event.device == "keyboard" and event.event_type in ("key_down", "key_up")


def _is_move_event(event: HDIEvent) -> bool:
    return event.event_type in ("pointer_move", "mouse_move", "trackpad_move")


def _requires_pointer_position(event_type: str) -> bool:
    return event_type in ("pointer_move", "mouse_move", "trackpad_move", "click", "tap", "scroll")
