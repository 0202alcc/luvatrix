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
        hold_threshold_s: float = 0.35,
        hold_tick_interval_s: float = 0.10,
        double_press_threshold_s: float = 0.25,
        window_active_provider: Callable[[], bool] | None = None,
        window_geometry_provider: Callable[[], tuple[float, float, float, float]] | None = None,
        target_extent_provider: Callable[[], tuple[float, float]] | None = None,
        source_content_rect_provider: Callable[[], tuple[float, float, float, float]] | None = None,
    ) -> None:
        if max_queue_size <= 0:
            raise ValueError("max_queue_size must be > 0")
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")
        if hold_threshold_s <= 0:
            raise ValueError("hold_threshold_s must be > 0")
        if hold_tick_interval_s <= 0:
            raise ValueError("hold_tick_interval_s must be > 0")
        if double_press_threshold_s <= 0:
            raise ValueError("double_press_threshold_s must be > 0")
        self._source = source
        self._max_queue_size = max_queue_size
        self._poll_interval_s = poll_interval_s
        self._hold_threshold_s = hold_threshold_s
        self._hold_tick_interval_s = hold_tick_interval_s
        self._double_press_threshold_s = double_press_threshold_s
        self._window_active_provider = window_active_provider or (lambda: True)
        self._window_geometry_provider = window_geometry_provider or (lambda: (0.0, 0.0, 1.0, 1.0))
        self._target_extent_provider = target_extent_provider
        self._source_content_rect_provider = source_content_rect_provider
        self._queue: deque[HDIEvent] = deque()
        self._lock = threading.Lock()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error: Exception | None = None
        self._keyboard_state: dict[str, _KeyPressState] = {}
        self._last_tap_up_ns: dict[str, int] = {}
        self._last_window_active = True
        self._next_synth_event_id = 2_000_000_000

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
                if not active and self._last_window_active:
                    for event in self._emit_keyboard_cancel_events(ts_ns=time.time_ns()):
                        self._enqueue(event)
                events = self._source.poll(window_active=active, ts_ns=time.time_ns())
                for event in events:
                    for normalized in self._normalize_events(event, active):
                        self._enqueue(normalized)
                if active:
                    for event in self._emit_hold_events(ts_ns=time.time_ns()):
                        self._enqueue(event)
                self._last_window_active = active
            except Exception as exc:  # noqa: BLE001
                self._last_error = exc
                self._running.clear()
                break
            time.sleep(self._poll_interval_s)

    def _normalize_events(self, event: HDIEvent, active: bool) -> list[HDIEvent]:
        if event.device == "keyboard":
            return self._normalize_keyboard_events(event, active)
        if event.device in ("mouse", "trackpad"):
            return [self._normalize_pointer_event(event, active)]
        if active:
            return [event]
        return [replace(event, status="NOT_DETECTED", payload=None)]

    def _normalize_keyboard_events(self, event: HDIEvent, active: bool) -> list[HDIEvent]:
        if not active:
            return [replace(event, status="NOT_DETECTED", payload=None)]
        payload = event.payload if isinstance(event.payload, dict) else {}
        key = str(payload.get("key", "")).strip()
        if not key:
            return [
                replace(
                    event,
                    event_type="press",
                    payload={"phase": "cancel", "key": ""},
                )
            ]

        event_type = event.event_type
        ts_ns = time.time_ns()
        out: list[HDIEvent] = []
        state = self._keyboard_state.get(key)
        if event_type == "key_down":
            if state is not None and state.is_down:
                out.append(self._press_event(event, key=key, phase="repeat", active_keys=self._active_keys()))
                return out
            self._keyboard_state[key] = _KeyPressState(
                is_down=True,
                down_ts_ns=ts_ns,
                hold_started=False,
                last_hold_tick_ns=ts_ns,
            )
            out.append(self._press_event(event, key=key, phase="down", active_keys=self._active_keys()))
            return out

        if event_type == "key_up":
            self._keyboard_state.pop(key, None)
            active_keys = self._active_keys()
            out.append(self._press_event(event, key=key, phase="up", active_keys=active_keys))
            if state is not None and state.hold_started:
                out.append(self._press_event(event, key=key, phase="hold_end", active_keys=active_keys))
            last_up = self._last_tap_up_ns.get(key)
            if last_up is not None and (ts_ns - last_up) <= int(self._double_press_threshold_s * 1_000_000_000):
                out.append(self._press_event(event, key=key, phase="double", active_keys=active_keys))
            else:
                out.append(self._press_event(event, key=key, phase="single", active_keys=active_keys))
            self._last_tap_up_ns[key] = ts_ns
            return out

        # Already standardized or unknown keyboard event: normalize to press.
        phase = str(payload.get("phase", event_type))
        out.append(
            replace(
                event,
                event_type="press",
                payload={"phase": phase, "key": key, "active_keys": self._active_keys()},
            )
        )
        return out

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
            content_left, content_top, content_w, content_h = self._resolve_content_rect(width, height)
            if content_w <= 0 or content_h <= 0:
                return replace(event, status="NOT_DETECTED", payload=None)
            rel_x = x - content_left
            rel_y = y - content_top
            if rel_x < 0 or rel_y < 0 or rel_x >= content_w or rel_y >= content_h:
                return replace(event, status="NOT_DETECTED", payload=None)
            tx, ty = self._project_to_target(rel_x, rel_y, content_w, content_h)
            x = tx
            y = ty
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

    def _project_to_target(
        self,
        x: float,
        y: float,
        source_w: float,
        source_h: float,
    ) -> tuple[float, float]:
        if self._target_extent_provider is None:
            return (x, y)
        tw, th = self._target_extent_provider()
        tw = max(1.0, float(tw))
        th = max(1.0, float(th))
        sw = max(1.0, float(source_w))
        sh = max(1.0, float(source_h))
        return (_remap_axis(x, sw, tw), _remap_axis(y, sh, th))

    def _resolve_content_rect(self, width: float, height: float) -> tuple[float, float, float, float]:
        if self._source_content_rect_provider is None:
            return (0.0, 0.0, float(width), float(height))
        left, top, rect_w, rect_h = self._source_content_rect_provider()
        return (float(left), float(top), float(rect_w), float(rect_h))

    def _emit_hold_events(self, ts_ns: int) -> list[HDIEvent]:
        out: list[HDIEvent] = []
        hold_threshold_ns = int(self._hold_threshold_s * 1_000_000_000)
        hold_tick_ns = int(self._hold_tick_interval_s * 1_000_000_000)
        for key, state in list(self._keyboard_state.items()):
            if not state.is_down:
                continue
            if not state.hold_started:
                if ts_ns - state.down_ts_ns >= hold_threshold_ns:
                    state.hold_started = True
                    state.last_hold_tick_ns = ts_ns
                    out.append(
                        self._synthetic_press_event(
                            ts_ns=ts_ns, key=key, phase="hold_start", active_keys=self._active_keys()
                        )
                    )
                continue
            if ts_ns - state.last_hold_tick_ns >= hold_tick_ns:
                state.last_hold_tick_ns = ts_ns
                out.append(
                    self._synthetic_press_event(
                        ts_ns=ts_ns, key=key, phase="hold_tick", active_keys=self._active_keys()
                    )
                )
        return out

    def _emit_keyboard_cancel_events(self, ts_ns: int) -> list[HDIEvent]:
        out: list[HDIEvent] = []
        for key, state in list(self._keyboard_state.items()):
            if not state.is_down:
                continue
            state.is_down = False
            self._keyboard_state.pop(key, None)
            out.append(
                self._synthetic_press_event(
                    ts_ns=ts_ns, key=key, phase="cancel", active_keys=self._active_keys()
                )
            )
        return out

    def _press_event(self, event: HDIEvent, key: str, phase: str, active_keys: list[str]) -> HDIEvent:
        base = event.payload if isinstance(event.payload, dict) else {}
        payload = {"key": key, "phase": phase, "active_keys": active_keys}
        if "code" in base:
            payload["code"] = base["code"]
        return replace(event, event_type="press", payload=payload, status="OK")

    def _synthetic_press_event(self, ts_ns: int, key: str, phase: str, active_keys: list[str]) -> HDIEvent:
        event_id = self._next_synth_event_id
        self._next_synth_event_id += 1
        return HDIEvent(
            event_id=event_id,
            ts_ns=ts_ns,
            window_id="runtime",
            device="keyboard",
            event_type="press",
            status="OK",
            payload={"key": key, "phase": phase, "active_keys": active_keys},
        )

    def _active_keys(self) -> list[str]:
        return sorted([k for k, s in self._keyboard_state.items() if s.is_down])

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
    if event.device != "keyboard":
        return False
    if event.event_type in ("key_down", "key_up"):
        return True
    if event.event_type == "press":
        return True
    return False


def _is_move_event(event: HDIEvent) -> bool:
    return event.event_type in ("pointer_move", "mouse_move", "trackpad_move")


def _requires_pointer_position(event_type: str) -> bool:
    return event_type in ("pointer_move", "mouse_move", "trackpad_move", "click", "tap", "scroll")


def _remap_axis(value: float, source_extent: float, target_extent: float) -> float:
    if source_extent <= 1.0:
        return 0.0
    ratio = float(value) / float(source_extent - 1.0)
    out = ratio * float(target_extent - 1.0)
    if out < 0.0:
        return 0.0
    if out > (target_extent - 1.0):
        return target_extent - 1.0
    return out


@dataclass
class _KeyPressState:
    is_down: bool
    down_ts_ns: int
    hold_started: bool
    last_hold_tick_ns: int
