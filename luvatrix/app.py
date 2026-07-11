from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from importlib import resources
import importlib.util
import math
import platform
from pathlib import Path
from typing import Any

from luvatrix_core.core.app_runtime import (
    APP_PROTOCOL_VERSION,
    AppContext,
    AppLifecycle,
    AppManifest,
    AppRuntime,
    AppUIRenderer,
    AppVariant,
    AppWebConfig,
    ResolvedAppVariant,
)
from luvatrix_core.core.hdi_thread import HDIEvent, HDIThread
from luvatrix_core.core.sensor_manager import SensorManagerThread, SensorSample
from luvatrix_core.core.window_matrix import FullRewrite, WriteBatch, WindowMatrix
from luvatrix_core import accel

PLATFORM_MACOS = "macos"
PLATFORM_IOS = "ios"
PLATFORM_ANDROID = "android"
PLATFORM_LINUX = "linux"
PLATFORM_WINDOWS = "windows"
PLATFORM_WEB = "web"

SUPPORTED_APP_PLATFORMS = (
    PLATFORM_MACOS,
    PLATFORM_IOS,
    PLATFORM_ANDROID,
    PLATFORM_LINUX,
    PLATFORM_WINDOWS,
    PLATFORM_WEB,
)

RENDER_PLATFORM: dict[str, str | None] = {
    "headless": None,
    "macos": PLATFORM_MACOS,
    "macos-metal": PLATFORM_MACOS,
    "ios-simulator": PLATFORM_IOS,
    "ios-device": PLATFORM_IOS,
    "android-emulator": PLATFORM_ANDROID,
    "android-device": PLATFORM_ANDROID,
    "web": PLATFORM_WEB,
}

RENDER_EXTRA_MODULES: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "headless": (),
    "macos": (
        ("macos", ("AppKit", "Quartz", "Metal", "objc")),
        ("vulkan", ("vulkan",)),
    ),
    "macos-metal": (
        ("macos", ("AppKit", "Quartz", "Metal", "objc")),
    ),
    "ios-simulator": (
        ("ios", ()),
    ),
    "ios-device": (
        ("ios", ()),
    ),
    "android-emulator": (
        ("android", ()),
    ),
    "android-device": (
        ("android", ()),
    ),
    "web": (),
}

COORD_SCREEN_TL = "screen_tl"
COORD_CARTESIAN_BL = "cartesian_bl"
COORD_CARTESIAN_CENTER = "cartesian_center"
BUILTIN_COORDINATE_FRAMES = (COORD_SCREEN_TL, COORD_CARTESIAN_BL, COORD_CARTESIAN_CENTER)


@dataclass
class InputState:
    mouse_x: float = 0.0
    mouse_y: float = 0.0
    mouse_in_window: bool = False
    mouse_error: str | None = "window not active / pointer out of bounds"
    active_touches: dict[int, tuple[float, float]] = field(default_factory=dict)
    touch_count: int = 0
    gesture_pan_x: float = 0.0
    gesture_pan_y: float = 0.0
    gesture_scale: float = 1.0
    gesture_rotation: float = 0.0
    left_down: bool = False
    right_down: bool = False
    left_clicked: bool = False
    right_clicked: bool = False
    pressure: float = 0.0
    pinch: float = 0.0
    rotation: float = 0.0
    scroll_x: float = 0.0
    scroll_y: float = 0.0
    key_last: str = ""
    key_state: str = ""
    keys_down: list[str] | None = None

    @property
    def pointer(self) -> tuple[float, float]:
        return (self.mouse_x, self.mouse_y)


class InputManager:
    def __init__(self, ctx: AppContext, on_activity: Callable[[], None] | None = None) -> None:
        self._ctx = ctx
        self._state = InputState()
        self._on_activity = on_activity

    @property
    def state(self) -> InputState:
        return self._state

    def raw_events(self, max_events: int = 256, frame: str | None = None) -> list[HDIEvent]:
        return self._ctx.poll_hdi_events(max_events=max_events, frame=frame)

    def snapshot(self, max_events: int = 256, frame: str | None = None) -> InputState:
        events = self.raw_events(max_events=max_events, frame=frame)
        if events and self._on_activity is not None:
            self._on_activity()
        reset_transient_input(self._state)
        apply_hdi_events(self._state, events)
        return self._state


@dataclass(frozen=True)
class ScrollbarMetrics:
    thumb_start: float
    thumb_extent: float
    travel_extent: float
    max_offset: float


@dataclass(frozen=True)
class ScrollbarUpdate:
    offset: float
    consumed: bool
    dragging: bool


@dataclass(frozen=True)
class SwipeMomentumUpdate:
    delta: float
    velocity: float
    dragging: bool
    inertial: bool
    needs_render: bool


class ScrollbarController:
    """Pointer interaction state for a horizontal or vertical scrollbar."""

    def __init__(self, orientation: str = "vertical", *, min_thumb_extent: float = 24.0) -> None:
        if orientation not in {"horizontal", "vertical"}:
            raise ValueError("orientation must be 'horizontal' or 'vertical'")
        self.orientation = orientation
        self.min_thumb_extent = max(1.0, float(min_thumb_extent))
        self._dragging = False
        self._drag_anchor = 0.0

    @property
    def dragging(self) -> bool:
        return self._dragging

    def metrics(
        self,
        *,
        track_extent: float,
        content_extent: float,
        viewport_extent: float,
        offset: float,
    ) -> ScrollbarMetrics:
        track_extent = max(0.0, float(track_extent))
        content_extent = max(0.0, float(content_extent))
        viewport_extent = max(0.0, float(viewport_extent))
        max_offset = max(0.0, content_extent - viewport_extent)
        if track_extent <= 0.0 or content_extent <= 0.0 or max_offset <= 0.0:
            return ScrollbarMetrics(0.0, track_extent, 0.0, max_offset)
        ratio = min(1.0, viewport_extent / content_extent)
        thumb_extent = min(track_extent, max(self.min_thumb_extent, track_extent * ratio))
        travel = max(0.0, track_extent - thumb_extent)
        clamped_offset = min(max(0.0, float(offset)), max_offset)
        thumb_start = travel * (clamped_offset / max_offset) if travel > 0.0 else 0.0
        return ScrollbarMetrics(thumb_start, thumb_extent, travel, max_offset)

    def update(
        self,
        state: InputState,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        content_extent: float,
        viewport_extent: float,
        offset: float,
    ) -> ScrollbarUpdate:
        track_start = float(y if self.orientation == "vertical" else x)
        track_extent = float(height if self.orientation == "vertical" else width)
        pointer_axis = float(state.mouse_y if self.orientation == "vertical" else state.mouse_x)
        pointer_cross = float(state.mouse_x if self.orientation == "vertical" else state.mouse_y)
        cross_start = float(x if self.orientation == "vertical" else y)
        cross_extent = float(width if self.orientation == "vertical" else height)
        metrics = self.metrics(
            track_extent=track_extent,
            content_extent=content_extent,
            viewport_extent=viewport_extent,
            offset=offset,
        )
        clamped = min(max(0.0, float(offset)), metrics.max_offset)
        clicked = bool(state.left_clicked)
        down = bool(state.left_down)
        in_cross = cross_start <= pointer_cross <= cross_start + max(0.0, cross_extent)
        local_axis = pointer_axis - track_start
        in_track = in_cross and 0.0 <= local_axis <= track_extent
        consumed = False

        if clicked and in_track and metrics.max_offset > 0.0:
            thumb_end = metrics.thumb_start + metrics.thumb_extent
            if metrics.thumb_start <= local_axis <= thumb_end:
                self._drag_anchor = local_axis - metrics.thumb_start
            else:
                self._drag_anchor = metrics.thumb_extent * 0.5
            self._dragging = True
            consumed = True

        if self._dragging and down:
            consumed = True
            thumb_start = min(
                max(0.0, local_axis - self._drag_anchor),
                metrics.travel_extent,
            )
            clamped = (
                metrics.max_offset * thumb_start / metrics.travel_extent
                if metrics.travel_extent > 0.0
                else 0.0
            )
        elif self._dragging and not down:
            consumed = True
            self._dragging = False
            self._drag_anchor = 0.0

        return ScrollbarUpdate(offset=clamped, consumed=consumed, dragging=self._dragging)


