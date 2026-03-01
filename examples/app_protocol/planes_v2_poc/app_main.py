from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parents[2]
if str(REPO_ROOT) not in sys.path:
    # Allow running this example from source checkout without installing package.
    sys.path.insert(0, str(REPO_ROOT))

from luvatrix_core.core.ui_frame_renderer import MatrixUIFrameRenderer
from luvatrix_ui.component_schema import CoordinatePoint
from luvatrix_ui.controls.svg_component import SVGComponent
from luvatrix_ui.planes_protocol import compile_planes_to_ui_ir, resolve_web_metadata
from luvatrix_ui.text.component import TextComponent
from luvatrix_ui.text.renderer import TextAppearance, TextSizeSpec


PLANES_JSON = APP_DIR / "plane.json"


def _parse_hex_rgba(value: str) -> tuple[int, int, int, int]:
    raw = value.strip()
    if not raw.startswith("#"):
        raise ValueError(f"invalid color: {value}")
    h = raw[1:]
    if len(h) == 6:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
    if len(h) == 8:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16))
    raise ValueError(f"invalid color: {value}")


class PlanesV2PocApp:
    def __init__(self) -> None:
        self._renderer = MatrixUIFrameRenderer()
        self._planes = json.loads(PLANES_JSON.read_text(encoding="utf-8"))
        self._metadata = resolve_web_metadata(self._planes["app"])
        self._ui_page = compile_planes_to_ui_ir(self._planes, matrix_width=640, matrix_height=360)
        self._bg_color = _parse_hex_rgba(self._ui_page.background)

    def init(self, ctx) -> None:
        _ = ctx

    def loop(self, ctx, dt: float) -> None:
        _ = dt
        ctx.begin_ui_frame(
            self._renderer,
            content_width_px=float(self._ui_page.matrix.width),
            content_height_px=float(self._ui_page.matrix.height),
            clear_color=self._bg_color,
        )
        for component in self._ui_page.ordered_components_for_draw():
            if not component.visible:
                continue
            if component.component_type == "text":
                props = component.style if isinstance(component.style, dict) else {}
                text = str(props.get("text", component.component_id))
                color_hex = str(props.get("color_hex", "#f5fbff"))
                font_size_px = float(props.get("font_size_px", 14.0))
                ctx.mount_component(
                    TextComponent(
                        component_id=component.component_id,
                        text=text,
                        position=CoordinatePoint(component.position.x, component.position.y, component.resolved_frame(self._ui_page.default_frame)),
                        size=TextSizeSpec(unit="px", value=font_size_px),
                        appearance=TextAppearance(color_hex=color_hex, opacity=float(component.opacity)),
                    )
                )
                continue
            if component.component_type == "svg":
                if component.asset is None:
                    continue
                svg_path = (APP_DIR / component.asset.source).resolve()
                svg_markup = svg_path.read_text(encoding="utf-8")
                ctx.mount_component(
                    SVGComponent(
                        component_id=component.component_id,
                        svg_markup=svg_markup,
                        position=CoordinatePoint(component.position.x, component.position.y, component.resolved_frame(self._ui_page.default_frame)),
                        width=component.width,
                        height=component.height,
                        opacity=float(component.opacity),
                    )
                )
                continue
            # v0 viewport and other component types are validated but not rendered in this PoC.
        ctx.finalize_ui_frame()

    def stop(self, ctx) -> None:
        _ = ctx


class _ScriptHandlers:
    """PoC target-function namespace; placeholders for Planes function bindings."""

    @staticmethod
    def open_card(event_ctx: dict[str, Any], app_ctx: Any) -> None:
        _ = (event_ctx, app_ctx)

    @staticmethod
    def hover_logo(event_ctx: dict[str, Any], app_ctx: Any) -> None:
        _ = (event_ctx, app_ctx)

    @staticmethod
    def pan_timeline(event_ctx: dict[str, Any], app_ctx: Any) -> None:
        _ = (event_ctx, app_ctx)

    @staticmethod
    def select_task(event_ctx: dict[str, Any], app_ctx: Any) -> None:
        _ = (event_ctx, app_ctx)


def create():
    return PlanesV2PocApp()
