from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
import time
from typing import Any, Callable


COORD_SCREEN_TL = "screen_tl"
COORD_CARTESIAN_BL = "cartesian_bl"
COORD_CARTESIAN_CENTER = "cartesian_center"
BUILTIN_COORDINATE_FRAMES = (COORD_SCREEN_TL, COORD_CARTESIAN_BL, COORD_CARTESIAN_CENTER)

OP_CLEAR = 1
OP_SHADER_RECT = 2
OP_RECT = 3
OP_CIRCLE = 4
OP_TEXT = 5
OP_CAMERA_3D = 6
OP_CUBE_3D = 7
OP_DOT_GRID_3D = 8
OP_LINE_3D = 9
OP_HORIZON_3D = 10
OP_TEXT_3D = 11
OP_GROUND_PLANE_3D = 12
OP_DOT_PLANE_3D = 13
OP_INFINITE_GROUND_3D = 14
OP_INFINITE_DOT_PLANE_3D = 15
OP_CUBOID_3D = 16
OP_INFINITE_GRID_3D = 17
OP_SPHERE_3D = 18
OP_ROUNDED_RECT = 19
OP_MODEL_3D = 20
OP_ROUNDED_CUBOID_3D = 21
OP_IMAGE_3D = 22
SHADER_IDS = {"solid": 1, "full_suite_background": 2}


@dataclass
class SensorSample:
    sample_id: int
    ts_ns: int
    sensor_type: str
    status: str
    value: object | None = None
    unit: str | None = None


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


class ScrollbarController:
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

    def metrics(self, *, track_extent: float, content_extent: float, viewport_extent: float, offset: float) -> ScrollbarMetrics:
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
        local_axis = pointer_axis - track_start
        in_track = (
            cross_start <= pointer_cross <= cross_start + max(0.0, cross_extent)
            and 0.0 <= local_axis <= track_extent
        )
        consumed = False
        if bool(state.left_clicked) and in_track and metrics.max_offset > 0.0:
            thumb_end = metrics.thumb_start + metrics.thumb_extent
            self._drag_anchor = (
                local_axis - metrics.thumb_start
                if metrics.thumb_start <= local_axis <= thumb_end
                else metrics.thumb_extent * 0.5
            )
            self._dragging = True
            consumed = True
        if self._dragging and bool(state.left_down):
            consumed = True
            thumb_start = min(max(0.0, local_axis - self._drag_anchor), metrics.travel_extent)
            clamped = (
                metrics.max_offset * thumb_start / metrics.travel_extent
                if metrics.travel_extent > 0.0
                else 0.0
            )
        elif self._dragging:
            consumed = True
            self._dragging = False
            self._drag_anchor = 0.0
        return ScrollbarUpdate(offset=clamped, consumed=consumed, dragging=self._dragging)


def apply_hdi_events(state: InputState, events: list[object]) -> InputState:
    for event in events:
        payload = getattr(event, "payload", event)
        if not isinstance(payload, dict):
            continue
        if "mouse_x" in payload:
            state.mouse_x = float(payload.get("mouse_x", state.mouse_x))
            state.mouse_y = float(payload.get("mouse_y", state.mouse_y))
        else:
            state.mouse_x = float(payload.get("x", state.mouse_x))
            state.mouse_y = float(payload.get("y", state.mouse_y))
        state.mouse_in_window = bool(payload.get("mouse_in_window", state.mouse_in_window))
        state.mouse_error = None if state.mouse_in_window else "window not active / pointer out of bounds"
        state.left_down = bool(payload.get("left_down", state.left_down))
        state.right_down = bool(payload.get("right_down", state.right_down))
        state.left_clicked = bool(payload.get("left_clicked", False))
        state.right_clicked = bool(payload.get("right_clicked", False))
        state.pressure = float(payload.get("pressure", state.pressure))
        state.pinch = float(payload.get("pinch", 0.0) or 0.0)
        state.rotation = float(payload.get("rotation", 0.0) or 0.0)
        state.scroll_x = float(payload.get("scroll_x", 0.0) or 0.0)
        state.scroll_y = float(payload.get("scroll_y", 0.0) or 0.0)
        state.key_last = str(payload.get("key_last", "") or "")
        state.key_state = str(payload.get("key_state", "") or "")
        keys_down = payload.get("keys_down")
        if isinstance(keys_down, list):
            state.keys_down = [str(k) for k in keys_down]
        touches = payload.get("active_touches")
        if isinstance(touches, dict):
            state.active_touches = {int(k): (float(v[0]), float(v[1])) for k, v in touches.items()}
            state.touch_count = len(state.active_touches)
        else:
            state.touch_count = int(payload.get("touch_count", state.touch_count))
    return state