class SwipeMomentumController:
    """Touch drag velocity and post-release inertia for one input axis."""

    def __init__(
        self,
        axis: str = "y",
        *,
        direction: float = 1.0,
        velocity_smoothing: float = 0.45,
        max_velocity: float = 3600.0,
        deceleration: float = 3200.0,
        stop_velocity: float = 8.0,
        hold_cancel_time: float = 0.14,
        fallback_dt: float = 1.0 / 120.0,
        max_dt: float = 1.0 / 30.0,
        request_render: Callable[[], None] | None = None,
    ) -> None:
        if axis not in {"x", "y"}:
            raise ValueError("axis must be 'x' or 'y'")
        self.axis = axis
        self.direction = float(direction)
        self.velocity_smoothing = _clamp_float(float(velocity_smoothing), 0.0, 1.0)
        self.max_velocity = max(0.0, float(max_velocity))
        self.deceleration = max(0.0, float(deceleration))
        self.stop_velocity = max(0.0, float(stop_velocity))
        self.hold_cancel_time = max(0.0, float(hold_cancel_time))
        self.fallback_dt = max(0.000001, float(fallback_dt))
        self.max_dt = max(self.fallback_dt, float(max_dt))
        self.request_render = request_render
        self._touch_id: int | None = None
        self._last_position: float | None = None
        self._sample_dt = 0.0
        self._velocity = 0.0
        self._dragging = False

    @property
    def velocity(self) -> float:
        return self._velocity

    @property
    def dragging(self) -> bool:
        return self._dragging

    def reset(self) -> None:
        self._touch_id = None
        self._last_position = None
        self._sample_dt = 0.0
        self._velocity = 0.0
        self._dragging = False

    def update(self, state: InputState, dt: float) -> SwipeMomentumUpdate:
        frame_dt = _motion_dt(dt, fallback_dt=self.fallback_dt, max_dt=self.max_dt)
        if not state.active_touches:
            if self._sample_dt > self.hold_cancel_time:
                self._velocity = 0.0
            self._touch_id = None
            self._last_position = None
            self._sample_dt = 0.0
            self._dragging = False
            return self._apply_inertia(frame_dt)

        touch_id, point = next(iter(sorted(state.active_touches.items())))
        position = float(point[0] if self.axis == "x" else point[1])
        if self._touch_id != touch_id or self._last_position is None:
            self._touch_id = touch_id
            self._last_position = position
            self._sample_dt = 0.0
            self._velocity = 0.0
            self._dragging = True
            return SwipeMomentumUpdate(0.0, 0.0, True, False, False)

        self._sample_dt += frame_dt
        pointer_delta = position - self._last_position
        self._last_position = position
        if pointer_delta:
            delta = pointer_delta * self.direction
            sample_dt = max(self._sample_dt, self.fallback_dt)
            sample_velocity = _clamp_float(
                delta / sample_dt,
                -self.max_velocity,
                self.max_velocity,
            )
            self._velocity = (
                self._velocity * (1.0 - self.velocity_smoothing)
                + sample_velocity * self.velocity_smoothing
            )
            self._sample_dt = 0.0
            self._request_render()
            return SwipeMomentumUpdate(delta, self._velocity, True, False, True)

        if self._sample_dt > self.hold_cancel_time:
            self._velocity = 0.0
        return SwipeMomentumUpdate(0.0, self._velocity, True, False, False)

    def _apply_inertia(self, dt: float) -> SwipeMomentumUpdate:
        velocity = self._velocity
        if abs(velocity) <= self.stop_velocity:
            self._velocity = 0.0
            return SwipeMomentumUpdate(0.0, 0.0, False, False, False)

        delta = velocity * dt
        speed = max(0.0, abs(velocity) - self.deceleration * dt)
        self._velocity = 0.0 if speed <= self.stop_velocity else math.copysign(speed, velocity)
        self._request_render()
        return SwipeMomentumUpdate(delta, self._velocity, False, True, True)

    def _request_render(self) -> None:
        if self.request_render is not None:
            self.request_render()


def reset_transient_input(state: InputState) -> None:
    state.pinch = 0.0
    state.rotation = 0.0
    state.scroll_x = 0.0
    state.scroll_y = 0.0
    state.left_clicked = False
    state.right_clicked = False
    state.key_last = ""
    state.key_state = ""


def _apply_pointer_payload(state: InputState, payload: dict) -> None:
    if "x" not in payload and "y" not in payload:
        return
    state.mouse_x = float(payload.get("x", state.mouse_x))
    state.mouse_y = float(payload.get("y", state.mouse_y))
    state.mouse_in_window = True
    state.mouse_error = None


def apply_hdi_events(state: InputState, events: list[object]) -> InputState:
    for event in events:
        if getattr(event, "device", None) == "keyboard":
            payload = getattr(event, "payload", None)
            if getattr(event, "status", None) == "OK" and isinstance(payload, dict):
                key = str(payload.get("key", "")).strip()
                phase = str(payload.get("phase", ""))
                if key:
                    state.key_last = key
                if phase:
                    state.key_state = phase
                active_keys = payload.get("active_keys")
                if isinstance(active_keys, list):
                    state.keys_down = [str(k) for k in active_keys]
            else:
                state.key_state = str(getattr(event, "status", ""))

        payload = getattr(event, "payload", None)
        device = getattr(event, "device", None)
        event_type = getattr(event, "event_type", None)
        status = getattr(event, "status", None)
        if device == "mouse" and event_type == "pointer_move":
            if status == "OK" and isinstance(payload, dict):
                state.mouse_x = float(payload.get("x", state.mouse_x))
                state.mouse_y = float(payload.get("y", state.mouse_y))
                state.mouse_in_window = True
                state.mouse_error = None
            else:
                state.mouse_in_window = False
                state.mouse_error = "window not active / pointer out of bounds"
        if device == "touch" and isinstance(payload, dict):
            if event_type == "touch" and status == "OK":
                touch_id = int(payload.get("touch_id", 0))
                phase = str(payload.get("phase", ""))
                x = float(payload.get("x", state.mouse_x))
                y = float(payload.get("y", state.mouse_y))
                if phase in ("down", "move"):
                    state.active_touches[touch_id] = (x, y)
                    state.mouse_x = x
                    state.mouse_y = y
                    state.mouse_in_window = True
                    state.mouse_error = None
                    state.pressure = _effective_touch_pressure(
                        force=float(payload.get("force", state.pressure) or 0.0),
                        major_radius=float(payload.get("major_radius", 0.0) or 0.0),
                    )
                elif phase in ("up", "cancel"):
                    state.active_touches.pop(touch_id, None)
                state.touch_count = len(state.active_touches)
                if phase in ("up", "cancel") and state.touch_count == 0:
                    state.mouse_in_window = False
                    state.mouse_error = "window not active / pointer out of bounds"
                    state.pressure = 0.0
            elif event_type == "gesture" and status == "OK":
                kind = str(payload.get("kind", ""))
                if kind == "pan":
                    state.gesture_pan_x = float(payload.get("translation_x", state.gesture_pan_x))
                    state.gesture_pan_y = float(payload.get("translation_y", state.gesture_pan_y))
                elif kind == "pinch":
                    state.gesture_scale = float(payload.get("scale", state.gesture_scale))
                    state.pinch = state.gesture_scale - 1.0
                elif kind == "rotate":
                    state.gesture_rotation = float(payload.get("rotation", state.gesture_rotation))
                    state.rotation = state.gesture_rotation
        if device not in ("mouse", "trackpad") or not isinstance(payload, dict):
            continue
        _apply_pointer_payload(state, payload)
        if event_type == "click":
            button = int(payload.get("button", -1))
            phase = str(payload.get("phase", ""))
            is_down = phase == "down"
            if button == 0:
                state.left_down = is_down
                if is_down:
                    state.left_clicked = True
            elif button == 1:
                state.right_down = is_down
                if is_down:
                    state.right_clicked = True
        elif event_type == "pointer_move":
            buttons_mask = payload.get("buttons_mask")
            if buttons_mask is not None:
                mask = int(buttons_mask)
                state.left_down = bool(mask & 1)
                state.right_down = bool(mask & 2)
        elif event_type == "pressure":
            state.pressure = float(payload.get("pressure", state.pressure))
        elif event_type == "pinch":
            state.pinch = float(payload.get("magnification", state.pinch))
        elif event_type == "rotate":
            state.rotation = float(payload.get("rotation", state.rotation))
        elif event_type == "scroll":
            state.scroll_x += float(payload.get("delta_x", 0.0) or 0.0)
            state.scroll_y += float(payload.get("delta_y", 0.0) or 0.0)
    return state


