from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
import importlib.util
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
    ResolvedAppVariant,
)
from luvatrix_core.core.hdi_thread import HDIEvent, HDIThread
from luvatrix_core.core.sensor_manager import SensorManagerThread, SensorSample
from luvatrix_core.core.window_matrix import FullRewrite, WriteBatch, WindowMatrix
from luvatrix_core import accel

PLATFORM_MACOS = "macos"
PLATFORM_IOS = "ios"
PLATFORM_LINUX = "linux"
PLATFORM_WINDOWS = "windows"
PLATFORM_WEB = "web"

SUPPORTED_APP_PLATFORMS = (
    PLATFORM_MACOS,
    PLATFORM_IOS,
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
    "web": (
        ("web", ("websockets",)),
    ),
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
    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx
        self._state = InputState()

    @property
    def state(self) -> InputState:
        return self._state

    def raw_events(self, max_events: int = 256, frame: str | None = None) -> list[HDIEvent]:
        return self._ctx.poll_hdi_events(max_events=max_events, frame=frame)

    def snapshot(self, max_events: int = 256, frame: str | None = None) -> InputState:
        events = self.raw_events(max_events=max_events, frame=frame)
        apply_hdi_events(self._state, events)
        return self._state


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
                    state.pressure = float(payload.get("force", state.pressure))
                elif phase in ("up", "cancel"):
                    state.active_touches.pop(touch_id, None)
                state.touch_count = len(state.active_touches)
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
        if event_type == "click":
            button = int(payload.get("button", -1))
            phase = str(payload.get("phase", ""))
            is_down = phase == "down"
            if button == 0:
                state.left_down = is_down
            elif button == 1:
                state.right_down = is_down
        elif event_type == "pressure":
            state.pressure = float(payload.get("pressure", state.pressure))
        elif event_type == "pinch":
            state.pinch = float(payload.get("magnification", state.pinch))
        elif event_type == "rotate":
            state.rotation = float(payload.get("rotation", state.rotation))
        elif event_type == "scroll":
            state.scroll_x = float(payload.get("delta_x", state.scroll_x))
            state.scroll_y = float(payload.get("delta_y", state.scroll_y))
    return state


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
    def __init__(self, ctx: AppContext, clear: tuple[int, int, int, int] | str = (0, 0, 0, 255)) -> None:
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
        self._ctx.draw_shader_rect(
            x=x,
            y=y,
            width=float(self._ctx.display_width_px if width is None else width),
            height=float(self._ctx.display_height_px if height is None else height),
            shader=shader,
            uniforms=uniforms,
            z_index=z_index,
        )

    def rect(self, *, x: float, y: float, width: float, height: float, color: tuple[int, int, int, int] | str, z_index: int = 0) -> None:
        self._ctx.draw_rect(x=x, y=y, width=width, height=height, color_rgba=_rgba(color), z_index=z_index)

    def circle(self, *, cx: float, cy: float, radius: float, fill: tuple[int, int, int, int] | str, stroke: tuple[int, int, int, int] | str = (0, 0, 0, 0), stroke_width: float = 0.0, z_index: int = 0) -> None:
        self._ctx.draw_circle(
            cx=cx,
            cy=cy,
            radius=radius,
            fill_rgba=_rgba(fill),
            stroke_rgba=_rgba(stroke),
            stroke_width=stroke_width,
            z_index=z_index,
        )

    def text(self, text: str, *, x: float, y: float, font_size_px: float = 14.0, color: tuple[int, int, int, int] | str = (255, 255, 255, 255), z_index: int = 0, cache_key: str | None = None) -> None:
        self._ctx.draw_text(text, x=x, y=y, font_size_px=font_size_px, color_rgba=_rgba(color), z_index=z_index, cache_key=cache_key)


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

    def rect(self, *, x: float, y: float, width: float, height: float, color: tuple[int, int, int, int] | str, z_index: int = 0) -> None:
        from luvatrix_ui.component_schema import CoordinatePoint
        from luvatrix_ui.controls.svg_component import SVGComponent

        r, g, b, a = _rgba(color)
        markup = (
            f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            f'<rect x="0" y="0" width="{width}" height="{height}" fill="#{r:02x}{g:02x}{b:02x}{a:02x}"/>'
            "</svg>"
        )
        self._ctx.mount_component(SVGComponent(component_id=f"rect_{z_index}_{x}_{y}", svg_markup=markup, position=CoordinatePoint(x, y, "screen_tl"), width=width, height=height))

    def circle(self, *, cx: float, cy: float, radius: float, fill: tuple[int, int, int, int] | str, stroke: tuple[int, int, int, int] | str = (0, 0, 0, 0), stroke_width: float = 0.0, z_index: int = 0) -> None:
        from luvatrix_ui.component_schema import CoordinatePoint
        from luvatrix_ui.controls.svg_component import SVGComponent

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
        self._ctx.mount_component(SVGComponent(component_id=f"circle_{z_index}_{cx}_{cy}", svg_markup=markup, position=CoordinatePoint(cx - size / 2.0, cy - size / 2.0, "screen_tl"), width=size, height=size))

    def text(self, text: str, *, x: float, y: float, font_size_px: float = 14.0, color: tuple[int, int, int, int] | str = (255, 255, 255, 255), z_index: int = 0, cache_key: str | None = None) -> None:
        from luvatrix_ui.component_schema import CoordinatePoint
        from luvatrix_ui.text.component import TextComponent
        from luvatrix_ui.text.renderer import TextAppearance, TextSizeSpec

        r, g, b, _ = _rgba(color)
        self._ctx.mount_component(
            TextComponent(
                component_id=cache_key or f"text_{z_index}_{x}_{y}",
                text=text,
                position=CoordinatePoint(x, y, "screen_tl"),
                appearance=TextAppearance(color_hex=f"#{r:02x}{g:02x}{b:02x}"),
                size=TextSizeSpec(unit="px", value=font_size_px),
            )
        )


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

    def rect(self, *, x: float, y: float, width: float, height: float, color: tuple[int, int, int, int] | str, z_index: int = 0) -> None:
        _ = z_index
        assert self._frame is not None
        x0 = max(0, min(self.width, int(round(x))))
        y0 = max(0, min(self.height, int(round(y))))
        x1 = max(x0, min(self.width, int(round(x + width))))
        y1 = max(y0, min(self.height, int(round(y + height))))
        self._fill_rect(x0, y0, x1, y1, _rgba(color))

    def circle(self, *, cx: float, cy: float, radius: float, fill: tuple[int, int, int, int] | str, stroke: tuple[int, int, int, int] | str = (0, 0, 0, 0), stroke_width: float = 0.0, z_index: int = 0) -> None:
        _ = z_index
        assert self._frame is not None
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

    def text(self, text: str, *, x: float, y: float, font_size_px: float = 14.0, color: tuple[int, int, int, int] | str = (255, 255, 255, 255), z_index: int = 0, cache_key: str | None = None) -> None:
        _ = z_index, cache_key
        assert self._frame is not None
        scale = max(1, int(round(font_size_px / 7.0)))
        cursor = int(x)
        rgba = _rgba(color)
        for raw_ch in text.upper():
            glyph = _DEBUG_GLYPHS.get(raw_ch, _DEBUG_GLYPHS[" "])
            for gy, row in enumerate(glyph):
                for gx, bit in enumerate(row):
                    if bit != "1":
                        continue
                    self.rect(x=cursor + gx * scale, y=int(y) + gy * scale, width=scale, height=scale, color=rgba)
            cursor += 4 * scale

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
        self.input = InputManager(ctx)
        self.display = Display(ctx)
        self.coordinates = CoordinateFrames(ctx)
        self.sensors = Sensors(ctx)
        self.setup()

    def loop(self, ctx: AppContext, dt: float) -> None:
        _ = ctx
        self.update(dt)
        self.render()

    def stop(self, ctx: AppContext) -> None:
        _ = ctx
        self.teardown()

    def frame(self, clear: tuple[int, int, int, int] | str = (0, 0, 0, 255)) -> AbstractContextManager[Any]:
        manifest = getattr(self.ctx, "app_manifest", None)
        preferred = getattr(manifest, "render_preferred", "auto")
        fallbacks = list(getattr(manifest, "render_fallbacks", ["scene", "ui", "matrix"]))
        modes = fallbacks if preferred == "auto" else [preferred, *[m for m in fallbacks if m != preferred]]
        for mode in modes:
            if mode == "scene" and self.ctx.supports_scene_graph:
                return SceneFrame(self.ctx, clear=clear)
            if mode == "ui":
                try:
                    return UIFrame(self.ctx, clear=clear)
                except ImportError:
                    continue
            if mode == "matrix":
                return MatrixFrame(self.ctx, clear=clear)
        return MatrixFrame(self.ctx, clear=clear)

    def scene_frame(self, clear: tuple[int, int, int, int] | str = (0, 0, 0, 255)) -> SceneFrame:
        return SceneFrame(self.ctx, clear=clear)

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

    target_platform = RENDER_PLATFORM[render] or _normalize_host_os(host_os or platform.system())
    runtime = _manifest_runtime(host_os=target_platform, host_arch=host_arch)
    app_path = Path(app_dir)
    manifest = runtime.load_manifest(app_path)
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
    "Sensors",
    "UIFrame",
    "apply_hdi_events",
    "check_app_install",
    "load_app_manifest",
    "validate_app_install",
]
