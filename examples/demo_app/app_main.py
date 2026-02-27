from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

from luvatrix_core.core.ui_frame_renderer import MatrixUIFrameRenderer
from luvatrix_core.render.svg import SvgDocument
from luvatrix_ui.component_schema import CoordinatePoint
from luvatrix_ui.controls.svg_component import SVGComponent


APP_DIR = Path(__file__).resolve().parent
PAGE_JSON = APP_DIR / "page.json"


@dataclass(frozen=True)
class CompiledElement:
    element_id: str
    svg_markup: str
    x_bl: float
    y_bl: float
    width_px: float
    height_px: float
    opacity: float
    float_amp: float
    float_speed: float


@dataclass(frozen=True)
class CompiledPage:
    viewport_width: int
    viewport_height: int
    background_rgba: tuple[int, int, int, int]
    elements: list[CompiledElement]


def _parse_hex_color(value: str) -> tuple[int, int, int, int]:
    raw = value.strip()
    if not raw.startswith("#"):
        raise ValueError(f"background must be hex color, got: {value}")
    h = raw[1:]
    if len(h) == 6:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
    if len(h) == 8:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16))
    raise ValueError(f"background must be #RRGGBB or #RRGGBBAA, got: {value}")


def compile_page(page_path: Path) -> CompiledPage:
    raw = json.loads(page_path.read_text())
    viewport = raw.get("viewport", {})
    width = int(viewport.get("width", 640))
    height = int(viewport.get("height", 360))
    if width <= 0 or height <= 0:
        raise ValueError("viewport width/height must be > 0")
    background = _parse_hex_color(str(raw.get("background", "#000000")))

    compiled: list[CompiledElement] = []
    for item in raw.get("elements", []):
        if not isinstance(item, dict):
            continue
        element_id = str(item.get("id", "element"))
        svg_rel = str(item.get("svg", "")).strip()
        if not svg_rel:
            continue
        svg_path = (page_path.parent / svg_rel).resolve()
        if not svg_path.exists():
            raise FileNotFoundError(f"svg not found for element `{element_id}`: {svg_path}")
        svg_markup = svg_path.read_text()
        doc = SvgDocument.from_file(svg_path)
        scale = float(item.get("scale", 1.0))
        opacity = float(item.get("opacity", 1.0))
        if scale <= 0:
            raise ValueError(f"element `{element_id}` scale must be > 0")
        width_px = max(1.0, float(doc.width) * scale)
        height_px = max(1.0, float(doc.height) * scale)

        animate = item.get("animate")
        float_amp = 0.0
        float_speed = 0.0
        if isinstance(animate, dict) and str(animate.get("type", "")).strip() == "float":
            float_amp = float(animate.get("amp", 0.0))
            float_speed = float(animate.get("speed", 0.0))

        compiled.append(
            CompiledElement(
                element_id=element_id,
                svg_markup=svg_markup,
                x_bl=float(item.get("x", 0.0)),
                y_bl=float(item.get("y", 0.0)),
                width_px=width_px,
                height_px=height_px,
                opacity=opacity,
                float_amp=float_amp,
                float_speed=float_speed,
            )
        )

    return CompiledPage(
        viewport_width=width,
        viewport_height=height,
        background_rgba=background,
        elements=compiled,
    )


def _to_render_top_left(ctx, x_bl: float, y_bl: float, height_px: float) -> tuple[float, float]:
    x_render, y_render_bottom = ctx.to_render_coords(x_bl, y_bl, frame="cartesian_bl")
    y_render_top = y_render_bottom - height_px + 1.0
    return (x_render, y_render_top)


class DemoPageApp:
    def __init__(self) -> None:
        self._compiled = compile_page(PAGE_JSON)
        self._renderer = MatrixUIFrameRenderer()
        self._time_s = 0.0

    def init(self, ctx) -> None:
        ctx.set_default_coordinate_frame("cartesian_bl")

    def loop(self, ctx, dt: float) -> None:
        self._time_s += max(0.0, dt)
        ctx.begin_ui_frame(
            self._renderer,
            content_width_px=float(self._compiled.viewport_width),
            content_height_px=float(self._compiled.viewport_height),
            clear_color=self._compiled.background_rgba,
        )
        for element in self._compiled.elements:
            y_bl = element.y_bl
            if element.float_amp != 0.0 and element.float_speed != 0.0:
                y_bl += element.float_amp * math.sin(self._time_s * element.float_speed)
            x_tl, y_tl = _to_render_top_left(ctx, element.x_bl, y_bl, element.height_px)
            ctx.mount_component(
                SVGComponent(
                    component_id=element.element_id,
                    svg_markup=element.svg_markup,
                    position=CoordinatePoint(x_tl, y_tl, "screen_tl"),
                    width=element.width_px,
                    height=element.height_px,
                    opacity=element.opacity,
                )
            )
        ctx.finalize_ui_frame()

    def stop(self, ctx) -> None:
        _ = ctx


def create():
    return DemoPageApp()