class InputManager:
    def __init__(self, ctx: "BrowserAppContext") -> None:
        self._ctx = ctx
        self._state = InputState()

    @property
    def state(self) -> InputState:
        return self._state

    def snapshot(self, max_events: int = 256, frame: str | None = None) -> InputState:
        _ = max_events, frame
        payload = self._ctx.input_provider()
        if hasattr(payload, "to_py"):
            payload = payload.to_py()
        self._state.pinch = 0.0
        self._state.rotation = 0.0
        self._state.scroll_x = 0.0
        self._state.scroll_y = 0.0
        self._state.left_clicked = False
        self._state.right_clicked = False
        self._state.key_last = ""
        self._state.key_state = ""
        apply_hdi_events(self._state, [payload])
        return self._state


class Display:
    def __init__(self, ctx: "BrowserAppContext") -> None:
        self._ctx = ctx

    @property
    def width_px(self) -> int:
        return int(self._ctx.width)

    @property
    def height_px(self) -> int:
        return int(self._ctx.height)


class CoordinateFrames:
    def __init__(self, ctx: "BrowserAppContext") -> None:
        self._ctx = ctx

    @property
    def default(self) -> str:
        return self._ctx.default_coordinate_frame

    def set_default(self, frame: str) -> None:
        if frame not in BUILTIN_COORDINATE_FRAMES:
            raise ValueError(f"unsupported coordinate frame: {frame}")
        self._ctx.default_coordinate_frame = frame

    def cycle(self, frames: tuple[str, ...] | list[str] | None = None) -> str:
        order = tuple(frames or BUILTIN_COORDINATE_FRAMES)
        current = self.default
        next_frame = order[0] if current not in order else order[(order.index(current) + 1) % len(order)]
        self.set_default(next_frame)
        return next_frame

    def from_render(self, x: float, y: float, frame: str | None = None) -> tuple[float, float]:
        name = frame or self.default
        if name == COORD_CARTESIAN_BL:
            return (float(x), float(self._ctx.height) - float(y))
        if name == COORD_CARTESIAN_CENTER:
            return (float(x) - self._ctx.width / 2.0, self._ctx.height / 2.0 - float(y))
        return (float(x), float(y))

    def to_render(self, x: float, y: float, frame: str | None = None) -> tuple[float, float]:
        name = frame or self.default
        if name == COORD_CARTESIAN_BL:
            return (float(x), float(self._ctx.height) - float(y))
        if name == COORD_CARTESIAN_CENTER:
            return (float(x) + self._ctx.width / 2.0, self._ctx.height / 2.0 - float(y))
        return (float(x), float(y))

    def bind_switch_keys(
        self,
        input_state: InputState,
        keys: dict[str, str] | None = None,
        frames: tuple[str, ...] | list[str] | None = None,
    ) -> str | None:
        if input_state.key_state not in ("down", "single"):
            return None
        mapping = keys or {"1": COORD_SCREEN_TL, "2": COORD_CARTESIAN_BL, "3": COORD_CARTESIAN_CENTER, "c": "cycle"}
        target = mapping.get(input_state.key_last.strip().lower())
        if target is None:
            return None
        next_frame = self.cycle(frames) if target == "cycle" else target
        self.set_default(next_frame)
        return next_frame