def _effective_touch_pressure(*, force: float, major_radius: float) -> float:
    force = max(0.0, min(1.0, float(force)))
    major_radius = max(0.0, float(major_radius))
    area_pressure = max(0.0, min(1.0, (major_radius - 4.0) / 34.0))
    if 0.0 < force < 0.98:
        return max(force, area_pressure)
    return area_pressure


def _motion_dt(dt: float, *, fallback_dt: float, max_dt: float) -> float:
    try:
        value = float(dt)
    except (TypeError, ValueError):
        value = fallback_dt
    if value <= 0.0 or not math.isfinite(value):
        return fallback_dt
    return min(value, max_dt)


def _clamp_float(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class CoordinateFrames:
    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx

    @property
    def default(self) -> str:
        return self._ctx.default_coordinate_frame

    def set_default(self, frame: str) -> None:
        self._ctx.set_default_coordinate_frame(frame)

    def cycle(self, frames: tuple[str, ...] | list[str] | None = None) -> str:
        order = tuple(frames or BUILTIN_COORDINATE_FRAMES)
        current = self.default
        if current not in order:
            next_frame = order[0]
        else:
            next_frame = order[(order.index(current) + 1) % len(order)]
        self.set_default(next_frame)
        return next_frame

    def from_render(self, x: float, y: float, frame: str | None = None) -> tuple[float, float]:
        return self._ctx.from_render_coords(x, y, frame=frame)

    def to_render(self, x: float, y: float, frame: str | None = None) -> tuple[float, float]:
        return self._ctx.to_render_coords(x, y, frame=frame)

    def bind_switch_keys(
        self,
        input_state: InputState,
        keys: dict[str, str] | None = None,
        frames: tuple[str, ...] | list[str] | None = None,
    ) -> str | None:
        mapping = keys or {"1": COORD_SCREEN_TL, "2": COORD_CARTESIAN_BL, "3": COORD_CARTESIAN_CENTER, "c": "cycle"}
        phase = input_state.key_state
        if phase not in ("down", "single"):
            return None
        key = input_state.key_last.strip().lower()
        target = mapping.get(key)
        if target is None:
            return None
        next_frame = self.cycle(frames) if target == "cycle" else target
        self.set_default(next_frame)
        return next_frame


class Display:
    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx

    @property
    def width_px(self) -> int:
        return int(round(self._ctx.display_width_px))

    @property
    def height_px(self) -> int:
        return int(round(self._ctx.display_height_px))


class Sensors:
    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx

    def available(self) -> list[str]:
        names = set(self._ctx.sensor_manager.enabled_sensors())
        for capability in self._ctx.granted_capabilities:
            if capability.startswith("sensor.") and capability not in {"sensor.*", "sensor.high_precision"}:
                suffix = capability.removeprefix("sensor.")
                if "." in suffix:
                    names.add(suffix)
        return sorted(names)

    def select(self, requested: list[str] | tuple[str, ...] | None = None, available: list[str] | None = None) -> list[str]:
        available_sensors = list(self.available() if available is None else available)
        if not requested:
            return available_sensors
        selected: list[str] = []
        for sensor in requested:
            if sensor not in available_sensors:
                raise ValueError(
                    f"unsupported sensor `{sensor}` on this runtime; choose from: {', '.join(available_sensors)}"
                )
            if sensor not in selected:
                selected.append(sensor)
        return selected

    def read(self, sensor_type: str) -> SensorSample:
        return self._ctx.read_sensor(sensor_type)

    def read_many(self, names: list[str] | tuple[str, ...]) -> dict[str, SensorSample]:
        return {name: self.read(name) for name in names}


def _rgba(value: tuple[int, int, int, int] | str) -> tuple[int, int, int, int]:
    if isinstance(value, tuple):
        return (int(value[0]), int(value[1]), int(value[2]), int(value[3]))
    raw = value.strip()
    if raw.startswith("#"):
        h = raw[1:]
        if len(h) == 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
        if len(h) == 8:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16))
    raise ValueError(f"unsupported color: {value!r}")


