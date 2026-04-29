from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
import math
import threading
import time
from typing import Callable, Literal, Protocol


HDIDevice = Literal["keyboard", "mouse", "trackpad", "touch"]
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
        self._touch_state: dict[int, _TouchPoint] = {}
        self._last_gesture: _GestureState | None = None
        self._last_tap_up_ns: dict[str, int] = {}
        self._last_window_active = True
        self._next_synth_event_id = 2_000_000_000
        self._latency_samples_ns: deque[int] = deque(maxlen=4096)
        self._telemetry_window: dict[str, int] = {
            "events_enqueued": 0,
            "events_dequeued": 0,
            "events_dropped": 0,
            "events_coalesced": 0,
            "queue_latency_ns_max": 0,
        }

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
        now_ns = time.time_ns()
        with self._lock:
            while self._queue and len(out) < max_events:
                event = self._queue.popleft()
                out.append(event)
                self._telemetry_window["events_dequeued"] += 1
                latency_ns = max(0, int(now_ns - int(event.ts_ns)))
                self._latency_samples_ns.append(latency_ns)
                if latency_ns > int(self._telemetry_window.get("queue_latency_ns_max", 0)):
                    self._telemetry_window["queue_latency_ns_max"] = latency_ns
        return out

    def pending_count(self) -> int:
        with self._lock:
            return len(self._queue)

    def consume_telemetry(self) -> dict[str, int]:
        with self._lock:
            samples = sorted(int(v) for v in self._latency_samples_ns)
            self._latency_samples_ns.clear()
            out = dict(self._telemetry_window)
            out["queue_latency_ns_p95"] = _percentile_int(samples, 95.0)
            self._telemetry_window = {
                "events_enqueued": 0,
                "events_dequeued": 0,
                "events_dropped": 0,
                "events_coalesced": 0,
                "queue_latency_ns_max": 0,
            }
        return out

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
        if event.device == "touch":
            return self._normalize_touch_events(event, active)
        if active:
            return [event]
        return [replace(event, status="NOT_DETECTED", payload=None)]

    def _normalize_touch_events(self, event: HDIEvent, active: bool) -> list[HDIEvent]:
        if not active:
            return [replace(event, status="NOT_DETECTED", payload=None)]
        if event.payload is None or not isinstance(event.payload, dict):
            return [replace(event, status="NOT_DETECTED", payload=None)]
        payload = dict(event.payload)
        phase = str(payload.get("phase", event.event_type)).lower()
        if phase not in ("down", "move", "up", "cancel"):
            phase = "move" if event.event_type in ("pointer_move", "touch_move") else phase
        try:
            touch_id = int(payload.get("touch_id", 0))
        except (TypeError, ValueError):
            return [replace(event, status="NOT_DETECTED", payload=None)]
        normalized = self._normalize_position_payload(event, payload, requires_position=True)
        if normalized.status != "OK" or not isinstance(normalized.payload, dict):
            if phase in ("up", "cancel"):
                self._touch_state.pop(touch_id, None)
            return [normalized]

        safe_payload = dict(normalized.payload)
        safe_payload["touch_id"] = touch_id
        safe_payload["phase"] = phase
        for key in ("force", "major_radius", "tap_count"):
            if key in payload:
                safe_payload[key] = payload[key]
        touch_event = replace(normalized, device="touch", event_type="touch", payload=safe_payload, status="OK")

        before_count = len(self._touch_state)
        if phase in ("down", "move"):
            self._touch_state[touch_id] = _TouchPoint(
                touch_id=touch_id,
                x=float(safe_payload["x"]),
                y=float(safe_payload["y"]),
            )
        elif phase in ("up", "cancel"):
            self._touch_state.pop(touch_id, None)

        out = [touch_event]
        gesture = self._synthesize_touch_gesture(event, phase=phase, before_count=before_count)
        if gesture is not None:
            out.extend(gesture)
        return out

    def _normalize_keyboard_events(self, event: HDIEvent, active: bool) -> list[HDIEvent]:
        if not active:
            return [replace(event, status="NOT_DETECTED", payload=None)]
        payload = event.payload if isinstance(event.payload, dict) else {}
        raw_key = payload.get("key", "")
        key = "" if raw_key is None else str(raw_key)
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
        return self._normalize_position_payload(event, payload, requires_position=requires_position)

    def _normalize_position_payload(
        self,
        event: HDIEvent,
        payload: dict[str, object],
        *,
        requires_position: bool,
    ) -> HDIEvent:
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
            "touch_id",
        ):
            if key in payload:
                safe_payload[key] = payload[key]
        if not safe_payload and requires_position:
            return replace(event, status="NOT_DETECTED", payload=None)
        return replace(event, payload=safe_payload, status="OK")

    def _synthesize_touch_gesture(
        self,
        event: HDIEvent,
        *,
        phase: str,
        before_count: int,
    ) -> list[HDIEvent] | None:
        if len(self._touch_state) < 2:
            if before_count >= 2 and self._last_gesture is not None:
                final = self._gesture_events(event, phase="up", current=self._last_gesture, previous=self._last_gesture)
                self._last_gesture = None
                return final
            self._last_gesture = None
            return None

        current = _gesture_state_from_touches(self._touch_state)
        previous = self._last_gesture or current
        gesture_phase = "down" if before_count < 2 or self._last_gesture is None else phase
        if gesture_phase in ("up", "cancel") and len(self._touch_state) >= 2:
            gesture_phase = "move"
        if gesture_phase not in ("down", "move", "up", "cancel"):
            gesture_phase = "move"
        self._last_gesture = current
        return self._gesture_events(event, phase=gesture_phase, current=current, previous=previous)

    def _gesture_events(
        self,
        event: HDIEvent,
        *,
        phase: str,
        current: "_GestureState",
        previous: "_GestureState",
    ) -> list[HDIEvent]:
        translation_x = current.centroid_x - previous.centroid_x
        translation_y = current.centroid_y - previous.centroid_y
        scale = 1.0 if previous.distance <= 1e-6 else current.distance / previous.distance
        rotation = current.angle - previous.angle
        base_payload = {
            "phase": phase,
            "centroid_x": current.centroid_x,
            "centroid_y": current.centroid_y,
            "translation_x": translation_x,
            "translation_y": translation_y,
            "scale": scale,
            "rotation": rotation,
            "touch_count": len(self._touch_state),
        }
        out: list[HDIEvent] = []
        for kind in ("pan", "pinch", "rotate"):
            event_id = self._next_synth_event_id
            self._next_synth_event_id += 1
            payload = dict(base_payload)
            payload["kind"] = kind
            out.append(
                HDIEvent(
                    event_id=event_id,
                    ts_ns=event.ts_ns,
                    window_id=event.window_id,
                    device="touch",
                    event_type="gesture",
                    status="OK",
                    payload=payload,
                )
            )
        return out

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
            if _is_motion_event(event):
                idx = self._find_last_motion_index(event)
                if idx is not None:
                    self._queue[idx] = _merge_motion_events(self._queue[idx], event)
                    self._telemetry_window["events_coalesced"] += 1
                    return
            if len(self._queue) < self._max_queue_size:
                self._queue.append(event)
                self._telemetry_window["events_enqueued"] += 1
                return
            if _is_keyboard_transition(event):
                if self._drop_one_non_keyboard():
                    self._queue.append(event)
                    self._telemetry_window["events_enqueued"] += 1
                    return
                raise RuntimeError("HDI queue saturated with keyboard transitions; refusing to drop keyboard events")
            if _is_motion_event(event):
                self._telemetry_window["events_dropped"] += 1
                return
            self._queue.popleft()
            self._queue.append(event)
            self._telemetry_window["events_dropped"] += 1
            self._telemetry_window["events_enqueued"] += 1

    def _find_last_motion_index(self, incoming: HDIEvent) -> int | None:
        for i in range(len(self._queue) - 1, -1, -1):
            e = self._queue[i]
            if not _is_motion_event(e):
                continue
            if e.device != incoming.device or e.window_id != incoming.window_id:
                continue
            if _motion_coalesce_key(e) != _motion_coalesce_key(incoming):
                continue
            return i
        return None

    def _drop_one_non_keyboard(self) -> bool:
        for i, event in enumerate(self._queue):
            if not _is_keyboard_transition(event):
                del self._queue[i]
                self._telemetry_window["events_dropped"] += 1
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


