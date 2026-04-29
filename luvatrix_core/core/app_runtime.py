from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
from pathlib import Path
import logging
import platform
import sys
import time
import tomllib
from typing import TYPE_CHECKING, Callable, Literal, Protocol

if TYPE_CHECKING:
    import torch
    from luvatrix_ui.component_schema import ComponentBase, DisplayableArea
    from luvatrix_ui.controls.svg_component import SVGComponent
    from luvatrix_ui.controls.stained_glass_button import StainedGlassButtonComponent, StainedGlassButtonRenderBatch
    from luvatrix_ui.controls.svg_renderer import SVGRenderBatch
    from luvatrix_ui.text.component import TextComponent
    from luvatrix_ui.text.renderer import TextLayoutMetrics, TextMeasureRequest, TextRenderBatch

from .hdi_thread import HDIEvent, HDIThread
from .coordinates import CoordinateFrameRegistry
from .frame_rate_controller import FrameRateController
from .protocol_governance import CURRENT_PROTOCOL_VERSION, check_protocol_compatibility
from .scene_graph import (
    CircleNode,
    ClearNode,
    RectNode,
    SceneBlitEvent,
    SceneFrame,
    SceneGraphBuffer,
    SceneNode,
    ShaderKind,
    ShaderRectNode,
    SceneTelemetry,
    TextNode,
)
from .sensor_manager import SensorManagerThread, SensorSample
from .window_matrix import CallBlitEvent, FullRewrite, ReplaceRect, ShiftFrame, WindowMatrix, WriteBatch
from luvatrix_core import accel
from luvatrix_core.perf.copy_telemetry import (
    add_copy_telemetry,
    begin_copy_telemetry_frame,
    snapshot_copy_telemetry,
)

LOGGER = logging.getLogger(__name__)
APP_PROTOCOL_VERSION = CURRENT_PROTOCOL_VERSION


class AppLifecycle(Protocol):
    def init(self, ctx: "AppContext") -> None:
        ...

    def loop(self, ctx: "AppContext", dt: float) -> None:
        ...

    def stop(self, ctx: "AppContext") -> None:
        ...


class AppUIRenderer(Protocol):
    """Component-to-matrix compiler contract used by first-party app protocol UI frames."""

    def begin_frame(self, display: DisplayableArea, clear_color: tuple[int, int, int, int]) -> None:
        ...

    def measure_text(self, request: TextMeasureRequest) -> TextLayoutMetrics:
        ...

    def draw_text_batch(self, batch: TextRenderBatch) -> None:
        ...

    def draw_svg_batch(self, batch: SVGRenderBatch) -> None:
        ...

    def draw_stained_glass_button_batch(self, batch: StainedGlassButtonRenderBatch) -> None:
        ...

    def end_frame(self) -> torch.Tensor:
        ...


@dataclass(frozen=True)
class AppDebugPolicy:
    schema_version: int = 1
    enable_default_debug_root: bool = True
    disable_debug_root_approval: str | None = None
    non_macos_behavior: Literal["explicit_stub"] = "explicit_stub"
    non_macos_stub_capability: str = "debug.policy.non_macos.stub"
    non_macos_unsupported_reason: str = "macOS-first phase: explicit stub only"


@dataclass(frozen=True)
class AppManifest:
    app_id: str
    protocol_version: str
    entrypoint: str
    required_capabilities: list[str]
    optional_capabilities: list[str]
    platform_support: list[str]
    variants: list["AppVariant"]
    runtime_kind: Literal["python_inproc", "process"] = "python_inproc"
    runtime_transport: Literal["stdio_jsonl"] = "stdio_jsonl"
    process_command: list[str] = field(default_factory=list)
    min_runtime_protocol_version: str | None = None
    max_runtime_protocol_version: str | None = None
    debug_policy: AppDebugPolicy = field(default_factory=AppDebugPolicy)
    display_native_width: int | None = None
    display_native_height: int | None = None
    display_bar_color_rgba: tuple[int, int, int, int] = (0, 0, 0, 255)


@dataclass(frozen=True)
class AppVariant:
    variant_id: str
    os: list[str]
    arch: list[str]
    module_root: str | None = None
    entrypoint: str | None = None


@dataclass(frozen=True)
class ResolvedAppVariant:
    variant_id: str
    entrypoint: str
    module_dir: Path