class SceneFrame(AbstractContextManager["SceneFrame"]):
    def __init__(
        self,
        ctx: AppContext,
        clear: tuple[int, int, int, int] | str = (0, 0, 0, 255),
        *,
        content_offset: tuple[float, float] = (0.0, 0.0),
        retained: bool = False,
    ) -> None:
        self._ctx = ctx
        self._clear = _rgba(clear)
        self._content_offset = (float(content_offset[0]), float(content_offset[1]))
        self._retained = bool(retained)

    def __enter__(self) -> "SceneFrame":
        self._ctx.begin_scene_frame(content_offset=self._content_offset, retained=self._retained)
        self._ctx.clear_scene(self._clear)
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        if exc_type is None:
            self._ctx.finalize_scene_frame()
        return False

    def _point(self, x: float, y: float, frame: str | None = None) -> tuple[float, float]:
        return self._ctx.to_render_coords(float(x), float(y), frame=frame)

    def _rect(self, x: float, y: float, width: float, height: float, frame: str | None = None) -> tuple[float, float, float, float]:
        x0, y0 = self._point(x, y, frame=frame)
        x1, y1 = self._point(x + width, y + height, frame=frame)
        left = min(x0, x1)
        top = min(y0, y1)
        return left, top, abs(x1 - x0), abs(y1 - y0)

    def shader_rect(self, shader: str, *, x: float = 0.0, y: float = 0.0, width: float | None = None, height: float | None = None, uniforms: tuple[float, ...] = (), z_index: int = 0, frame: str | None = None) -> None:
        rx, ry, rw, rh = self._rect(
            x,
            y,
            float(self._ctx.display_width_px if width is None else width),
            float(self._ctx.display_height_px if height is None else height),
            frame=frame,
        )
        self._ctx.draw_shader_rect(
            x=rx,
            y=ry,
            width=rw,
            height=rh,
            shader=shader,
            uniforms=uniforms,
            z_index=z_index,
        )

    def rect(self, *, x: float, y: float, width: float, height: float, color: tuple[int, int, int, int] | str, z_index: int = 0, frame: str | None = None) -> None:
        rx, ry, rw, rh = self._rect(x, y, width, height, frame=frame)
        self._ctx.draw_rect(x=rx, y=ry, width=rw, height=rh, color_rgba=_rgba(color), z_index=z_index)

    def rounded_rect(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        radius: float,
        color: tuple[int, int, int, int] | str,
        z_index: int = 0,
        frame: str | None = None,
    ) -> None:
        rx, ry, rw, rh = self._rect(x, y, width, height, frame=frame)
        self._ctx.draw_rounded_rect(
            x=rx,
            y=ry,
            width=rw,
            height=rh,
            radius=radius,
            color_rgba=_rgba(color),
            z_index=z_index,
        )

    def circle(self, *, cx: float, cy: float, radius: float, fill: tuple[int, int, int, int] | str, stroke: tuple[int, int, int, int] | str = (0, 0, 0, 0), stroke_width: float = 0.0, z_index: int = 0, frame: str | None = None) -> None:
        rx, ry = self._point(cx, cy, frame=frame)
        self._ctx.draw_circle(
            cx=rx,
            cy=ry,
            radius=radius,
            fill_rgba=_rgba(fill),
            stroke_rgba=_rgba(stroke),
            stroke_width=stroke_width,
            z_index=z_index,
        )

    def text(self, text: str, *, x: float, y: float, font_size_px: float = 14.0, color: tuple[int, int, int, int] | str = (255, 255, 255, 255), z_index: int = 0, cache_key: str | None = None, rotation_deg: float = 0.0, frame: str | None = None) -> None:
        rx, ry = self._point(x, y, frame=frame)
        self._ctx.draw_text(text, x=rx, y=ry, font_size_px=font_size_px, color_rgba=_rgba(color), z_index=z_index, cache_key=cache_key, rotation_deg=rotation_deg)

    def camera3d(
        self,
        *,
        position: tuple[float, float, float] = (0.0, 0.0, 5.0),
        target: tuple[float, float, float] = (0.0, 0.0, 0.0),
        up: tuple[float, float, float] = (0.0, 1.0, 0.0),
        fov_deg: float = 60.0,
        near: float = 0.1,
        far: float = 100.0,
        z_index: int = 0,
    ) -> None:
        self._ctx.set_camera3d(
            position=position,
            target=target,
            up=up,
            fov_deg=fov_deg,
            near=near,
            far=far,
            z_index=z_index,
        )

    def cube3d(
        self,
        *,
        center: tuple[float, float, float] = (0.0, 0.0, 0.0),
        size: float = 1.0,
        rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
        color: tuple[int, int, int, int] | str = (80, 180, 255, 255),
        edge: tuple[int, int, int, int] | str = (255, 255, 255, 255),
        z_index: int = 0,
    ) -> None:
        self._ctx.draw_cube3d(
            center=center,
            size=size,
            rotation=rotation,
            color_rgba=_rgba(color),
            edge_rgba=_rgba(edge),
            z_index=z_index,
        )

    def cuboid3d(
        self,
        *,
        center: tuple[float, float, float] = (0.0, 0.0, 0.0),
        size: tuple[float, float, float] = (1.0, 1.0, 1.0),
        rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
        color: tuple[int, int, int, int] | str = (80, 180, 255, 255),
        edge: tuple[int, int, int, int] | str = (255, 255, 255, 255),
        z_index: int = 0,
    ) -> None:
        self._ctx.draw_cuboid3d(
            center=center,
            size=size,
            rotation=rotation,
            color_rgba=_rgba(color),
            edge_rgba=_rgba(edge),
            z_index=z_index,
        )

    def rounded_cuboid3d(
        self,
        *,
        center: tuple[float, float, float] = (0.0, 0.0, 0.0),
        size: tuple[float, float, float] = (1.0, 1.0, 1.0),
        rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
        radius: float = 0.25,
        color: tuple[int, int, int, int] | str = (80, 180, 255, 255),
        edge: tuple[int, int, int, int] | str = (255, 255, 255, 255),
        z_index: int = 0,
    ) -> None:
        self._ctx.draw_rounded_cuboid3d(
            center=center,
            size=size,
            rotation=rotation,
            radius=radius,
            color_rgba=_rgba(color),
            edge_rgba=_rgba(edge),
            z_index=z_index,
        )

    def sphere3d(
        self,
        *,
        center: tuple[float, float, float] = (0.0, 0.0, 0.0),
        radius: float = 1.0,
        color: tuple[int, int, int, int] | str = (246, 208, 146, 255),
        edge: tuple[int, int, int, int] | str = (0, 0, 0, 0),
        z_index: int = 0,
    ) -> None:
        self._ctx.draw_sphere3d(
            center=center,
            radius=radius,
            color_rgba=_rgba(color),
            edge_rgba=_rgba(edge),
            z_index=z_index,
        )

    def model3d(
        self,
        *,
        asset: str,
        center: tuple[float, float, float] = (0.0, 0.0, 0.0),
        scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
        rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
        color: tuple[int, int, int, int] | str = (198, 145, 255, 255),
        edge: tuple[int, int, int, int] | str = (0, 0, 0, 0),
        z_index: int = 0,
    ) -> None:
        self._ctx.draw_model3d(
            asset=asset,
            center=center,
            scale=scale,
            rotation=rotation,
            color_rgba=_rgba(color),
            edge_rgba=_rgba(edge),
            z_index=z_index,
        )

    def image3d(
        self,
        *,
        asset: str,
        center: tuple[float, float, float] = (0.0, 0.0, 0.0),
        size: tuple[float, float] = (1.0, 1.0),
        rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
        opacity: float = 1.0,
        z_index: int = 0,
    ) -> None:
        self._ctx.draw_image3d(
            asset=asset,
            center=center,
            size=size,
            rotation=rotation,
            opacity=opacity,
            z_index=z_index,
        )

    def dot_grid3d(
        self,
        *,
        center: tuple[float, float, float] = (0.0, 0.0, 0.0),
        extent: float = 8.0,
        spacing: float = 0.5,
        point_size: float = 2.0,
        color: tuple[int, int, int, int] | str = (120, 170, 220, 120),
        z_index: int = 0,
    ) -> None:
        self._ctx.draw_dot_grid3d(
            center=center,
            extent=extent,
            spacing=spacing,
            point_size=point_size,
            color_rgba=_rgba(color),
            z_index=z_index,
        )

    def line3d(
        self,
        *,
        start: tuple[float, float, float],
        end: tuple[float, float, float],
        color: tuple[int, int, int, int] | str = (255, 255, 255, 255),
        width: float = 1.0,
        z_index: int = 0,
    ) -> None:
        self._ctx.draw_line3d(start=start, end=end, color_rgba=_rgba(color), width=width, z_index=z_index)

    def dot_plane3d(
        self,
        *,
        center: tuple[float, float, float] = (0.0, 0.0, 0.0),
        width: float = 8.0,
        depth: float = 8.0,
        spacing: float = 0.5,
        point_size: float = 2.0,
        color: tuple[int, int, int, int] | str = (140, 190, 225, 170),
        z_index: int = 0,
    ) -> None:
        self._ctx.draw_dot_plane3d(
            center=center,
            width=width,
            depth=depth,
            spacing=spacing,
            point_size=point_size,
            color_rgba=_rgba(color),
            z_index=z_index,
        )

    def ground_plane3d(
        self,
        *,
        center: tuple[float, float, float] = (0.0, 0.0, -20.0),
        width: float = 40.0,
        depth: float = 40.0,
        color: tuple[int, int, int, int] | str = (26, 46, 34, 255),
        z_index: int = -20,
    ) -> None:
        self._ctx.draw_ground_plane3d(center=center, width=width, depth=depth, color_rgba=_rgba(color), z_index=z_index)

    def infinite_ground3d(
        self,
        *,
        y: float = 0.0,
        z_max: float = 0.0,
        render_distance: float = 120.0,
        color: tuple[int, int, int, int] | str = (26, 46, 34, 255),
        z_index: int = -20,
    ) -> None:
        self._ctx.draw_infinite_ground3d(
            y=y,
            z_max=z_max,
            render_distance=render_distance,
            color_rgba=_rgba(color),
            z_index=z_index,
        )

    def infinite_dot_plane3d(
        self,
        *,
        y: float = 0.0,
        z_max: float = 0.0,
        spacing: float = 0.5,
        point_size: float = 2.0,
        render_distance: float = 80.0,
        color: tuple[int, int, int, int] | str = (140, 190, 225, 170),
        z_index: int = 0,
    ) -> None:
        self._ctx.draw_infinite_dot_plane3d(
            y=y,
            z_max=z_max,
            spacing=spacing,
            point_size=point_size,
            render_distance=render_distance,
            color_rgba=_rgba(color),
            z_index=z_index,
        )

    def infinite_grid3d(
        self,
        *,
        y: float = 0.0,
        minor_spacing: float = 1.0,
        major_spacing: float = 5.0,
        render_distance: float = 180.0,
        minor: tuple[int, int, int, int] | str = (204, 212, 218, 95),
        major: tuple[int, int, int, int] | str = (58, 118, 190, 145),
        minor_width: float = 1.0,
        major_width: float = 1.35,
        z_index: int = -10,
    ) -> None:
        self._ctx.draw_infinite_grid3d(
            y=y,
            minor_spacing=minor_spacing,
            major_spacing=major_spacing,
            render_distance=render_distance,
            minor_rgba=_rgba(minor),
            major_rgba=_rgba(major),
            minor_width=minor_width,
            major_width=major_width,
            z_index=z_index,
        )

    def horizon3d(
        self,
        *,
        sky: tuple[int, int, int, int] | str = (228, 238, 246, 255),
        ground: tuple[int, int, int, int] | str = (236, 232, 220, 255),
        horizon: tuple[int, int, int, int] | str = (150, 160, 168, 255),
        sky_horizon: tuple[int, int, int, int] | str | None = None,
        horizon_width: float = 0.012,
        z_index: int = -100,
    ) -> None:
        self._ctx.draw_horizon3d(
            sky_rgba=_rgba(sky),
            ground_rgba=_rgba(ground),
            horizon_rgba=_rgba(horizon),
            sky_horizon_rgba=None if sky_horizon is None else _rgba(sky_horizon),
            horizon_width=horizon_width,
            z_index=z_index,
        )

    def text3d(
        self,
        text: str,
        *,
        position: tuple[float, float, float] = (0.0, 0.0, 0.0),
        height: float = 0.4,
        depth: float = 0.12,
        color: tuple[int, int, int, int] | str = (235, 246, 255, 255),
        side: tuple[int, int, int, int] | str = (48, 76, 98, 255),
        font_family: str = "Inter",
        z_index: int = 0,
    ) -> None:
        self._ctx.draw_text3d(
            text,
            position=position,
            height=height,
            depth=depth,
            color_rgba=_rgba(color),
            side_rgba=_rgba(side),
            font_family=font_family,
            z_index=z_index,
        )