def _is_scroll_event(event: HDIEvent) -> bool:
    return event.event_type in ("scroll", "pan", "swipe")


def _is_motion_event(event: HDIEvent) -> bool:
    if event.device == "touch" and event.event_type == "touch":
        payload = event.payload if isinstance(event.payload, dict) else {}
        return str(payload.get("phase", "")).lower() == "move"
    return _is_move_event(event) or _is_scroll_event(event)


def _motion_coalesce_key(event: HDIEvent) -> tuple[str, str]:
    if event.device == "touch" and event.event_type == "touch":
        payload = event.payload if isinstance(event.payload, dict) else {}
        return ("touch_move", str(payload.get("touch_id", "")))
    if _is_move_event(event):
        return ("move", "")
    if _is_scroll_event(event):
        payload = event.payload if isinstance(event.payload, dict) else {}
        phase = str(payload.get("phase", ""))
        momentum = str(payload.get("momentum_phase", ""))
        return ("scroll", f"{phase}|{momentum}")
    return ("", "")


def _merge_motion_events(existing: HDIEvent, incoming: HDIEvent) -> HDIEvent:
    payload_existing = existing.payload if isinstance(existing.payload, dict) else {}
    payload_incoming = incoming.payload if isinstance(incoming.payload, dict) else {}
    merged = dict(payload_existing)
    merged.update(payload_incoming)
    if _is_scroll_event(incoming):
        ex_dx = _float_or_zero(payload_existing.get("delta_x", 0.0))
        ex_dy = _float_or_zero(payload_existing.get("delta_y", 0.0))
        in_dx = _float_or_zero(payload_incoming.get("delta_x", 0.0))
        in_dy = _float_or_zero(payload_incoming.get("delta_y", 0.0))
        if incoming.device == "trackpad":
            merged["delta_x"] = in_dx
            merged["delta_y"] = in_dy
            merged["coalesce_mode"] = "latest"
        else:
            merged["delta_x"] = ex_dx + in_dx
            merged["delta_y"] = ex_dy + in_dy
            merged["coalesce_mode"] = "sum"
        merged["coalesced_count"] = int(payload_existing.get("coalesced_count", 1)) + 1
    return replace(incoming, payload=merged)


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