class Sensors:
    def __init__(self, ctx: "BrowserAppContext") -> None:
        self._ctx = ctx

    def available(self) -> list[str]:
        return []

    def select(self, requested: list[str] | tuple[str, ...] | None = None, available: list[str] | None = None) -> list[str]:
        available_sensors = [] if available is None else list(available)
        if not requested:
            return available_sensors
        selected: list[str] = []
        for sensor in requested:
            if sensor not in available_sensors:
                raise ValueError(f"unsupported sensor `{sensor}` on this runtime; choose from: {', '.join(available_sensors)}")
            selected.append(sensor)
        return selected

    def read(self, sensor_type: str) -> SensorSample:
        return SensorSample(0, time.time_ns(), sensor_type, "UNAVAILABLE", None, None)

    def read_many(self, names: list[str] | tuple[str, ...]) -> dict[str, SensorSample]:
        return {name: self.read(name) for name in names}


class BrowserAppContext:
    def __init__(self, *, width: int, height: int, input_provider: Callable[[], object], manifest: dict[str, object]) -> None:
        self.width = int(width)
        self.height = int(height)
        self.input_provider = input_provider
        self.manifest = manifest
        display = manifest.get("display", {}) if isinstance(manifest, dict) else {}
        self.default_coordinate_frame = str(display.get("default_coordinate_frame") or COORD_SCREEN_TL)
        self._builder: CommandBufferBuilder | None = None

    @property
    def supports_scene_graph(self) -> bool:
        return True

    def begin_scene_frame(self) -> None:
        self._builder = CommandBufferBuilder(self.width, self.height)

    def clear_scene(self, color_rgba: tuple[int, int, int, int]) -> None:
        self._require_builder().clear(color_rgba)

    def draw_shader_rect(self, **kwargs: object) -> None:
        self._require_builder().shader_rect(**kwargs)

    def draw_rect(self, **kwargs: object) -> None:
        self._require_builder().rect(**kwargs)

    def draw_rounded_rect(self, **kwargs: object) -> None:
        self._require_builder().rounded_rect(**kwargs)

    def draw_circle(self, **kwargs: object) -> None:
        self._require_builder().circle(**kwargs)

    def draw_text(self, text: str, **kwargs: object) -> None:
        self._require_builder().text(text, **kwargs)

    def set_camera3d(self, **kwargs: object) -> None:
        self._require_builder().camera3d(**kwargs)

    def draw_cube3d(self, **kwargs: object) -> None:
        self._require_builder().cube3d(**kwargs)

    def draw_cuboid3d(self, **kwargs: object) -> None:
        self._require_builder().cuboid3d(**kwargs)

    def draw_rounded_cuboid3d(self, **kwargs: object) -> None:
        self._require_builder().rounded_cuboid3d(**kwargs)

    def draw_sphere3d(self, **kwargs: object) -> None:
        self._require_builder().sphere3d(**kwargs)

    def draw_model3d(self, **kwargs: object) -> None:
        self._require_builder().model3d(**kwargs)

    def draw_image3d(self, **kwargs: object) -> None:
        self._require_builder().image3d(**kwargs)

    def draw_dot_grid3d(self, **kwargs: object) -> None:
        self._require_builder().dot_grid3d(**kwargs)

    def draw_line3d(self, **kwargs: object) -> None:
        self._require_builder().line3d(**kwargs)

    def draw_dot_plane3d(self, **kwargs: object) -> None:
        self._require_builder().dot_plane3d(**kwargs)

    def draw_ground_plane3d(self, **kwargs: object) -> None:
        self._require_builder().ground_plane3d(**kwargs)

    def draw_infinite_ground3d(self, **kwargs: object) -> None:
        self._require_builder().infinite_ground3d(**kwargs)

    def draw_infinite_dot_plane3d(self, **kwargs: object) -> None:
        self._require_builder().infinite_dot_plane3d(**kwargs)

    def draw_infinite_grid3d(self, **kwargs: object) -> None:
        self._require_builder().infinite_grid3d(**kwargs)

    def draw_horizon3d(self, **kwargs: object) -> None:
        self._require_builder().horizon3d(**kwargs)

    def draw_text3d(self, text: str, **kwargs: object) -> None:
        self._require_builder().text3d(text, **kwargs)

    def finalize_scene_frame(self) -> dict[str, object]:
        return self._require_builder().finish()

    def runtime_telemetry(self) -> dict[str, object]:
        return {}

    def _require_builder(self) -> "CommandBufferBuilder":
        if self._builder is None:
            raise RuntimeError("scene frame has not started")
        return self._builder


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
    def __init__(self, ctx: BrowserAppContext, clear: tuple[int, int, int, int] | str = (0, 0, 0, 255)) -> None:
        self._ctx = ctx
        self._clear = _rgba(clear)

    def __enter__(self) -> "SceneFrame":
        self._ctx.begin_scene_frame()
        self._ctx.clear_scene(self._clear)
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        if exc_type is None:
            self._ctx.finalize_scene_frame()
        return False

    def _point(self, x: float, y: float, frame: str | None = None) -> tuple[float, float]:
        return CoordinateFrames(self._ctx).to_render(float(x), float(y), frame=frame)

    def _rect(self, x: float, y: float, width: float, height: float, frame: str | None = None) -> tuple[float, float, float, float]:
        x0, y0 = self._point(x, y, frame=frame)
        x1, y1 = self._point(x + width, y + height, frame=frame)
        left = min(x0, x1)
        top = min(y0, y1)
        return left, top, abs(x1 - x0), abs(y1 - y0)

    def shader_rect(self, shader: str, *, x: float = 0.0, y: float = 0.0, width: float | None = None, height: float | None = None, uniforms: tuple[float, ...] = (), z_index: int = 0, frame: str | None = None) -> None:
        _ = z_index
        rx, ry, rw, rh = self._rect(
            x,
            y,
            float(self._ctx.width if width is None else width),
            float(self._ctx.height if height is None else height),
            frame=frame,
        )
        self._ctx.draw_shader_rect(
            x=rx,
            y=ry,
            width=rw,
            height=rh,
            shader=shader,
            uniforms=uniforms,
        )

    def rect(self, *, x: float, y: float, width: float, height: float, color: tuple[int, int, int, int] | str, z_index: int = 0, frame: str | None = None) -> None:
        _ = z_index
        rx, ry, rw, rh = self._rect(x, y, width, height, frame=frame)
        self._ctx.draw_rect(x=rx, y=ry, width=rw, height=rh, color_rgba=_rgba(color))

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
        _ = z_index
        rx, ry, rw, rh = self._rect(x, y, width, height, frame=frame)
        self._ctx.draw_rounded_rect(x=rx, y=ry, width=rw, height=rh, radius=radius, color_rgba=_rgba(color))

    def circle(self, *, cx: float, cy: float, radius: float, fill: tuple[int, int, int, int] | str, stroke: tuple[int, int, int, int] | str = (0, 0, 0, 0), stroke_width: float = 0.0, z_index: int = 0, frame: str | None = None) -> None:
        _ = z_index
        rx, ry = self._point(cx, cy, frame=frame)
        self._ctx.draw_circle(cx=rx, cy=ry, radius=radius, fill_rgba=_rgba(fill), stroke_rgba=_rgba(stroke), stroke_width=stroke_width)

    def text(self, text: str, *, x: float, y: float, font_size_px: float = 14.0, color: tuple[int, int, int, int] | str = (255, 255, 255, 255), z_index: int = 0, cache_key: str | None = None, rotation_deg: float = 0.0, frame: str | None = None) -> None:
        _ = z_index, cache_key
        rx, ry = self._point(x, y, frame=frame)
        self._ctx.draw_text(text, x=rx, y=ry, font_size_px=font_size_px, color_rgba=_rgba(color), rotation_deg=rotation_deg)

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
        _ = z_index
        self._ctx.set_camera3d(position=position, target=target, up=up, fov_deg=fov_deg, near=near, far=far)

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
        _ = z_index
        self._ctx.draw_cube3d(center=center, size=size, rotation=rotation, color_rgba=_rgba(color), edge_rgba=_rgba(edge))

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
        _ = z_index
        self._ctx.draw_cuboid3d(center=center, size=size, rotation=rotation, color_rgba=_rgba(color), edge_rgba=_rgba(edge))

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
        _ = z_index
        self._ctx.draw_rounded_cuboid3d(center=center, size=size, rotation=rotation, radius=radius, color_rgba=_rgba(color), edge_rgba=_rgba(edge))

    def sphere3d(
        self,
        *,
        center: tuple[float, float, float] = (0.0, 0.0, 0.0),
        radius: float = 1.0,
        color: tuple[int, int, int, int] | str = (246, 208, 146, 255),
        edge: tuple[int, int, int, int] | str = (0, 0, 0, 0),
        z_index: int = 0,
    ) -> None:
        _ = z_index
        self._ctx.draw_sphere3d(center=center, radius=radius, color_rgba=_rgba(color), edge_rgba=_rgba(edge))

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
        _ = z_index
        self._ctx.draw_model3d(asset=asset, center=center, scale=scale, rotation=rotation, color_rgba=_rgba(color), edge_rgba=_rgba(edge))

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
        _ = z_index
        self._ctx.draw_image3d(asset=asset, center=center, size=size, rotation=rotation, opacity=opacity)

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
        _ = z_index
        self._ctx.draw_dot_grid3d(center=center, extent=extent, spacing=spacing, point_size=point_size, color_rgba=_rgba(color))

    def line3d(
        self,
        *,
        start: tuple[float, float, float],
        end: tuple[float, float, float],
        color: tuple[int, int, int, int] | str = (255, 255, 255, 255),
        width: float = 1.0,
        z_index: int = 0,
    ) -> None:
        _ = z_index
        self._ctx.draw_line3d(start_point=start, end_point=end, color_rgba=_rgba(color), width=width)

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
        _ = z_index
        self._ctx.draw_dot_plane3d(center=center, width=width, depth=depth, spacing=spacing, point_size=point_size, color_rgba=_rgba(color))

    def ground_plane3d(
        self,
        *,
        center: tuple[float, float, float] = (0.0, 0.0, -20.0),
        width: float = 40.0,
        depth: float = 40.0,
        color: tuple[int, int, int, int] | str = (26, 46, 34, 255),
        z_index: int = -20,
    ) -> None:
        _ = z_index
        self._ctx.draw_ground_plane3d(center=center, width=width, depth=depth, color_rgba=_rgba(color))

    def infinite_ground3d(
        self,
        *,
        y: float = 0.0,
        z_max: float = 0.0,
        render_distance: float = 120.0,
        color: tuple[int, int, int, int] | str = (26, 46, 34, 255),
        z_index: int = -20,
    ) -> None:
        _ = z_index
        self._ctx.draw_infinite_ground3d(y=y, z_max=z_max, render_distance=render_distance, color_rgba=_rgba(color))

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
        _ = z_index
        self._ctx.draw_infinite_dot_plane3d(
            y=y,
            z_max=z_max,
            spacing=spacing,
            point_size=point_size,
            render_distance=render_distance,
            color_rgba=_rgba(color),
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
        _ = z_index
        self._ctx.draw_infinite_grid3d(
            y=y,
            minor_spacing=minor_spacing,
            major_spacing=major_spacing,
            render_distance=render_distance,
            minor_rgba=_rgba(minor),
            major_rgba=_rgba(major),
            minor_width=minor_width,
            major_width=major_width,
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
        _ = z_index
        self._ctx.draw_horizon3d(
            sky_rgba=_rgba(sky),
            ground_rgba=_rgba(ground),
            horizon_rgba=_rgba(horizon),
            sky_horizon_rgba=None if sky_horizon is None else _rgba(sky_horizon),
            horizon_width=horizon_width,
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
        _ = z_index
        self._ctx.draw_text3d(
            text,
            position=position,
            height=height,
            depth=depth,
            color_rgba=_rgba(color),
            side_rgba=_rgba(side),
            font_family=font_family,
        )


class CommandBufferBuilder:
    def __init__(self, width: int, height: int) -> None:
        self.width = int(width)
        self.height = int(height)
        self.headers: list[int] = []
        self.floats: list[float] = []
        self.strings: list[str] = []
        self._string_ids: dict[str, int] = {}

    def clear(self, color_rgba: tuple[int, int, int, int]) -> None:
        self.headers.extend([OP_CLEAR, len(self.floats), 4, 0])
        self.floats.extend(_rgba_floats(color_rgba))

    def shader_rect(self, *, x: float, y: float, width: float, height: float, shader: str, color_rgba: tuple[int, int, int, int] = (0, 0, 0, 255), uniforms: tuple[float, ...] = ()) -> None:
        if shader not in SHADER_IDS:
            raise ValueError(f"unsupported web shader: {shader}")
        start = len(self.floats)
        values = [float(x), float(y), float(width), float(height), *_rgba_floats(color_rgba), *[float(v) for v in uniforms]]
        self.headers.extend([OP_SHADER_RECT, start, len(values), SHADER_IDS[shader]])
        self.floats.extend(values)

    def rect(self, *, x: float, y: float, width: float, height: float, color_rgba: tuple[int, int, int, int]) -> None:
        start = len(self.floats)
        values = [float(x), float(y), float(width), float(height), *_rgba_floats(color_rgba)]
        self.headers.extend([OP_RECT, start, len(values), 0])
        self.floats.extend(values)

    def rounded_rect(self, *, x: float, y: float, width: float, height: float, radius: float, color_rgba: tuple[int, int, int, int]) -> None:
        start = len(self.floats)
        values = [float(x), float(y), float(width), float(height), float(radius), *_rgba_floats(color_rgba)]
        self.headers.extend([OP_ROUNDED_RECT, start, len(values), 0])
        self.floats.extend(values)

    def circle(self, *, cx: float, cy: float, radius: float, fill_rgba: tuple[int, int, int, int], stroke_rgba: tuple[int, int, int, int] = (0, 0, 0, 0), stroke_width: float = 0.0) -> None:
        start = len(self.floats)
        values = [float(cx), float(cy), float(radius), *_rgba_floats(fill_rgba), *_rgba_floats(stroke_rgba), float(stroke_width)]
        self.headers.extend([OP_CIRCLE, start, len(values), 0])
        self.floats.extend(values)

    def text(self, text: str, *, x: float, y: float, font_family: str = "Comic Mono", font_size_px: float = 14.0, color_rgba: tuple[int, int, int, int] = (255, 255, 255, 255), max_width_px: float | None = None, rotation_deg: float = 0.0) -> None:
        text_id = self._intern(text)
        font_id = self._intern(font_family)
        start = len(self.floats)
        values = [float(x), float(y), float(font_size_px), *_rgba_floats(color_rgba), float(max_width_px or 0.0), float(rotation_deg)]
        self.headers.extend([OP_TEXT, start, len(values), text_id, font_id])
        self.floats.extend(values)

    def camera3d(self, *, position: tuple[float, float, float], target: tuple[float, float, float], up: tuple[float, float, float], fov_deg: float, near: float, far: float) -> None:
        start = len(self.floats)
        values = [*map(float, position), *map(float, target), *map(float, up), float(fov_deg), float(near), float(far)]
        self.headers.extend([OP_CAMERA_3D, start, len(values), 0])
        self.floats.extend(values)

    def cube3d(self, *, center: tuple[float, float, float], size: float, rotation: tuple[float, float, float], color_rgba: tuple[int, int, int, int], edge_rgba: tuple[int, int, int, int]) -> None:
        start = len(self.floats)
        values = [*map(float, center), float(size), *map(float, rotation), *_rgba_floats(color_rgba), *_rgba_floats(edge_rgba)]
        self.headers.extend([OP_CUBE_3D, start, len(values), 0])
        self.floats.extend(values)

    def cuboid3d(self, *, center: tuple[float, float, float], size: tuple[float, float, float], rotation: tuple[float, float, float], color_rgba: tuple[int, int, int, int], edge_rgba: tuple[int, int, int, int]) -> None:
        start = len(self.floats)
        values = [*map(float, center), *map(float, size), *map(float, rotation), *_rgba_floats(color_rgba), *_rgba_floats(edge_rgba)]
        self.headers.extend([OP_CUBOID_3D, start, len(values), 0])
        self.floats.extend(values)

    def rounded_cuboid3d(self, *, center: tuple[float, float, float], size: tuple[float, float, float], rotation: tuple[float, float, float], radius: float, color_rgba: tuple[int, int, int, int], edge_rgba: tuple[int, int, int, int]) -> None:
        start = len(self.floats)
        values = [*map(float, center), *map(float, size), *map(float, rotation), float(radius), *_rgba_floats(color_rgba), *_rgba_floats(edge_rgba)]
        self.headers.extend([OP_ROUNDED_CUBOID_3D, start, len(values), 0])
        self.floats.extend(values)

    def sphere3d(self, *, center: tuple[float, float, float], radius: float, color_rgba: tuple[int, int, int, int], edge_rgba: tuple[int, int, int, int]) -> None:
        start = len(self.floats)
        values = [*map(float, center), float(radius), *_rgba_floats(color_rgba), *_rgba_floats(edge_rgba)]
        self.headers.extend([OP_SPHERE_3D, start, len(values), 0])
        self.floats.extend(values)

    def model3d(self, *, asset: str, center: tuple[float, float, float], scale: tuple[float, float, float], rotation: tuple[float, float, float], color_rgba: tuple[int, int, int, int], edge_rgba: tuple[int, int, int, int]) -> None:
        asset_id = self._intern(asset)
        start = len(self.floats)
        values = [*map(float, center), *map(float, scale), *map(float, rotation), *_rgba_floats(color_rgba), *_rgba_floats(edge_rgba)]
        self.headers.extend([OP_MODEL_3D, start, len(values), asset_id])
        self.floats.extend(values)

    def image3d(self, *, asset: str, center: tuple[float, float, float], size: tuple[float, float], rotation: tuple[float, float, float], opacity: float) -> None:
        asset_id = self._intern(asset)
        start = len(self.floats)
        values = [*map(float, center), *map(float, size), *map(float, rotation), float(opacity)]
        self.headers.extend([OP_IMAGE_3D, start, len(values), asset_id])
        self.floats.extend(values)

    def dot_grid3d(self, *, center: tuple[float, float, float], extent: float, spacing: float, point_size: float, color_rgba: tuple[int, int, int, int]) -> None:
        start = len(self.floats)
        values = [*map(float, center), float(extent), float(spacing), float(point_size), *_rgba_floats(color_rgba)]
        self.headers.extend([OP_DOT_GRID_3D, start, len(values), 0])
        self.floats.extend(values)

    def line3d(self, *, start_point: tuple[float, float, float], end_point: tuple[float, float, float], color_rgba: tuple[int, int, int, int], width: float) -> None:
        start = len(self.floats)
        values = [*map(float, start_point), *map(float, end_point), *_rgba_floats(color_rgba), float(width)]
        self.headers.extend([OP_LINE_3D, start, len(values), 0])
        self.floats.extend(values)

    def dot_plane3d(self, *, center: tuple[float, float, float], width: float, depth: float, spacing: float, point_size: float, color_rgba: tuple[int, int, int, int]) -> None:
        start = len(self.floats)
        values = [*map(float, center), float(width), float(depth), float(spacing), float(point_size), *_rgba_floats(color_rgba)]
        self.headers.extend([OP_DOT_PLANE_3D, start, len(values), 0])
        self.floats.extend(values)

    def ground_plane3d(self, *, center: tuple[float, float, float], width: float, depth: float, color_rgba: tuple[int, int, int, int]) -> None:
        start = len(self.floats)
        values = [*map(float, center), float(width), float(depth), *_rgba_floats(color_rgba)]
        self.headers.extend([OP_GROUND_PLANE_3D, start, len(values), 0])
        self.floats.extend(values)

    def infinite_ground3d(self, *, y: float, z_max: float, render_distance: float, color_rgba: tuple[int, int, int, int]) -> None:
        start = len(self.floats)
        values = [float(y), float(z_max), float(render_distance), *_rgba_floats(color_rgba)]
        self.headers.extend([OP_INFINITE_GROUND_3D, start, len(values), 0])
        self.floats.extend(values)

    def infinite_dot_plane3d(self, *, y: float, z_max: float, spacing: float, point_size: float, render_distance: float, color_rgba: tuple[int, int, int, int]) -> None:
        start = len(self.floats)
        values = [float(y), float(z_max), float(spacing), float(point_size), float(render_distance), *_rgba_floats(color_rgba)]
        self.headers.extend([OP_INFINITE_DOT_PLANE_3D, start, len(values), 0])
        self.floats.extend(values)

    def infinite_grid3d(self, *, y: float, minor_spacing: float, major_spacing: float, render_distance: float, minor_rgba: tuple[int, int, int, int], major_rgba: tuple[int, int, int, int], minor_width: float, major_width: float) -> None:
        start = len(self.floats)
        values = [
            float(y),
            float(minor_spacing),
            float(major_spacing),
            float(render_distance),
            *_rgba_floats(minor_rgba),
            *_rgba_floats(major_rgba),
            float(minor_width),
            float(major_width),
        ]
        self.headers.extend([OP_INFINITE_GRID_3D, start, len(values), 0])
        self.floats.extend(values)

    def horizon3d(self, *, sky_rgba: tuple[int, int, int, int], ground_rgba: tuple[int, int, int, int], horizon_rgba: tuple[int, int, int, int], sky_horizon_rgba: tuple[int, int, int, int] | None, horizon_width: float) -> None:
        start = len(self.floats)
        sky_horizon = sky_rgba if sky_horizon_rgba is None else sky_horizon_rgba
        values = [*_rgba_floats(sky_rgba), *_rgba_floats(ground_rgba), *_rgba_floats(horizon_rgba), *_rgba_floats(sky_horizon), float(horizon_width)]
        self.headers.extend([OP_HORIZON_3D, start, len(values), 0])
        self.floats.extend(values)

    def text3d(self, text: str, *, position: tuple[float, float, float], height: float, depth: float, color_rgba: tuple[int, int, int, int], side_rgba: tuple[int, int, int, int], font_family: str) -> None:
        text_id = self._intern(text)
        font_id = self._intern(font_family)
        start = len(self.floats)
        values = [*map(float, position), float(height), float(depth), *_rgba_floats(color_rgba), *_rgba_floats(side_rgba)]
        self.headers.extend([OP_TEXT_3D, start, len(values), text_id, font_id])
        self.floats.extend(values)

    def finish(self) -> dict[str, object]:
        return {"headers": self.headers, "floats": self.floats, "strings": self.strings, "width": self.width, "height": self.height}

    def _intern(self, value: str) -> int:
        if value not in self._string_ids:
            self._string_ids[value] = len(self.strings)
            self.strings.append(value)
        return self._string_ids[value]


def _rgba_floats(color_rgba: tuple[int, int, int, int]) -> list[float]:
    return [max(0.0, min(1.0, float(ch) / 255.0)) for ch in color_rgba]


class App:
    ctx: BrowserAppContext
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

    def init_browser(self, *, width: int, height: int, input_provider: Callable[[], object], manifest: dict[str, object]) -> None:
        self.ctx = BrowserAppContext(width=width, height=height, input_provider=input_provider, manifest=manifest)
        self.input = InputManager(self.ctx)
        self.display = Display(self.ctx)
        self.coordinates = CoordinateFrames(self.ctx)
        self.sensors = Sensors(self.ctx)
        self.setup()

    def loop_browser(self, dt: float) -> dict[str, object]:
        self.update(float(dt))
        self.render()
        return self.ctx._require_builder().finish()

    def teardown_browser(self) -> None:
        self.teardown()

    def frame(self, clear: tuple[int, int, int, int] | str = (0, 0, 0, 255)) -> SceneFrame:
        return SceneFrame(self.ctx, clear=clear)

    def scene_frame(self, clear: tuple[int, int, int, int] | str = (0, 0, 0, 255)) -> SceneFrame:
        return SceneFrame(self.ctx, clear=clear)