class UIFrame(AbstractContextManager["UIFrame"]):
    def __init__(self, ctx: AppContext, clear: tuple[int, int, int, int] | str = (0, 0, 0, 255)) -> None:
        from luvatrix_core.core.ui_frame_renderer import MatrixUIFrameRenderer

        self._ctx = ctx
        self._clear = _rgba(clear)
        self._renderer = MatrixUIFrameRenderer()

    def __enter__(self) -> "UIFrame":
        self._ctx.begin_ui_frame(self._renderer, clear_color=self._clear)
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        if exc_type is None:
            self._ctx.finalize_ui_frame()
        return False

    def shader_rect(self, shader: str, **kwargs: Any) -> None:
        _ = shader, kwargs

    def _point(self, x: float, y: float, frame: str | None = None) -> tuple[float, float]:
        return self._ctx.to_render_coords(float(x), float(y), frame=frame)

    def _rect(self, x: float, y: float, width: float, height: float, frame: str | None = None) -> tuple[float, float, float, float]:
        x0, y0 = self._point(x, y, frame=frame)
        x1, y1 = self._point(x + width, y + height, frame=frame)
        left = min(x0, x1)
        top = min(y0, y1)
        return left, top, abs(x1 - x0), abs(y1 - y0)

    def rect(self, *, x: float, y: float, width: float, height: float, color: tuple[int, int, int, int] | str, z_index: int = 0, frame: str | None = None) -> None:
        from luvatrix_ui.component_schema import CoordinatePoint
        from luvatrix_ui.controls.svg_component import SVGComponent

        rx, ry, rw, rh = self._rect(x, y, width, height, frame=frame)
        r, g, b, a = _rgba(color)
        markup = (
            f'<svg width="{rw}" height="{rh}" viewBox="0 0 {rw} {rh}">'
            f'<rect x="0" y="0" width="{rw}" height="{rh}" fill="#{r:02x}{g:02x}{b:02x}{a:02x}"/>'
            "</svg>"
        )
        self._ctx.mount_component(SVGComponent(component_id=f"rect_{z_index}_{x}_{y}", svg_markup=markup, position=CoordinatePoint(rx, ry, "screen_tl"), width=rw, height=rh))

    def circle(self, *, cx: float, cy: float, radius: float, fill: tuple[int, int, int, int] | str, stroke: tuple[int, int, int, int] | str = (0, 0, 0, 0), stroke_width: float = 0.0, z_index: int = 0, frame: str | None = None) -> None:
        from luvatrix_ui.component_schema import CoordinatePoint
        from luvatrix_ui.controls.svg_component import SVGComponent

        rx, ry = self._point(cx, cy, frame=frame)
        size = max(1.0, radius * 2.0 + stroke_width * 2.0)
        fr, fg, fb, fa = _rgba(fill)
        sr, sg, sb, sa = _rgba(stroke)
        markup = (
            f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
            f'<circle cx="{size / 2:.2f}" cy="{size / 2:.2f}" r="{radius:.2f}" '
            f'fill="#{fr:02x}{fg:02x}{fb:02x}{fa:02x}" stroke="#{sr:02x}{sg:02x}{sb:02x}{sa:02x}" '
            f'stroke-width="{stroke_width}"/>'
            "</svg>"
        )
        self._ctx.mount_component(SVGComponent(component_id=f"circle_{z_index}_{cx}_{cy}", svg_markup=markup, position=CoordinatePoint(rx - size / 2.0, ry - size / 2.0, "screen_tl"), width=size, height=size))

    def text(self, text: str, *, x: float, y: float, font_size_px: float = 14.0, color: tuple[int, int, int, int] | str = (255, 255, 255, 255), z_index: int = 0, cache_key: str | None = None, rotation_deg: float = 0.0, frame: str | None = None) -> None:
        _ = rotation_deg
        from luvatrix_ui.component_schema import CoordinatePoint
        from luvatrix_ui.text.component import TextComponent
        from luvatrix_ui.text.renderer import TextAppearance, TextSizeSpec

        rx, ry = self._point(x, y, frame=frame)
        r, g, b, _ = _rgba(color)
        self._ctx.mount_component(
            TextComponent(
                component_id=cache_key or f"text_{z_index}_{x}_{y}",
                text=text,
                position=CoordinatePoint(rx, ry, "screen_tl"),
                appearance=TextAppearance(color_hex=f"#{r:02x}{g:02x}{b:02x}"),
                size=TextSizeSpec(unit="px", value=font_size_px),
            )
        )


@dataclass(frozen=True)
class _BitmapFont:
    width: int
    height: int
    advance: int
    glyphs: dict[str, tuple[tuple[int, ...], ...]]