@dataclass
class AppContext:
    matrix: WindowMatrix
    hdi: HDIThread
    sensor_manager: SensorManagerThread
    granted_capabilities: set[str]
    security_audit_logger: Callable[[dict[str, object]], None] | None = None
    sensor_read_min_interval_s: float = 0.2
    logical_width_px: float | None = None
    logical_height_px: float | None = None
    coordinate_frames: CoordinateFrameRegistry | None = None
    scene_buffer: SceneGraphBuffer | None = None
    runtime_telemetry_provider: Callable[[], dict[str, object]] | None = None
    _last_sensor_read_ns: dict[str, int] = field(default_factory=dict)
    _ui_renderer: AppUIRenderer | None = field(default=None, init=False, repr=False)
    _ui_display: DisplayableArea | None = field(default=None, init=False, repr=False)
    _ui_components: list[ComponentBase] = field(default_factory=list, init=False, repr=False)
    _ui_dirty_rects: list[tuple[int, int, int, int]] | None = field(default=None, init=False, repr=False)
    _ui_scroll_shift: tuple[int, int] | None = field(default=None, init=False, repr=False)
    _ui_clear_color: tuple[int, int, int, int] = field(default=(0, 0, 0, 255), init=False, repr=False)
    _last_ui_copy_telemetry: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _scene_nodes: list[SceneNode] | None = field(default=None, init=False, repr=False)
    _scene_started_ns: int = field(default=0, init=False, repr=False)
    _scene_quality_tier: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.logical_width_px is None:
            self.logical_width_px = float(self.matrix.width)
        if self.logical_height_px is None:
            self.logical_height_px = float(self.matrix.height)
        if self.coordinate_frames is None:
            self.coordinate_frames = CoordinateFrameRegistry(
                width=int(round(float(self.logical_width_px))),
                height=int(round(float(self.logical_height_px))),
            )

    @property
    def display_width_px(self) -> float:
        return float(self.logical_width_px if self.logical_width_px is not None else self.matrix.width)

    @property
    def display_height_px(self) -> float:
        return float(self.logical_height_px if self.logical_height_px is not None else self.matrix.height)

    def submit_write_batch(self, batch: WriteBatch) -> CallBlitEvent:
        self._require_capability("window.write")
        return self.matrix.submit_write_batch(batch)

    def poll_hdi_events(self, max_events: int, frame: str | None = None) -> list[HDIEvent]:
        if max_events <= 0:
            raise ValueError("max_events must be > 0")
        events = self.hdi.poll_events(max_events=max_events)
        gated = [self._gate_hdi_event(event) for event in events]
        return [self._transform_hdi_event(event, frame=frame) for event in gated]

    def consume_hdi_telemetry(self) -> dict[str, int]:
        consumer = getattr(self.hdi, "consume_telemetry", None)
        if consumer is None or not callable(consumer):
            return {}
        payload = consumer()
        if not isinstance(payload, dict):
            return {}
        out: dict[str, int] = {}
        for key, value in payload.items():
            try:
                out[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
        return out

    def read_sensor(self, sensor_type: str) -> SensorSample:
        if not self._has_sensor_capability(sensor_type):
            self._audit_security("sensor_denied_capability", sensor_type=sensor_type)
            return SensorSample(
                sample_id=0,
                ts_ns=time.time_ns(),
                sensor_type=sensor_type,
                status="DENIED",
                value=None,
                unit=None,
            )
        now_ns = time.time_ns()
        min_delta_ns = int(self.sensor_read_min_interval_s * 1_000_000_000)
        last_ns = self._last_sensor_read_ns.get(sensor_type, 0)
        if now_ns - last_ns < min_delta_ns:
            self._audit_security("sensor_denied_rate_limit", sensor_type=sensor_type)
            return SensorSample(
                sample_id=0,
                ts_ns=now_ns,
                sensor_type=sensor_type,
                status="DENIED",
                value=None,
                unit=None,
            )
        self._last_sensor_read_ns[sensor_type] = now_ns
        sample = self.sensor_manager.read_sensor(sensor_type)
        return _sanitize_sensor_sample(sample, self.granted_capabilities)

    def read_matrix_snapshot(self) -> torch.Tensor:
        return self.matrix.read_snapshot()

    def has_capability(self, capability: str) -> bool:
        return capability in self.granted_capabilities

    @property
    def supports_scene_graph(self) -> bool:
        return self.scene_buffer is not None

    @property
    def default_coordinate_frame(self) -> str:
        assert self.coordinate_frames is not None
        return self.coordinate_frames.default_frame

    def set_default_coordinate_frame(self, frame_name: str) -> None:
        assert self.coordinate_frames is not None
        self.coordinate_frames.set_default_frame(frame_name)

    def define_coordinate_frame(
        self,
        name: str,
        origin: tuple[float, float],
        basis_x: tuple[float, float],
        basis_y: tuple[float, float],
    ) -> None:
        assert self.coordinate_frames is not None
        self.coordinate_frames.define_frame(name=name, origin=origin, basis_x=basis_x, basis_y=basis_y)

    def to_render_coords(self, x: float, y: float, frame: str | None = None) -> tuple[float, float]:
        assert self.coordinate_frames is not None
        return self.coordinate_frames.to_render_coords((float(x), float(y)), frame=frame)

    def from_render_coords(self, x: float, y: float, frame: str | None = None) -> tuple[float, float]:
        assert self.coordinate_frames is not None
        return self.coordinate_frames.from_render_coords((float(x), float(y)), frame=frame)

    def begin_ui_frame(
        self,
        renderer: AppUIRenderer,
        *,
        content_width_px: float | None = None,
        content_height_px: float | None = None,
        clear_color: tuple[int, int, int, int] = (0, 0, 0, 255),
        dirty_rects: list[tuple[int, int, int, int]] | None = None,
        scroll_shift: tuple[int, int] | None = None,
    ) -> None:
        from luvatrix_ui.component_schema import DisplayableArea  # lazy: avoids import cycle
        if self._ui_renderer is not None:
            raise RuntimeError("ui frame is already active")
        width = float(self.display_width_px if content_width_px is None else content_width_px)
        height = float(self.display_height_px if content_height_px is None else content_height_px)
        self._ui_display = DisplayableArea(
            content_width_px=width,
            content_height_px=height,
            viewport_width_px=float(self.matrix.width),
            viewport_height_px=float(self.matrix.height),
        )
        self._ui_renderer = renderer
        self._ui_components = []
        scale_x = float(self.matrix.width) / max(1.0, width)
        scale_y = float(self.matrix.height) / max(1.0, height)
        if dirty_rects is None:
            scaled_dirty_rects = None
        else:
            scaled_dirty_rects = [
                (
                    int(round(float(x) * scale_x)),
                    int(round(float(y) * scale_y)),
                    max(1, int(round(float(w) * scale_x))),
                    max(1, int(round(float(h) * scale_y))),
                )
                for (x, y, w, h) in dirty_rects
            ]
        self._ui_dirty_rects = _normalize_dirty_rects(scaled_dirty_rects, self.matrix.width, self.matrix.height)
        if scroll_shift is None:
            scaled_scroll_shift = None
        else:
            scaled_scroll_shift = (
                int(round(float(scroll_shift[0]) * scale_x)),
                int(round(float(scroll_shift[1]) * scale_y)),
            )
        self._ui_scroll_shift = _normalize_scroll_shift(scaled_scroll_shift)
        self._ui_clear_color = (
            int(clear_color[0]),
            int(clear_color[1]),
            int(clear_color[2]),
            int(clear_color[3]),
        )
        renderer.begin_frame(self._ui_display, clear_color)

    def mount_component(self, component: ComponentBase) -> None:
        if self._ui_renderer is None or self._ui_display is None:
            raise RuntimeError("ui frame is not active; call begin_ui_frame first")
        self._ui_components.append(component)

    def finalize_ui_frame(self) -> CallBlitEvent:
        from luvatrix_ui.text.component import TextComponent  # lazy: avoids import cycle
        from luvatrix_ui.text.renderer import TextRenderBatch
        from luvatrix_ui.controls.svg_component import SVGComponent
        from luvatrix_ui.controls.svg_renderer import SVGRenderBatch
        from luvatrix_ui.controls.stained_glass_button import StainedGlassButtonComponent, StainedGlassButtonRenderBatch
        if self._ui_renderer is None or self._ui_display is None:
            raise RuntimeError("ui frame is not active; call begin_ui_frame first")
        begin_copy_telemetry_frame()
        renderer = self._ui_renderer
        display = self._ui_display
        components = list(self._ui_components)
        try:
            for component in components:
                if isinstance(component, TextComponent):
                    command, _ = component.layout(
                        renderer,
                        display,
                        transformer=self.coordinate_frames,
                    )
                    renderer.draw_text_batch(TextRenderBatch(commands=(command,)))
                    continue
                if isinstance(component, SVGComponent):
                    command, _ = component.layout()
                    renderer.draw_svg_batch(SVGRenderBatch(commands=(command,)))
                    continue
                if isinstance(component, StainedGlassButtonComponent):
                    command, _ = component.layout()
                    renderer.draw_stained_glass_button_batch(StainedGlassButtonRenderBatch(commands=(command,)))
                    continue
                raise NotImplementedError(f"unsupported component type for ui frame: {type(component)!r}")
            frame = renderer.end_frame()
            if self._ui_dirty_rects:
                if self._ui_scroll_shift is not None and (self._ui_scroll_shift[0] != 0 or self._ui_scroll_shift[1] != 0):
                    fill = accel.from_sequence(list(self._ui_clear_color), (4,))
                    ops = [
                        ShiftFrame(dx=int(self._ui_scroll_shift[0]), dy=int(self._ui_scroll_shift[1]), fill_rgba_4=fill)
                    ]
                else:
                    ops = []
                ui_pack_ns = 0
                patch_bytes = 0
                for (x, y, w, h) in self._ui_dirty_rects:
                    started = time.perf_counter_ns()
                    patch = accel.clone(frame[y : y + h, x : x + w, :])
                    ui_pack_ns += time.perf_counter_ns() - started
                    patch_bytes += accel.numel(patch)
                    ops.append(
                        ReplaceRect(
                            x=x,
                            y=y,
                            width=w,
                            height=h,
                            rect_h_w_4=patch,
                        )
                    )
                add_copy_telemetry(
                    copy_count=max(0, len(self._ui_dirty_rects)),
                    copy_bytes=patch_bytes,
                    ui_pack_ns=ui_pack_ns,
                )
                return self.submit_write_batch(WriteBatch(ops))
            add_copy_telemetry(copy_count=1, copy_bytes=accel.numel(frame))
            return self.submit_write_batch(WriteBatch([FullRewrite(frame, take_ownership=True)]))
        finally:
            self._last_ui_copy_telemetry = snapshot_copy_telemetry()
            self._ui_renderer = None
            self._ui_display = None
            self._ui_components = []
            self._ui_dirty_rects = None
            self._ui_scroll_shift = None

    def consume_ui_copy_telemetry(self) -> dict[str, int]:
        payload = dict(self._last_ui_copy_telemetry)
        self._last_ui_copy_telemetry = {}
        return payload

    def runtime_telemetry(self) -> dict[str, object]:
        if self.runtime_telemetry_provider is None:
            return {}
        payload = self.runtime_telemetry_provider()
        return payload if isinstance(payload, dict) else {}

    def begin_scene_frame(self, *, adaptive_quality_tier: int = 0) -> None:
        self._require_capability("window.write")
        if self.scene_buffer is None:
            raise RuntimeError("scene graph rendering is not enabled for this runtime")
        if self._scene_nodes is not None:
            raise RuntimeError("scene frame is already active")
        self._scene_nodes = []
        self._scene_started_ns = time.perf_counter_ns()
        self._scene_quality_tier = int(adaptive_quality_tier)

    def add_scene_node(self, node: SceneNode) -> None:
        if self._scene_nodes is None:
            raise RuntimeError("scene frame is not active; call begin_scene_frame first")
        self._scene_nodes.append(node)

    def clear_scene(self, color_rgba: tuple[int, int, int, int]) -> None:
        self.add_scene_node(ClearNode(color_rgba=color_rgba))

    def draw_shader_rect(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        shader: ShaderKind = "solid",
        color_rgba: tuple[int, int, int, int] = (0, 0, 0, 255),
        uniforms: tuple[float, ...] = (),
        z_index: int = 0,
    ) -> None:
        self.add_scene_node(
            ShaderRectNode(
                x=x,
                y=y,
                width=width,
                height=height,
                shader=shader,
                color_rgba=color_rgba,
                uniforms=uniforms,
                z_index=z_index,
            )
        )

    def draw_rect(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        color_rgba: tuple[int, int, int, int],
        z_index: int = 0,
    ) -> None:
        self.add_scene_node(RectNode(x=x, y=y, width=width, height=height, color_rgba=color_rgba, z_index=z_index))

    def draw_circle(
        self,
        *,
        cx: float,
        cy: float,
        radius: float,
        fill_rgba: tuple[int, int, int, int],
        stroke_rgba: tuple[int, int, int, int] = (0, 0, 0, 0),
        stroke_width: float = 0.0,
        z_index: int = 0,
    ) -> None:
        self.add_scene_node(
            CircleNode(
                cx=cx,
                cy=cy,
                radius=radius,
                fill_rgba=fill_rgba,
                stroke_rgba=stroke_rgba,
                stroke_width=stroke_width,
                z_index=z_index,
            )
        )

    def draw_text(
        self,
        text: str,
        *,
        x: float,
        y: float,
        font_family: str = "Comic Mono",
        font_size_px: float = 14.0,
        color_rgba: tuple[int, int, int, int] = (255, 255, 255, 255),
        max_width_px: float | None = None,
        z_index: int = 0,
        cache_key: str | None = None,
    ) -> None:
        self.add_scene_node(
            TextNode(
                text=text,
                x=x,
                y=y,
                font_family=font_family,
                font_size_px=font_size_px,
                color_rgba=color_rgba,
                max_width_px=max_width_px,
                z_index=z_index,
                cache_key=cache_key,
            )
        )

    def finalize_scene_frame(self) -> SceneBlitEvent:
        if self.scene_buffer is None:
            raise RuntimeError("scene graph rendering is not enabled for this runtime")
        if self._scene_nodes is None:
            raise RuntimeError("scene frame is not active; call begin_scene_frame first")
        scene_encode_ms = (time.perf_counter_ns() - self._scene_started_ns) / 1_000_000.0
        try:
            frame = SceneFrame(
                revision=0,
                logical_width=max(1, int(round(self.display_width_px))),
                logical_height=max(1, int(round(self.display_height_px))),
                display_width=int(self.matrix.width),
                display_height=int(self.matrix.height),
                ts_ns=time.time_ns(),
                nodes=tuple(self._scene_nodes),
                telemetry=SceneTelemetry(scene_encode_ms=scene_encode_ms),
                adaptive_quality_tier=int(self._scene_quality_tier),
            )
            return self.scene_buffer.submit(frame)
        finally:
            self._scene_nodes = None
            self._scene_started_ns = 0
            self._scene_quality_tier = 0

    def _require_capability(self, capability: str) -> None:
        if capability not in self.granted_capabilities:
            raise PermissionError(f"missing capability: {capability}")

    def _gate_hdi_event(self, event: HDIEvent) -> HDIEvent:
        required = f"hdi.{event.device}"
        if required in self.granted_capabilities:
            return event
        return HDIEvent(
            event_id=event.event_id,
            ts_ns=event.ts_ns,
            window_id=event.window_id,
            device=event.device,
            event_type=event.event_type,
            status="DENIED",
            payload=None,
        )

    def _has_sensor_capability(self, sensor_type: str) -> bool:
        if "sensor.*" in self.granted_capabilities:
            return True
        if sensor_type in self.granted_capabilities:
            return True
        prefix = sensor_type.split(".", 1)[0]
        return f"sensor.{prefix}" in self.granted_capabilities

    def _audit_security(self, action: str, *, sensor_type: str) -> None:
        if self.security_audit_logger is None:
            return
        self.security_audit_logger(
            {
                "ts_ns": time.time_ns(),
                "action": action,
                "sensor_type": sensor_type,
                "actor": "app_context",
            }
        )

    def _transform_hdi_event(self, event: HDIEvent, frame: str | None) -> HDIEvent:
        if self.coordinate_frames is None:
            return event
        if event.payload is None or not isinstance(event.payload, dict):
            return event
        payload = dict(event.payload)
        if "x" in payload and "y" in payload:
            try:
                x = float(payload["x"])
                y = float(payload["y"])
                tx, ty = self.coordinate_frames.from_render_coords((x, y), frame=frame)
                payload["x"] = tx
                payload["y"] = ty
            except (TypeError, ValueError):
                return event
        if "delta_x" in payload and "delta_y" in payload:
            try:
                dx = float(payload["delta_x"])
                dy = float(payload["delta_y"])
                tdx, tdy = self.coordinate_frames.transform_vector(
                    (dx, dy),
                    from_frame="screen_tl",
                    to_frame=frame,
                )
                payload["delta_x"] = tdx
                payload["delta_y"] = tdy
            except (TypeError, ValueError):
                return event
        if "centroid_x" in payload and "centroid_y" in payload:
            try:
                x = float(payload["centroid_x"])
                y = float(payload["centroid_y"])
                tx, ty = self.coordinate_frames.from_render_coords((x, y), frame=frame)
                payload["centroid_x"] = tx
                payload["centroid_y"] = ty
            except (TypeError, ValueError):
                return event
        if "translation_x" in payload and "translation_y" in payload:
            try:
                dx = float(payload["translation_x"])
                dy = float(payload["translation_y"])
                tdx, tdy = self.coordinate_frames.transform_vector(
                    (dx, dy),
                    from_frame="screen_tl",
                    to_frame=frame,
                )
                payload["translation_x"] = tdx
                payload["translation_y"] = tdy
            except (TypeError, ValueError):
                return event
        return HDIEvent(
            event_id=event.event_id,
            ts_ns=event.ts_ns,
            window_id=event.window_id,
            device=event.device,
            event_type=event.event_type,
            status=event.status,
            payload=payload,
        )


def read_app_display_config(
    app_dir: str | Path,
) -> tuple[int | None, int | None, tuple[int, int, int, int]]:
    """Return (native_width, native_height, bar_color_rgba) from app.toml [display] section.

    Called before the runtime starts so callers can size the WindowMatrix and presenters
    before constructing UnifiedRuntime.  Returns (None, None, (0,0,0,255)) when the
    [display] section is absent or the file does not exist.
    """
    toml_path = Path(app_dir) / "app.toml"
    if not toml_path.exists():
        return None, None, (0, 0, 0, 255)
    with toml_path.open("rb") as f:
        raw = tomllib.load(f)
    d = raw.get("display", {})
    w = int(d["native_width"]) if "native_width" in d else None
    h = int(d["native_height"]) if "native_height" in d else None
    bar = d.get("bar_color_rgba", [0, 0, 0, 255])
    return w, h, (int(bar[0]), int(bar[1]), int(bar[2]), int(bar[3]))


class AppRuntime:
    def __init__(
        self,
        matrix: WindowMatrix,
        hdi: HDIThread,
        sensor_manager: SensorManagerThread,
        capability_decider: Callable[[str], bool] | None = None,
        capability_audit_logger: Callable[[dict[str, object]], None] | None = None,
        host_os: str | None = None,
        host_arch: str | None = None,
        logical_width_px: float | None = None,
        logical_height_px: float | None = None,
        scene_buffer: SceneGraphBuffer | None = None,
    ) -> None:
        self._matrix = matrix
        self._hdi = hdi
        self._sensor_manager = sensor_manager
        self._logical_width_px = float(logical_width_px) if logical_width_px is not None else float(matrix.width)
        self._logical_height_px = float(logical_height_px) if logical_height_px is not None else float(matrix.height)
        self._scene_buffer = scene_buffer
        self._capability_decider = capability_decider or (lambda capability: True)
        self._capability_audit_logger = capability_audit_logger
        self._host_os = _normalize_os_name(host_os or platform.system())
        self._host_arch = _normalize_arch_name(host_arch or platform.machine())
        self._last_error: Exception | None = None

    @property
    def last_error(self) -> Exception | None:
        return self._last_error

    def load_manifest(self, app_dir: str | Path) -> AppManifest:
        app_path = Path(app_dir)
        manifest_path = app_path / "app.toml"
        if not manifest_path.exists():
            raise FileNotFoundError(f"app manifest not found: {manifest_path}")
        with manifest_path.open("rb") as f:
            raw = tomllib.load(f)
        try:
            app_id = str(raw["app_id"])
            protocol_version = str(raw["protocol_version"])
            entrypoint = str(raw["entrypoint"])
        except KeyError as exc:
            raise ValueError(f"manifest missing required field: {exc.args[0]}") from exc
        required = _coerce_string_list(raw.get("required_capabilities", []), "required_capabilities")
        optional = _coerce_string_list(raw.get("optional_capabilities", []), "optional_capabilities")
        platform_support = _coerce_string_list(raw.get("platform_support", []), "platform_support")
        variants = _coerce_variants(raw.get("variants", []))
        min_runtime_protocol_version = _coerce_optional_str(
            raw.get("min_runtime_protocol_version"), "min_runtime_protocol_version"
        )
        max_runtime_protocol_version = _coerce_optional_str(
            raw.get("max_runtime_protocol_version"), "max_runtime_protocol_version"
        )
        runtime_raw = raw.get("runtime", {})
        runtime_kind, runtime_transport, process_command = _coerce_runtime_config(runtime_raw)
        debug_policy = _coerce_debug_policy(raw.get("debug_policy", None))
        display_raw = raw.get("display", {})
        display_native_width = int(display_raw["native_width"]) if "native_width" in display_raw else None
        display_native_height = int(display_raw["native_height"]) if "native_height" in display_raw else None
        bar_raw = display_raw.get("bar_color_rgba", [0, 0, 0, 255])
        display_bar_color_rgba = (int(bar_raw[0]), int(bar_raw[1]), int(bar_raw[2]), int(bar_raw[3]))
        manifest = AppManifest(
            app_id=app_id,
            protocol_version=protocol_version,
            entrypoint=entrypoint,
            required_capabilities=required,
            optional_capabilities=optional,
            platform_support=platform_support,
            variants=variants,
            runtime_kind=runtime_kind,
            runtime_transport=runtime_transport,
            process_command=process_command,
            min_runtime_protocol_version=min_runtime_protocol_version,
            max_runtime_protocol_version=max_runtime_protocol_version,
            debug_policy=debug_policy,
            display_native_width=display_native_width,
            display_native_height=display_native_height,
            display_bar_color_rgba=display_bar_color_rgba,
        )
        self._validate_manifest(manifest)
        return manifest

    def run(
        self,
        app_dir: str | Path,
        *,
        max_ticks: int = 1,
        target_fps: int = 60,
        present_fps: int | None = None,
        on_tick: Callable[[], None] | None = None,
        should_continue: Callable[[], bool] | None = None,
    ) -> None:
        if max_ticks <= 0:
            raise ValueError("max_ticks must be > 0")
        rate = FrameRateController(target_fps=target_fps, present_fps=present_fps)

        app_path = Path(app_dir).resolve()
        manifest = self.load_manifest(app_path)
        granted = self.resolve_capabilities(manifest)
        ctx = self.build_context(granted_capabilities=granted)
        resolved = self.resolve_variant(app_path, manifest)
        lifecycle = self.load_lifecycle(resolved.module_dir, resolved.entrypoint)

        self._hdi.start()
        self._sensor_manager.start()
        started = False
        try:
            lifecycle.init(ctx)
            started = True
            last = time.perf_counter()
            for _ in range(max_ticks):
                if should_continue is not None and not should_continue():
                    break
                if on_tick is not None:
                    on_tick()
                now = time.perf_counter()
                dt = max(0.0, now - last)
                last = now
                lifecycle.loop(ctx, dt)
                sleep_for = rate.compute_sleep(loop_started_at=now, loop_finished_at=time.perf_counter())
                if sleep_for > 0:
                    time.sleep(sleep_for)
        except Exception as exc:  # noqa: BLE001
            self._last_error = exc
            raise
        finally:
            if started:
                try:
                    lifecycle.stop(ctx)
                except Exception as exc:  # noqa: BLE001
                    self._last_error = exc
                    raise
            self._hdi.stop()
            self._sensor_manager.stop()

    def resolve_capabilities(self, manifest: AppManifest) -> set[str]:
        granted: set[str] = set()
        denied_required: list[str] = []
        for capability in manifest.required_capabilities:
            if self._capability_decider(capability):
                granted.add(capability)
                self._audit_capability("granted_required", capability)
            else:
                denied_required.append(capability)
                self._audit_capability("denied_required", capability)
        if denied_required:
            raise PermissionError(
                "required capabilities denied: " + ", ".join(sorted(denied_required))
            )
        for capability in manifest.optional_capabilities:
            if self._capability_decider(capability):
                granted.add(capability)
                self._audit_capability("granted_optional", capability)
            else:
                self._audit_capability("denied_optional", capability)
        return granted

    def build_context(self, granted_capabilities: set[str]) -> AppContext:
        return AppContext(
            matrix=self._matrix,
            hdi=self._hdi,
            sensor_manager=self._sensor_manager,
            granted_capabilities=granted_capabilities,
            security_audit_logger=self._capability_audit_logger,
            logical_width_px=self._logical_width_px,
            logical_height_px=self._logical_height_px,
            scene_buffer=self._scene_buffer,
            coordinate_frames=CoordinateFrameRegistry(
                width=int(round(self._logical_width_px)),
                height=int(round(self._logical_height_px)),
            ),
        )

    def resolve_debug_policy_profile(self, manifest: AppManifest) -> dict[str, object]:
        policy = manifest.debug_policy
        if self._host_os != "macos":
            return {
                "supported": False,
                "enable_default_debug_root": False,
                "declared_capabilities": [policy.non_macos_stub_capability],
                "unsupported_reason": policy.non_macos_unsupported_reason,
                "host_os": self._host_os,
            }
        if not policy.enable_default_debug_root:
            return {
                "supported": False,
                "enable_default_debug_root": False,
                "declared_capabilities": [],
                "unsupported_reason": "disabled by manifest debug_policy with explicit approval",
                "host_os": self._host_os,
            }
        return {
            "supported": True,
            "enable_default_debug_root": True,
            "declared_capabilities": ["debug.root.default"],
            "unsupported_reason": None,
            "host_os": self._host_os,
        }

    def load_lifecycle(self, app_dir: Path, entrypoint: str) -> AppLifecycle:
        module_name, symbol_name = _parse_entrypoint(entrypoint)
        module = _load_module_from_app_dir(app_dir, module_name)
        if not hasattr(module, symbol_name):
            raise ValueError(f"entrypoint symbol not found: {entrypoint}")
        symbol = getattr(module, symbol_name)
        lifecycle = symbol() if callable(symbol) else symbol
        for method_name in ("init", "loop", "stop"):
            method = getattr(lifecycle, method_name, None)
            if method is None or not callable(method):
                raise ValueError(f"entrypoint lifecycle missing callable `{method_name}`: {entrypoint}")
        return lifecycle

    def resolve_variant(self, app_dir: Path, manifest: AppManifest) -> ResolvedAppVariant:
        if manifest.platform_support and self._host_os not in manifest.platform_support:
            raise RuntimeError(
                f"app `{manifest.app_id}` does not support host os `{self._host_os}`; "
                f"supported={','.join(sorted(manifest.platform_support))}"
            )
        if not manifest.variants:
            return ResolvedAppVariant(
                variant_id="default",
                entrypoint=manifest.entrypoint,
                module_dir=app_dir,
            )

        candidates: list[AppVariant] = []
        for variant in manifest.variants:
            if self._host_os not in variant.os:
                continue
            if variant.arch and self._host_arch not in variant.arch:
                continue
            candidates.append(variant)
        if not candidates:
            raise RuntimeError(
                f"no app variant for host os={self._host_os} arch={self._host_arch} in `{manifest.app_id}`"
            )

        candidates.sort(key=lambda v: (0 if v.arch else 1, v.variant_id))
        selected = candidates[0]
        module_dir = app_dir
        if selected.module_root:
            candidate = (app_dir / selected.module_root).resolve()
            app_root = app_dir.resolve()
            if candidate != app_root and app_root not in candidate.parents:
                raise ValueError(f"variant `{selected.variant_id}` module_root escapes app directory")
            module_dir = candidate
        return ResolvedAppVariant(
            variant_id=selected.variant_id,
            entrypoint=selected.entrypoint or manifest.entrypoint,
            module_dir=module_dir,
        )

    def _validate_manifest(self, manifest: AppManifest) -> None:
        compat = check_protocol_compatibility(
            manifest.protocol_version,
            min_runtime_version=manifest.min_runtime_protocol_version,
            max_runtime_version=manifest.max_runtime_protocol_version,
        )
        if not compat.accepted:
            raise ValueError(compat.warning or "protocol compatibility check failed")
        if compat.warning:
            LOGGER.warning("%s", compat.warning)
        for os_name in manifest.platform_support:
            _normalize_os_name(os_name)
        variant_ids: set[str] = set()
        for variant in manifest.variants:
            if variant.variant_id in variant_ids:
                raise ValueError(f"duplicate variant id: {variant.variant_id}")
            variant_ids.add(variant.variant_id)
            if not variant.os:
                raise ValueError(f"variant `{variant.variant_id}` must declare at least one os")
            for os_name in variant.os:
                _normalize_os_name(os_name)
            for arch_name in variant.arch:
                _normalize_arch_name(arch_name)
        _parse_entrypoint(manifest.entrypoint)
        for variant in manifest.variants:
            if variant.entrypoint is not None:
                _parse_entrypoint(variant.entrypoint)
        if manifest.runtime_kind == "process" and not manifest.process_command:
            raise ValueError("runtime.kind=process requires runtime.command")
        if manifest.runtime_transport != "stdio_jsonl":
            raise ValueError(f"unsupported runtime transport: {manifest.runtime_transport}")
        if manifest.debug_policy.schema_version != 1:
            raise ValueError("debug_policy.schema_version must be 1")
        if manifest.debug_policy.non_macos_behavior != "explicit_stub":
            raise ValueError("debug_policy.non_macos_behavior must be explicit_stub")
        if (
            not manifest.debug_policy.enable_default_debug_root
            and not (manifest.debug_policy.disable_debug_root_approval or "").strip()
        ):
            raise ValueError(
                "debug_policy.disable_debug_root_approval is required when enable_default_debug_root=false"
            )

    def _audit_capability(self, action: str, capability: str) -> None:
        if self._capability_audit_logger is None:
            return
        self._capability_audit_logger(
            {
                "ts_ns": time.time_ns(),
                "action": action,
                "capability": capability,
                "actor": "app_runtime",
            }
        )


def _coerce_string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} entries must be strings")
        out.append(item)
    return out