@dataclass
class _TouchPoint:
    touch_id: int
    x: float
    y: float


@dataclass
class _GestureState:
    centroid_x: float
    centroid_y: float
    distance: float
    angle: float


def _gesture_state_from_touches(touches: dict[int, _TouchPoint]) -> _GestureState:
    ordered = [touches[k] for k in sorted(touches)]
    centroid_x = sum(p.x for p in ordered) / float(len(ordered))
    centroid_y = sum(p.y for p in ordered) / float(len(ordered))
    a = ordered[0]
    b = ordered[1]
    dx = b.x - a.x
    dy = b.y - a.y
    return _GestureState(
        centroid_x=centroid_x,
        centroid_y=centroid_y,
        distance=(dx * dx + dy * dy) ** 0.5,
        angle=math.atan2(dy, dx),
    )


def _percentile_int(values: list[int], q: float) -> int:
    if not values:
        return 0
    if q <= 0:
        return int(values[0])
    if q >= 100:
        return int(values[-1])
    idx = (len(values) - 1) * (q / 100.0)
    lo = int(idx)
    hi = min(len(values) - 1, lo + 1)
    if lo == hi:
        return int(values[lo])
    blend = idx - float(lo)
    return int(round((float(values[lo]) * (1.0 - blend)) + (float(values[hi]) * blend)))


def _float_or_zero(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