_DEBUG_GLYPHS: dict[str, tuple[str, ...]] = {
    " ": ("000", "000", "000", "000", "000"), "-": ("000", "000", "111", "000", "000"),
    ".": ("000", "000", "000", "000", "010"), ":": ("000", "010", "000", "010", "000"),
    "_": ("000", "000", "000", "000", "111"), "|": ("010", "010", "010", "010", "010"),
    "0": ("111", "101", "101", "101", "111"), "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"), "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"), "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"), "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"), "9": ("111", "101", "111", "001", "111"),
    "A": ("010", "101", "111", "101", "101"), "B": ("110", "101", "110", "101", "110"),
    "C": ("111", "100", "100", "100", "111"), "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"), "F": ("111", "100", "110", "100", "100"),
    "G": ("111", "100", "101", "101", "111"), "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"), "J": ("001", "001", "001", "101", "111"),
    "K": ("101", "101", "110", "101", "101"), "L": ("100", "100", "100", "100", "111"),
    "M": ("101", "111", "111", "101", "101"), "N": ("101", "111", "111", "111", "101"),
    "O": ("111", "101", "101", "101", "111"), "P": ("111", "101", "111", "100", "100"),
    "Q": ("111", "101", "101", "111", "001"), "R": ("111", "101", "111", "110", "101"),
    "S": ("111", "100", "111", "001", "111"), "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "111"), "V": ("101", "101", "101", "101", "010"),
    "W": ("101", "101", "111", "111", "101"), "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "010", "010", "010"), "Z": ("111", "001", "010", "100", "111"),
}


_DEFAULT_MATRIX_FONT: _BitmapFont | None = None
_MATRIX_FONT_ALPHA_ASSET = "templates/native/android/app/src/main/assets/luvatrix_matrix_font_alpha.txt"
_BITMAP_FONT_ASSET = "templates/native/android/app/src/main/assets/luvatrix_bitmap_font.txt"
_BITMAP_FONT_KEY_ALIASES = {
    "U+0020": " ",
    "colon": ":",
    "period": ".",
    "comma": ",",
    "dash": "-",
    "underscore": "_",
    "equals": "=",
    "pipe": "|",
    "slash": "/",
}


def _debug_bitmap_font() -> _BitmapFont:
    glyphs = {
        ch: tuple(
            tuple(255 if bit == "1" else 0 for bit in row)
            for row in rows
        )
        for ch, rows in _DEBUG_GLYPHS.items()
    }
    return _BitmapFont(width=3, height=5, advance=4, glyphs=glyphs)


def _bitmap_font_key_to_char(key: str) -> str:
    if key in _BITMAP_FONT_KEY_ALIASES:
        return _BITMAP_FONT_KEY_ALIASES[key]
    if key.startswith("U+"):
        try:
            return chr(int(key[2:], 16))
        except ValueError:
            return ""
    return key if len(key) == 1 else ""


def _parse_bitmap_font_table(source: str) -> _BitmapFont:
    table_format = "bitmask"
    width = 0
    height = 0
    advance = 0
    glyphs: dict[str, tuple[tuple[int, ...], ...]] = {}
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = (part.strip() for part in line.split("=", 1))
        if key == "format":
            if raw_value not in ("bitmask", "alpha"):
                raise ValueError(f"unsupported bitmap font format: {raw_value}")
            table_format = raw_value
            continue
        if key == "supersample":
            continue
        if key == "width":
            width = int(raw_value)
            continue
        if key == "height":
            height = int(raw_value)
            continue
        if key == "advance":
            advance = int(raw_value)
            continue
        ch = _bitmap_font_key_to_char(key)
        if not ch:
            continue
        parsed_rows: list[tuple[int, ...]] = []
        for part in raw_value.split(","):
            token = part.strip()
            if not token:
                continue
            try:
                if table_format == "alpha":
                    parsed_rows.append(_parse_bitmap_alpha_row(token, width))
                else:
                    parsed_rows.append(_bitmap_mask_to_coverage_row(int(token, 16), width))
            except ValueError:
                parsed_rows.clear()
                break
        if len(parsed_rows) != height or any(len(row) != width for row in parsed_rows):
            continue
        rows = tuple(parsed_rows)
        glyphs[ch] = rows
        if ch.isalpha():
            glyphs.setdefault(ch.lower(), rows)

    if width <= 0 or height <= 0 or advance <= 0:
        raise ValueError("bitmap font table is missing width, height, or advance")
    if not glyphs:
        raise ValueError("bitmap font table has no valid glyphs")
    if " " not in glyphs:
        glyphs[" "] = tuple(tuple(0 for _ in range(width)) for _ in range(height))
    return _BitmapFont(width=width, height=height, advance=advance, glyphs=glyphs)


def _bitmap_mask_to_coverage_row(mask: int, width: int) -> tuple[int, ...]:
    return tuple(
        255 if mask & (1 << (width - 1 - x)) else 0
        for x in range(width)
    )


def _parse_bitmap_alpha_row(token: str, width: int) -> tuple[int, ...]:
    if width <= 0 or len(token) != width * 2:
        raise ValueError("alpha row length does not match font width")
    return tuple(
        int(token[index : index + 2], 16)
        for index in range(0, len(token), 2)
    )


def _default_matrix_font() -> _BitmapFont:
    global _DEFAULT_MATRIX_FONT
    if _DEFAULT_MATRIX_FONT is not None:
        return _DEFAULT_MATRIX_FONT
    try:
        text = resources.files("luvatrix_core").joinpath(_MATRIX_FONT_ALPHA_ASSET).read_text(encoding="utf-8")
        _DEFAULT_MATRIX_FONT = _parse_bitmap_font_table(text)
    except (FileNotFoundError, ModuleNotFoundError, ValueError):
        try:
            text = resources.files("luvatrix_core").joinpath(_BITMAP_FONT_ASSET).read_text(encoding="utf-8")
            _DEFAULT_MATRIX_FONT = _parse_bitmap_font_table(text)
        except (FileNotFoundError, ModuleNotFoundError, ValueError):
            _DEFAULT_MATRIX_FONT = _debug_bitmap_font()
    return _DEFAULT_MATRIX_FONT


def draw_text_to_matrix(
    matrix,
    text: str,
    *,
    x: float,
    y: float,
    font_size_px: float = 14.0,
    color: tuple[int, int, int, int] | str = (255, 255, 255, 255),
):
    """Rasterize Luvatrix's default matrix text glyphs into an RGBA matrix."""
    height = int(matrix.shape[0])
    width = int(matrix.shape[1])
    if height <= 0 or width <= 0:
        return matrix

    font = _default_matrix_font()
    scale = max(1, int(round(float(font_size_px) / float(font.height))))
    cursor = int(x)
    top = int(y)
    rgba = _rgba(color)
    space = font.glyphs[" "]
    for raw_ch in str(text):
        glyph = font.glyphs.get(raw_ch, font.glyphs.get(raw_ch.upper(), space))
        for gy, row in enumerate(glyph):
            for gx, coverage in enumerate(row):
                if coverage <= 0:
                    continue
                _paint_matrix_rect(
                    matrix,
                    cursor + gx * scale,
                    top + gy * scale,
                    cursor + (gx + 1) * scale,
                    top + (gy + 1) * scale,
                    rgba,
                    coverage=coverage,
                    width=width,
                    height=height,
                )
        cursor += font.advance * scale
    return matrix


def _paint_matrix_rect(
    matrix,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int, int],
    *,
    coverage: int,
    width: int,
    height: int,
) -> None:
    coverage = max(0, min(255, int(coverage)))
    if coverage <= 0:
        return
    if coverage == 255 and color[3] >= 255:
        _fill_matrix_rect(matrix, x0, y0, x1, y1, color, width=width, height=height)
        return
    _blend_matrix_rect(matrix, x0, y0, x1, y1, color, coverage=coverage, width=width, height=height)


