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
        state.pressure = float(payload.get("pressure", state.pressure))
        state.pinch = float(payload.get("pinch", state.pinch))
        state.rotation = float(payload.get("rotation", state.rotation))
        state.scroll_x = float(payload.get("scroll_x", state.scroll_x))
        state.scroll_y = float(payload.get("scroll_y", state.scroll_y))
        state.key_last = str(payload.get("key_last", state.key_last))
        state.key_state = str(payload.get("key_state", state.key_state))
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

    def draw_circle(self, **kwargs: object) -> None:
        self._require_builder().circle(**kwargs)

    def draw_text(self, text: str, **kwargs: object) -> None:
        self._require_builder().text(text, **kwargs)

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

    def shader_rect(self, shader: str, *, x: float = 0.0, y: float = 0.0, width: float | None = None, height: float | None = None, uniforms: tuple[float, ...] = (), z_index: int = 0) -> None:
        _ = z_index
        self._ctx.draw_shader_rect(
            x=x,
            y=y,
            width=float(self._ctx.width if width is None else width),
            height=float(self._ctx.height if height is None else height),
            shader=shader,
            uniforms=uniforms,
        )

    def rect(self, *, x: float, y: float, width: float, height: float, color: tuple[int, int, int, int] | str, z_index: int = 0) -> None:
        _ = z_index
        self._ctx.draw_rect(x=x, y=y, width=width, height=height, color_rgba=_rgba(color))

    def circle(self, *, cx: float, cy: float, radius: float, fill: tuple[int, int, int, int] | str, stroke: tuple[int, int, int, int] | str = (0, 0, 0, 0), stroke_width: float = 0.0, z_index: int = 0) -> None:
        _ = z_index
        self._ctx.draw_circle(cx=cx, cy=cy, radius=radius, fill_rgba=_rgba(fill), stroke_rgba=_rgba(stroke), stroke_width=stroke_width)

    def text(self, text: str, *, x: float, y: float, font_size_px: float = 14.0, color: tuple[int, int, int, int] | str = (255, 255, 255, 255), z_index: int = 0, cache_key: str | None = None) -> None:
        _ = z_index, cache_key
        self._ctx.draw_text(text, x=x, y=y, font_size_px=font_size_px, color_rgba=_rgba(color))


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

    def circle(self, *, cx: float, cy: float, radius: float, fill_rgba: tuple[int, int, int, int], stroke_rgba: tuple[int, int, int, int] = (0, 0, 0, 0), stroke_width: float = 0.0) -> None:
        start = len(self.floats)
        values = [float(cx), float(cy), float(radius), *_rgba_floats(fill_rgba), *_rgba_floats(stroke_rgba), float(stroke_width)]
        self.headers.extend([OP_CIRCLE, start, len(values), 0])
        self.floats.extend(values)

    def text(self, text: str, *, x: float, y: float, font_family: str = "Comic Mono", font_size_px: float = 14.0, color_rgba: tuple[int, int, int, int] = (255, 255, 255, 255), max_width_px: float | None = None) -> None:
        text_id = self._intern(text)
        font_id = self._intern(font_family)
        start = len(self.floats)
        values = [float(x), float(y), float(font_size_px), *_rgba_floats(color_rgba), float(max_width_px or 0.0)]
        self.headers.extend([OP_TEXT, start, len(values), text_id, font_id])
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
