from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from luvatrix_ui.component_schema import CoordinatePoint
from luvatrix_ui.controls.svg_component import SVGComponent
from luvatrix_ui.planes_protocol import compile_planes_to_ui_ir, resolve_web_metadata
from luvatrix_ui.text.component import TextComponent
from luvatrix_ui.text.renderer import TextAppearance, TextSizeSpec

from luvatrix_core.core.ui_frame_renderer import MatrixUIFrameRenderer


EventHandler = Callable[[dict[str, Any], dict[str, Any]], object | None]


class PlaneApp:
    """Framework-managed Planes runtime lifecycle for App Protocol apps."""

    def __init__(
        self,
        plane_path: str | Path,
        *,
        handlers: dict[str, EventHandler] | None = None,
        strict: bool = True,
    ) -> None:
        self._plane_path = Path(plane_path).resolve()
        self._plane_dir = self._plane_path.parent
        self._handlers: dict[str, EventHandler] = dict(handlers or {})
        self._strict = strict
        self._renderer = MatrixUIFrameRenderer()
        self.state: dict[str, Any] = {}

        self._planes = json.loads(self._plane_path.read_text(encoding="utf-8"))
        self.metadata = resolve_web_metadata(self._planes["app"])
        self._ui_page = None
        self._bg_color = (0, 0, 0, 255)

    def register_handler(self, target: str, handler: EventHandler) -> None:
        self._handlers[target] = handler

    def init(self, ctx) -> None:
        self._ensure_compiled(ctx)

    def loop(self, ctx, dt: float) -> None:
        self._ensure_compiled(ctx)
        assert self._ui_page is not None
        self._dispatch_events(ctx, dt)

        ctx.begin_ui_frame(
            self._renderer,
            content_width_px=float(self._ui_page.matrix.width),
            content_height_px=float(self._ui_page.matrix.height),
            clear_color=self._bg_color,
        )
        for component in self._ui_page.ordered_components_for_draw():
            if not component.visible:
                continue
            frame = component.resolved_frame(self._ui_page.default_frame)
            if component.component_type == "text":
                props = component.style if isinstance(component.style, dict) else {}
                text = str(props.get("text", component.component_id))
                color_hex = str(props.get("color_hex", "#f5fbff"))
                font_size_px = float(props.get("font_size_px", 14.0))
                max_width_px = props.get("max_width_px")
                if max_width_px is not None:
                    max_width_px = float(max_width_px)
                ctx.mount_component(
                    TextComponent(
                        component_id=component.component_id,
                        text=text,
                        position=CoordinatePoint(component.position.x, component.position.y, frame),
                        size=TextSizeSpec(unit="px", value=font_size_px),
                        appearance=TextAppearance(color_hex=color_hex, opacity=float(component.opacity)),
                        max_width_px=max_width_px,
                    )
                )
                continue
            if component.component_type == "svg":
                if component.asset is None:
                    continue
                svg_path = (self._plane_dir / component.asset.source).resolve()
                svg_markup = svg_path.read_text(encoding="utf-8")
                ctx.mount_component(
                    SVGComponent(
                        component_id=component.component_id,
                        svg_markup=svg_markup,
                        position=CoordinatePoint(component.position.x, component.position.y, frame),
                        width=component.width,
                        height=component.height,
                        opacity=float(component.opacity),
                    )
                )
                continue
            # viewport and other component types are validated at compile-time.
        ctx.finalize_ui_frame()

    def stop(self, ctx) -> None:
        _ = ctx

    def _ensure_compiled(self, ctx) -> None:
        if self._ui_page is not None:
            return
        self._ui_page = compile_planes_to_ui_ir(
            self._planes,
            matrix_width=int(ctx.matrix.width),
            matrix_height=int(ctx.matrix.height),
            strict=self._strict,
        )
        self._bg_color = _parse_hex_rgba(self._ui_page.background)

    def _dispatch_events(self, ctx, dt: float) -> None:
        if self._ui_page is None:
            return
        events = ctx.poll_hdi_events(128)
        if not events:
            return
        for event in events:
            hook = _hook_for_event(event.event_type, event.payload)
            if hook is None:
                continue
            payload = event.payload if isinstance(event.payload, dict) else {}
            target_component = self._pick_component_for_event(payload)
            if target_component is None:
                continue
            for binding in target_component.interactions:
                if binding.event != hook:
                    continue
                handler = self._resolve_handler(binding.handler)
                if handler is None:
                    if self._strict:
                        raise RuntimeError(f"missing handler for target: {binding.handler}")
                    continue
                event_ctx = {
                    "component_id": target_component.component_id,
                    "event_type": event.event_type,
                    "hook": hook,
                    "payload": payload,
                    "dt": float(dt),
                }
                handler(event_ctx, self.state)

    def _pick_component_for_event(self, payload: dict[str, Any]):
        if self._ui_page is None:
            return None
        if "x" not in payload or "y" not in payload:
            return self._ui_page.ordered_components_for_hit_test()[0] if self._ui_page.components else None
        try:
            x = float(payload["x"])
            y = float(payload["y"])
        except (TypeError, ValueError):
            return None
        for component in self._ui_page.ordered_components_for_hit_test():
            bounds = component.resolved_interaction_bounds(self._ui_page.default_frame)
            if bounds.x <= x <= bounds.x + bounds.width and bounds.y <= y <= bounds.y + bounds.height:
                return component
        return None

    def _resolve_handler(self, target: str) -> EventHandler | None:
        if target in self._handlers:
            return self._handlers[target]
        if "::" in target:
            _, fn_name = target.split("::", 1)
            for key, handler in self._handlers.items():
                if key.endswith(f"::{fn_name}"):
                    return handler
        return None


def load_plane_app(
    plane_path: str | Path,
    *,
    handlers: dict[str, EventHandler] | None = None,
    strict: bool = True,
) -> PlaneApp:
    return PlaneApp(plane_path, handlers=handlers, strict=strict)


def _hook_for_event(event_type: str, payload: object) -> str | None:
    if event_type == "press" and isinstance(payload, dict):
        phase = payload.get("phase")
        phase_map = {
            "down": "on_press_down",
            "repeat": "on_press_repeat",
            "hold_start": "on_press_hold_start",
            "hold_tick": "on_press_hold_tick",
            "up": "on_press_up",
            "hold_end": "on_press_hold_end",
            "single": "on_press_single",
            "double": "on_press_double",
            "cancel": "on_press_cancel",
        }
        if phase in phase_map:
            return phase_map[phase]
    if event_type == "click":
        return "on_press_single"
    if event_type == "pointer_move":
        return "on_hover_start"
    if event_type == "scroll":
        return "on_scroll"
    if event_type == "pinch":
        return "on_pinch"
    if event_type == "rotate":
        return "on_rotate"
    return None


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