def _blend_matrix_rect(
    matrix,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int, int],
    *,
    coverage: int,
    width: int,
    height: int,
) -> None:
    x0 = max(0, min(width, int(x0)))
    y0 = max(0, min(height, int(y0)))
    x1 = max(x0, min(width, int(x1)))
    y1 = max(y0, min(height, int(y1)))
    if x1 <= x0 or y1 <= y0:
        return
    effective_alpha = max(0, min(255, (int(color[3]) * int(coverage) + 127) // 255))
    if effective_alpha <= 0:
        return

    for py in range(y0, y1):
        for px in range(x0, x1):
            dst_alpha = _read_matrix_channel(matrix, py, px, 3)
            out_alpha = _source_over_alpha(dst_alpha, effective_alpha)
            for channel in range(3):
                dst = _read_matrix_channel(matrix, py, px, channel)
                value = _source_over_channel(int(color[channel]), dst, effective_alpha, dst_alpha, out_alpha)
                matrix[py : py + 1, px : px + 1, channel] = value
            matrix[py : py + 1, px : px + 1, 3] = out_alpha


def _read_matrix_channel(matrix, y: int, x: int, channel: int) -> int | None:
    try:
        value = matrix[y, x, channel]
    except (AttributeError, IndexError, KeyError, TypeError):
        return None
    try:
        if hasattr(value, "detach"):
            value = value.detach().cpu()
        if hasattr(value, "item"):
            value = value.item()
        elif hasattr(value, "tolist"):
            listed = value.tolist()
            while isinstance(listed, list):
                listed = listed[0]
            value = listed
        elif hasattr(value, "_data"):
            value = value._data[0]
        return max(0, min(255, int(value)))
    except (TypeError, ValueError):
        return None


def _source_over_channel(
    src: int,
    dst: int | None,
    src_alpha: int,
    dst_alpha: int | None,
    out_alpha: int,
) -> int:
    if src_alpha >= 255 or dst is None or dst_alpha is None or dst_alpha <= 0:
        return src
    if src_alpha <= 0:
        return 0 if dst is None else dst
    if out_alpha <= 0:
        return 0
    numerator = src * src_alpha * 255 + dst * dst_alpha * (255 - src_alpha)
    denominator = out_alpha * 255
    return max(0, min(255, (numerator + denominator // 2) // denominator))


def _source_over_alpha(dst: int | None, alpha: int) -> int:
    if dst is None:
        return alpha
    return alpha + (dst * (255 - alpha) + 127) // 255


def _fill_matrix_rect(
    matrix,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int, int],
    *,
    width: int,
    height: int,
) -> None:
    x0 = max(0, min(width, int(x0)))
    y0 = max(0, min(height, int(y0)))
    x1 = max(x0, min(width, int(x1)))
    y1 = max(y0, min(height, int(y1)))
    if x1 <= x0 or y1 <= y0:
        return
    for channel, value in enumerate(color):
        matrix[y0:y1, x0:x1, channel] = int(value)


class MatrixFrame(AbstractContextManager["MatrixFrame"]):
    def __init__(self, ctx: AppContext, clear: tuple[int, int, int, int] | str = (0, 0, 0, 255)) -> None:
        self._ctx = ctx
        self._clear = _rgba(clear)
        self._frame = None

    def __enter__(self) -> "MatrixFrame":
        snap = self._ctx.read_matrix_snapshot()
        h, w, _ = snap.shape
        self._frame = accel.zeros((h, w, 4))
        self._fill_rect(0, 0, w, h, self._clear)
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        if exc_type is None and self._frame is not None:
            self._ctx.submit_write_batch(WriteBatch([FullRewrite(self._frame, take_ownership=True)]))
        return False

    @property
    def width(self) -> int:
        assert self._frame is not None
        return int(self._frame.shape[1])

    @property
    def height(self) -> int:
        assert self._frame is not None
        return int(self._frame.shape[0])

    def shader_rect(self, shader: str, **kwargs: Any) -> None:
        _ = shader, kwargs

    def _point(self, x: float, y: float, frame: str | None = None) -> tuple[float, float]:
        return self._ctx.to_render_coords(float(x), float(y), frame=frame)

    def _rect(self, x: float, y: float, width: float, height: float, frame: str | None = None) -> tuple[float, float, float, float]:
        x0, y0 = self._point(x, y, frame=frame)
        x1, y1 = self._point(x + width, y + height, frame=frame)
        left = min(x0, x1)
        top = min(y0, y1)
        return left, top, abs(x1 - x0), abs(y1 - y0)

    def rect(self, *, x: float, y: float, width: float, height: float, color: tuple[int, int, int, int] | str, z_index: int = 0, frame: str | None = None) -> None:
        _ = z_index
        assert self._frame is not None
        rx, ry, rw, rh = self._rect(x, y, width, height, frame=frame)
        x0 = max(0, min(self.width, int(round(rx))))
        y0 = max(0, min(self.height, int(round(ry))))
        x1 = max(x0, min(self.width, int(round(rx + rw))))
        y1 = max(y0, min(self.height, int(round(ry + rh))))
        self._fill_rect(x0, y0, x1, y1, _rgba(color))

    def circle(self, *, cx: float, cy: float, radius: float, fill: tuple[int, int, int, int] | str, stroke: tuple[int, int, int, int] | str = (0, 0, 0, 0), stroke_width: float = 0.0, z_index: int = 0, frame: str | None = None) -> None:
        _ = z_index
        assert self._frame is not None
        cx, cy = self._point(cx, cy, frame=frame)
        fill_rgba = _rgba(fill)
        stroke_rgba = _rgba(stroke)
        r2 = radius * radius
        inner = max(0.0, radius - stroke_width)
        inner2 = inner * inner
        x0 = max(0, int(cx - radius - stroke_width))
        x1 = min(self.width - 1, int(cx + radius + stroke_width))
        y0 = max(0, int(cy - radius - stroke_width))
        y1 = min(self.height - 1, int(cy + radius + stroke_width))
        for yy in range(y0, y1 + 1):
            for xx in range(x0, x1 + 1):
                d2 = (float(xx) - cx) ** 2 + (float(yy) - cy) ** 2
                if d2 <= inner2:
                    self._fill_rect(xx, yy, xx + 1, yy + 1, fill_rgba)
                elif stroke_width > 0 and d2 <= r2:
                    self._fill_rect(xx, yy, xx + 1, yy + 1, stroke_rgba)

    def text(self, text: str, *, x: float, y: float, font_size_px: float = 14.0, color: tuple[int, int, int, int] | str = (255, 255, 255, 255), z_index: int = 0, cache_key: str | None = None, rotation_deg: float = 0.0, frame: str | None = None) -> None:
        _ = rotation_deg
        _ = z_index, cache_key
        assert self._frame is not None
        x, y = self._point(x, y, frame=frame)
        draw_text_to_matrix(self._frame, text, x=x, y=y, font_size_px=font_size_px, color=color)

    def _fill_rect(self, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int, int]) -> None:
        assert self._frame is not None
        if x1 <= x0 or y1 <= y0:
            return
        self._frame[y0:y1, x0:x1, 0] = int(color[0])
        self._frame[y0:y1, x0:x1, 1] = int(color[1])
        self._frame[y0:y1, x0:x1, 2] = int(color[2])
        self._frame[y0:y1, x0:x1, 3] = int(color[3])


class App:
    ctx: AppContext
    input: InputManager
    display: Display
    coordinates: CoordinateFrames
    sensors: Sensors

    def setup(self) -> None:
        pass

    def update(self, dt: float) -> None:
        pass

    def render(self) -> None:
        pass

    def teardown(self) -> None:
        pass

    def init(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self._continuous_render = True
        self._render_requested = True
        self.input = InputManager(ctx, on_activity=self.invalidate)
        self.display = Display(ctx)
        self.coordinates = CoordinateFrames(ctx)
        self.sensors = Sensors(ctx)
        self.setup()

    def loop(self, ctx: AppContext, dt: float) -> None:
        _ = ctx
        self.update(dt)
        if self._continuous_render or self._render_requested:
            self._render_requested = False
            self.render()

    def invalidate(self) -> None:
        """Request a render on the next app-loop tick."""
        self._render_requested = True

    def set_continuous_render(self, enabled: bool) -> None:
        """Choose continuous animation or render-on-invalidation scheduling."""
        self._continuous_render = bool(enabled)
        if enabled:
            self.invalidate()

    def set_scene_content_offset(self, x: float, y: float) -> None:
        """Move the retained scene without rebuilding its nodes."""
        self.ctx.set_scene_content_offset(float(x), float(y))

    def stop(self, ctx: AppContext) -> None:
        _ = ctx
        self.teardown()

    def frame(
        self,
        clear: tuple[int, int, int, int] | str = (0, 0, 0, 255),
        *,
        content_offset: tuple[float, float] = (0.0, 0.0),
        retained: bool = False,
    ) -> AbstractContextManager[Any]:
        manifest = getattr(self.ctx, "app_manifest", None)
        preferred = getattr(manifest, "render_preferred", "auto")
        fallbacks = list(getattr(manifest, "render_fallbacks", ["scene", "ui", "matrix"]))
        modes = fallbacks if preferred == "auto" else [preferred, *[m for m in fallbacks if m != preferred]]
        for mode in modes:
            if mode == "scene" and self.ctx.supports_scene_graph:
                return SceneFrame(self.ctx, clear=clear, content_offset=content_offset, retained=retained)
            if mode == "ui":
                try:
                    return UIFrame(self.ctx, clear=clear)
                except ImportError:
                    continue
            if mode == "matrix":
                return MatrixFrame(self.ctx, clear=clear)
        return MatrixFrame(self.ctx, clear=clear)

    def scene_frame(
        self,
        clear: tuple[int, int, int, int] | str = (0, 0, 0, 255),
        *,
        content_offset: tuple[float, float] = (0.0, 0.0),
        retained: bool = False,
    ) -> SceneFrame:
        return SceneFrame(self.ctx, clear=clear, content_offset=content_offset, retained=retained)

    def matrix_frame(self, clear: tuple[int, int, int, int] | str = (0, 0, 0, 255)) -> MatrixFrame:
        return MatrixFrame(self.ctx, clear=clear)


@dataclass(frozen=True)
class AppInstallValidation:
    app_dir: Path
    render: str
    target_platform: str
    manifest: AppManifest
    resolved_variant: ResolvedAppVariant
    required_extras: tuple[str, ...]
    missing_modules: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.missing_modules

    @property
    def install_hint(self) -> str:
        if self.ok or not self.required_extras:
            return ""
        extras = ",".join(self.required_extras)
        return f'Install the missing optional runtime with: pip install "luvatrix[{extras}]"'


class MissingOptionalDependencyError(RuntimeError):
    def __init__(self, validation: AppInstallValidation) -> None:
        missing = ", ".join(validation.missing_modules)
        hint = validation.install_hint
        message = f"render={validation.render!r} requires missing modules: {missing}"
        if hint:
            message = f"{message}. {hint}"
        super().__init__(message)
        self.validation = validation


class _NoopHDISource:
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        return []


def load_app_manifest(app_dir: str | Path, *, host_os: str | None = None, host_arch: str | None = None) -> AppManifest:
    return _manifest_runtime(host_os=host_os, host_arch=host_arch).load_manifest(app_dir)


def check_app_install(
    app_dir: str | Path,
    *,
    render: str = "headless",
    host_os: str | None = None,
    host_arch: str | None = None,
    module_available: Callable[[str], bool] | None = None,
) -> AppInstallValidation:
    if render not in RENDER_PLATFORM:
        raise ValueError(f"unsupported render target: {render}")

    render_platform = RENDER_PLATFORM[render]
    manifest_runtime = _manifest_runtime(host_os=render_platform or host_os, host_arch=host_arch)
    app_path = Path(app_dir)
    manifest = manifest_runtime.load_manifest(app_path)
    target_platform = render_platform or _infer_headless_target_platform(
        manifest,
        host_os=host_os,
    )
    runtime = _manifest_runtime(host_os=target_platform, host_arch=host_arch)
    resolved = runtime.resolve_variant(app_path.resolve(), manifest)

    module_available = module_available or _module_available
    missing_modules: list[str] = []
    required_extras: list[str] = []
    for extra, modules in RENDER_EXTRA_MODULES[render]:
        required_extras.append(extra)
        for module_name in modules:
            if not module_available(module_name):
                missing_modules.append(module_name)

    return AppInstallValidation(
        app_dir=app_path,
        render=render,
        target_platform=target_platform,
        manifest=manifest,
        resolved_variant=resolved,
        required_extras=tuple(dict.fromkeys(required_extras)),
        missing_modules=tuple(dict.fromkeys(missing_modules)),
    )


def validate_app_install(
    app_dir: str | Path,
    *,
    render: str = "headless",
    host_os: str | None = None,
    host_arch: str | None = None,
    module_available: Callable[[str], bool] | None = None,
) -> AppInstallValidation:
    validation = check_app_install(
        app_dir,
        render=render,
        host_os=host_os,
        host_arch=host_arch,
        module_available=module_available,
    )
    if not validation.ok:
        raise MissingOptionalDependencyError(validation)
    return validation


def _manifest_runtime(*, host_os: str | None = None, host_arch: str | None = None) -> AppRuntime:
    return AppRuntime(
        matrix=WindowMatrix(1, 1),
        hdi=HDIThread(source=_NoopHDISource()),
        sensor_manager=SensorManagerThread(providers={}),
        host_os=host_os,
        host_arch=host_arch,
    )


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _infer_headless_target_platform(manifest: AppManifest, *, host_os: str | None = None) -> str:
    normalized_host = _normalize_host_os(host_os or platform.system())
    if not manifest.platform_support or normalized_host in manifest.platform_support:
        return normalized_host

    supported = tuple(dict.fromkeys(manifest.platform_support))
    if len(supported) == 1:
        return supported[0]

    supported_display = ",".join(sorted(supported))
    raise RuntimeError(
        f"headless validation for app `{manifest.app_id}` cannot infer target platform from "
        f"host os `{normalized_host}`; supported={supported_display}. Use a platform render target "
        "such as --render android-emulator, --render ios-simulator, or --render web."
    )


def _normalize_host_os(value: str) -> str:
    normalized = value.strip().lower().replace("_", "").replace("-", "")
    aliases = {
        "darwin": PLATFORM_MACOS,
        "macos": PLATFORM_MACOS,
        "osx": PLATFORM_MACOS,
        "mac": PLATFORM_MACOS,
        "linux": PLATFORM_LINUX,
        "windows": PLATFORM_WINDOWS,
        "win": PLATFORM_WINDOWS,
        "android": PLATFORM_ANDROID,
        "ios": PLATFORM_IOS,
        "web": PLATFORM_WEB,
        "wasm": PLATFORM_WEB,
    }
    if normalized not in aliases:
        raise ValueError(f"unsupported os identifier: {value}")
    return aliases[normalized]


__all__ = [
    "APP_PROTOCOL_VERSION",
    "App",
    "PLATFORM_ANDROID",
    "PLATFORM_IOS",
    "PLATFORM_LINUX",
    "PLATFORM_MACOS",
    "PLATFORM_WEB",
    "PLATFORM_WINDOWS",
    "RENDER_EXTRA_MODULES",
    "RENDER_PLATFORM",
    "SUPPORTED_APP_PLATFORMS",
    "AppContext",
    "AppInstallValidation",
    "AppLifecycle",
    "AppManifest",
    "AppRuntime",
    "AppUIRenderer",
    "AppVariant",
    "BUILTIN_COORDINATE_FRAMES",
    "COORD_CARTESIAN_BL",
    "COORD_CARTESIAN_CENTER",
    "COORD_SCREEN_TL",
    "CoordinateFrames",
    "Display",
    "InputManager",
    "InputState",
    "MatrixFrame",
    "MissingOptionalDependencyError",
    "ResolvedAppVariant",
    "SceneFrame",
    "ScrollbarController",
    "ScrollbarMetrics",
    "ScrollbarUpdate",
    "Sensors",
    "SwipeMomentumController",
    "SwipeMomentumUpdate",
    "UIFrame",
    "apply_hdi_events",
    "check_app_install",
    "draw_text_to_matrix",
    "load_app_manifest",
    "validate_app_install",
]