def _coerce_optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string if provided")
    return value


def _coerce_runtime_config(value: object) -> tuple[Literal["python_inproc", "process"], Literal["stdio_jsonl"], list[str]]:
    if value is None:
        return ("python_inproc", "stdio_jsonl", [])
    if not isinstance(value, dict):
        raise ValueError("runtime must be a table/object")
    raw_kind = _coerce_optional_str(value.get("kind"), "runtime.kind") or "python_inproc"
    raw_transport = _coerce_optional_str(value.get("transport"), "runtime.transport") or "stdio_jsonl"
    command_raw = value.get("command", [])
    if raw_kind not in {"python_inproc", "process"}:
        raise ValueError(f"unsupported runtime kind: {raw_kind}")
    if raw_transport != "stdio_jsonl":
        raise ValueError(f"unsupported runtime transport: {raw_transport}")
    if not isinstance(command_raw, list):
        raise ValueError("runtime.command must be a list")
    command: list[str] = []
    for item in command_raw:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("runtime.command entries must be non-empty strings")
        command.append(item)
    return (raw_kind, raw_transport, command)


def _coerce_debug_policy(value: object) -> AppDebugPolicy:
    if value is None:
        return AppDebugPolicy()
    if not isinstance(value, dict):
        raise ValueError("debug_policy must be a table/object")

    schema_version = value.get("schema_version", 1)
    if not isinstance(schema_version, int):
        raise ValueError("debug_policy.schema_version must be an integer")

    enable_default_debug_root = value.get("enable_default_debug_root", True)
    if not isinstance(enable_default_debug_root, bool):
        raise ValueError("debug_policy.enable_default_debug_root must be a boolean")

    disable_debug_root_approval = _coerce_optional_str(
        value.get("disable_debug_root_approval"),
        "debug_policy.disable_debug_root_approval",
    )

    non_macos_behavior = _coerce_optional_str(
        value.get("non_macos_behavior"),
        "debug_policy.non_macos_behavior",
    ) or "explicit_stub"
    if non_macos_behavior != "explicit_stub":
        raise ValueError("debug_policy.non_macos_behavior must be explicit_stub")

    non_macos_stub_capability = _coerce_optional_str(
        value.get("non_macos_stub_capability"),
        "debug_policy.non_macos_stub_capability",
    ) or "debug.policy.non_macos.stub"
    if not non_macos_stub_capability.startswith("debug.") or ".stub" not in non_macos_stub_capability:
        raise ValueError("debug_policy.non_macos_stub_capability must be a debug.* stub capability")

    non_macos_unsupported_reason = _coerce_optional_str(
        value.get("non_macos_unsupported_reason"),
        "debug_policy.non_macos_unsupported_reason",
    ) or "macOS-first phase: explicit stub only"

    return AppDebugPolicy(
        schema_version=schema_version,
        enable_default_debug_root=enable_default_debug_root,
        disable_debug_root_approval=disable_debug_root_approval,
        non_macos_behavior=non_macos_behavior,
        non_macos_stub_capability=non_macos_stub_capability,
        non_macos_unsupported_reason=non_macos_unsupported_reason,
    )


def _coerce_variants(value: object) -> list[AppVariant]:
    if not isinstance(value, list):
        raise ValueError("variants must be a list")
    variants: list[AppVariant] = []
    for idx, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError("variants entries must be tables")
        try:
            variant_id = str(item["id"])
        except KeyError as exc:
            raise ValueError(f"variants[{idx}] missing required field: {exc.args[0]}") from exc
        os_list = _coerce_string_list(item.get("os", []), f"variants[{idx}].os")
        arch_list = _coerce_string_list(item.get("arch", []), f"variants[{idx}].arch")
        module_root = _coerce_optional_str(item.get("module_root"), f"variants[{idx}].module_root")
        entrypoint = _coerce_optional_str(item.get("entrypoint"), f"variants[{idx}].entrypoint")
        variants.append(
            AppVariant(
                variant_id=variant_id,
                os=[_normalize_os_name(x) for x in os_list],
                arch=[_normalize_arch_name(x) for x in arch_list],
                module_root=module_root,
                entrypoint=entrypoint,
            )
        )
    return variants


def _parse_entrypoint(entrypoint: str) -> tuple[str, str]:
    if ":" not in entrypoint:
        raise ValueError("entrypoint must use `module:symbol` format")
    module_name, symbol_name = entrypoint.split(":", 1)
    module_name = module_name.strip()
    symbol_name = symbol_name.strip()
    if not module_name or not symbol_name:
        raise ValueError("entrypoint must include non-empty module and symbol")
    return module_name, symbol_name


def _load_module_from_app_dir(app_dir: Path, module_name: str):
    rel_parts = module_name.split(".")
    module_path = app_dir.joinpath(*rel_parts).with_suffix(".py")
    if not module_path.exists():
        raise ValueError(f"entrypoint module file not found: {module_name}")
    unique_name = f"luvatrix_app_{abs(hash((str(app_dir), module_name)))}"
    spec = importlib.util.spec_from_file_location(unique_name, module_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"unable to load entrypoint module: {module_name}")
    module = importlib.util.module_from_spec(spec)
    # Register before execution so decorators/introspection (e.g. dataclasses)
    # can resolve cls.__module__ during module import.
    sys.modules[unique_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(unique_name, None)
        raise
    return module


def _sanitize_sensor_sample(sample: SensorSample, granted_capabilities: set[str]) -> SensorSample:
    if sample.status != "OK" or sample.value is None:
        return sample
    if "sensor.high_precision" in granted_capabilities:
        return sample
    value = sample.value
    if sample.sensor_type == "thermal.temperature" and isinstance(value, (int, float)):
        value = round(float(value) * 2.0) / 2.0
    elif sample.sensor_type == "power.voltage_current" and isinstance(value, dict):
        out: dict[str, object] = {}
        for k, v in value.items():
            if isinstance(v, (int, float)):
                out[k] = round(float(v), 1)
            else:
                out[k] = v
        value = out
    elif sample.sensor_type == "sensor.motion" and isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(v, (int, float)):
                out[k] = round(float(v), 0)
            else:
                out[k] = v
        value = out
    elif sample.sensor_type in {"camera.device", "microphone.device", "speaker.device"} and isinstance(value, dict):
        value = {
            "available": bool(value.get("available", False)),
            "device_count": int(value.get("device_count", 0)),
            "default_present": bool(value.get("default_present", False)),
        }
    return SensorSample(
        sample_id=sample.sample_id,
        ts_ns=sample.ts_ns,
        sensor_type=sample.sensor_type,
        status=sample.status,
        value=value,
        unit=sample.unit,
    )


def _normalize_dirty_rects(
    dirty_rects: list[tuple[int, int, int, int]] | None,
    matrix_width: int,
    matrix_height: int,
) -> list[tuple[int, int, int, int]] | None:
    if not dirty_rects:
        return None
    out: list[tuple[int, int, int, int]] = []
    for item in dirty_rects:
        if not isinstance(item, tuple) or len(item) != 4:
            continue
        try:
            x = int(item[0])
            y = int(item[1])
            w = int(item[2])
            h = int(item[3])
        except (TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        if x >= matrix_width or y >= matrix_height:
            continue
        cx = max(0, x)
        cy = max(0, y)
        cw = min(w - max(0, -x), matrix_width - cx)
        ch = min(h - max(0, -y), matrix_height - cy)
        if cw <= 0 or ch <= 0:
            continue
        out.append((cx, cy, cw, ch))
    if not out:
        return None
    out.sort(key=lambda r: (r[1], r[0], r[2], r[3]))
    return out


def _normalize_scroll_shift(scroll_shift: tuple[int, int] | None) -> tuple[int, int] | None:
    if scroll_shift is None:
        return None
    if not isinstance(scroll_shift, tuple) or len(scroll_shift) != 2:
        return None
    try:
        dx = int(scroll_shift[0])
        dy = int(scroll_shift[1])
    except (TypeError, ValueError):
        return None
    return (dx, dy)


def _normalize_os_name(value: str) -> str:
    normalized = value.strip().lower().replace("_", "").replace("-", "")
    aliases = {
        "darwin": "macos",
        "macos": "macos",
        "osx": "macos",
        "mac": "macos",
        "windows": "windows",
        "win": "windows",
        "linux": "linux",
        "android": "android",
        "ios": "ios",
        "web": "web",
        "wasm": "web",
    }
    if normalized not in aliases:
        raise ValueError(f"unsupported os identifier: {value}")
    return aliases[normalized]


def _normalize_arch_name(value: str) -> str:
    normalized = value.strip().lower().replace("_", "").replace("-", "")
    aliases = {
        "arm64": "arm64",
        "aarch64": "arm64",
        "x8664": "x86_64",
        "amd64": "x86_64",
        "x64": "x86_64",
    }
    if normalized not in aliases:
        raise ValueError(f"unsupported arch identifier: {value}")
    return aliases[normalized]
