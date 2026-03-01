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
        self.state.setdefault("active_theme", "default")
        self.state.setdefault("hover_component_id", None)
        self.state.setdefault("last_pointer_xy", None)

    def register_handler(self, target: str, handler: EventHandler) -> None:
        self._handlers[target] = handler

    def init(self, ctx) -> None:
        self._ensure_compiled(ctx)

    def loop(self, ctx, dt: float) -> None:
        self._ensure_compiled(ctx)
        assert self._ui_page is not None
        self._dispatch_events(ctx, dt)
        self._bg_color = self._resolve_background()

        ctx.begin_ui_frame(
            self._renderer,
            content_width_px=float(self._ui_page.matrix.width),
            content_height_px=float(self._ui_page.matrix.height),
            clear_color=self._bg_color,
        )
        ordered = self._ui_page.ordered_components_for_draw()
        for component in ordered:
            if not component.visible:
                continue
            if component.component_type == "viewport":
                self._mount_viewport_cutout_mask(ctx, component)
                continue
            frame = component.resolved_frame(self._ui_page.default_frame)
            resolved_x, resolved_y = self._resolved_position(component)
            if component.component_type == "text":
                props = component.style if isinstance(component.style, dict) else {}
                text = str(props.get("text", component.component_id))
                color_hex = self._resolve_text_color(component.component_id, props)
                font_size_px = float(props.get("font_size_px", 14.0))
                max_width_px = props.get("max_width_px")
                if max_width_px is not None:
                    max_width_px = float(max_width_px)
                ctx.mount_component(
                    TextComponent(
                        component_id=component.component_id,
                        text=text,
                        position=CoordinatePoint(resolved_x, resolved_y, frame),
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
                        position=CoordinatePoint(resolved_x, resolved_y, frame),
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
            payload = event.payload if isinstance(event.payload, dict) else {}
            self._record_pointer_xy(payload)
            if event.event_type == "pointer_move":
                self._dispatch_hover(payload, dt)
                continue
            hook = _hook_for_event(event.event_type, payload)
            if hook is None:
                continue
            target_component = self._pick_component_for_event(payload)
            if target_component is None:
                continue
            self._invoke_bindings(target_component, hook, event.event_type, payload, dt)

    def _dispatch_hover(self, payload: dict[str, Any], dt: float) -> None:
        if self._ui_page is None:
            return
        new_target = self._pick_component_for_event(payload)
        prev_id = self.state.get("hover_component_id")
        new_id = new_target.component_id if new_target is not None else None
        if prev_id == new_id:
            return
        prev_target = None
        if prev_id is not None:
            prev_target = next((c for c in self._ui_page.components if c.component_id == prev_id), None)
        if prev_target is not None:
            self._invoke_bindings(prev_target, "on_hover_end", "pointer_move", payload, dt)
        if new_target is not None:
            self._invoke_bindings(new_target, "on_hover_start", "pointer_move", payload, dt)
        self.state["hover_component_id"] = new_id

    def _pick_component_for_event(self, payload: dict[str, Any]):
        if self._ui_page is None:
            return None
        xy = self._extract_event_xy(payload)
        if xy is None:
            return None
        x, y = xy
        for component in self._ui_page.ordered_components_for_hit_test():
            bounds = component.resolved_interaction_bounds(self._ui_page.default_frame)
            resolved_x, resolved_y = self._resolved_position(component)
            if resolved_x <= x <= resolved_x + bounds.width and resolved_y <= y <= resolved_y + bounds.height:
                return component
        return None

    def _record_pointer_xy(self, payload: dict[str, Any]) -> None:
        xy = self._extract_xy_from_payload(payload)
        if xy is not None:
            self.state["last_pointer_xy"] = xy

    def _extract_event_xy(self, payload: dict[str, Any]) -> tuple[float, float] | None:
        direct = self._extract_xy_from_payload(payload)
        if direct is not None:
            return direct
        fallback = self.state.get("last_pointer_xy")
        if isinstance(fallback, tuple) and len(fallback) == 2:
            try:
                return (float(fallback[0]), float(fallback[1]))
            except (TypeError, ValueError):
                return None
        return None

    def _extract_xy_from_payload(self, payload: dict[str, Any]) -> tuple[float, float] | None:
        if "x" not in payload or "y" not in payload:
            return None
        try:
            return (float(payload["x"]), float(payload["y"]))
        except (TypeError, ValueError):
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

    def _invoke_bindings(
        self,
        component,
        hook: str,
        event_type: str,
        payload: dict[str, Any],
        dt: float,
    ) -> None:
        for binding in component.interactions:
            if binding.event != hook:
                continue
            handler = self._resolve_handler(binding.handler)
            if handler is None:
                if self._strict:
                    raise RuntimeError(f"missing handler for target: {binding.handler}")
                continue
            event_ctx = {
                "component_id": component.component_id,
                "event_type": event_type,
                "hook": hook,
                "payload": payload,
                "dt": float(dt),
            }
            handler(event_ctx, self.state)

    def _resolve_background(self) -> tuple[int, int, int, int]:
        if self._ui_page is None:
            return self._bg_color
        theme_name = str(self.state.get("active_theme", "default"))
        themes = self._planes.get("themes", {})
        if isinstance(themes, dict):
            entry = themes.get(theme_name)
            if isinstance(entry, dict):
                color = entry.get("background")
                if isinstance(color, str):
                    return _parse_hex_rgba(color)
        return _parse_hex_rgba(self._ui_page.background)

    def _resolve_text_color(self, component_id: str, props: dict[str, Any]) -> str:
        color_hex = str(props.get("color_hex", "#f5fbff"))
        theme_name = str(self.state.get("active_theme", "default"))
        theme_colors = props.get("theme_colors")
        if isinstance(theme_colors, dict):
            themed = theme_colors.get(theme_name)
            if isinstance(themed, str) and themed.strip():
                color_hex = themed
        hovered = self.state.get("hover_component_id")
        hover_hex = props.get("hover_color_hex")
        if hovered == component_id and isinstance(hover_hex, str) and hover_hex.strip():
            color_hex = hover_hex
        return color_hex

    def _resolved_position(self, component) -> tuple[float, float]:
        if self._ui_page is None:
            return (float(component.position.x), float(component.position.y))
        x = float(component.position.x)
        y = float(component.position.y)
        props = component.style if isinstance(component.style, dict) else {}
        align = str(props.get("align", "")).lower()
        if align == "center":
            x = (float(self._ui_page.matrix.width) - float(component.width)) / 2.0
        v_align = str(props.get("v_align", "")).lower()
        if v_align == "bottom":
            margin_bottom_px = float(props.get("margin_bottom_px", 0.0))
            y = float(self._ui_page.matrix.height) - float(component.height) - margin_bottom_px
        return (x, y)

    def _mount_viewport_cutout_mask(self, ctx, component) -> None:
        if self._ui_page is None:
            return
        frame = component.resolved_frame(self._ui_page.default_frame)
        bg = _rgba_to_hex(self._bg_color)
        x, y = self._resolved_position(component)
        w = float(component.width)
        h = float(component.height)
        full_w = float(self._ui_page.matrix.width)
        full_h = float(self._ui_page.matrix.height)

        # Four rectangles around the viewport create a "cutout window" effect.
        masks = [
            (0.0, 0.0, full_w, max(0.0, y)),  # top
            (0.0, y + h, full_w, max(0.0, full_h - (y + h))),  # bottom
            (0.0, y, max(0.0, x), h),  # left
            (x + w, y, max(0.0, full_w - (x + w)), h),  # right
        ]
        for i, (mx, my, mw, mh) in enumerate(masks):
            if mw <= 0 or mh <= 0:
                continue
            iw = int(round(mw))
            ih = int(round(mh))
            markup = (
                f'<svg width="{iw}" height="{ih}" '
                'xmlns="http://www.w3.org/2000/svg">'
                f'<rect x="0" y="0" width="{iw}" height="{ih}" fill="{bg}"/>'
                "</svg>"
            )
            ctx.mount_component(
                SVGComponent(
                    component_id=f"{component.component_id}__mask_{i}",
                    svg_markup=markup,
                    position=CoordinatePoint(mx, my, frame),
                    width=mw,
                    height=mh,
                    opacity=1.0,
                )
            )


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


def _rgba_to_hex(value: tuple[int, int, int, int]) -> str:
    return f"#{value[0]:02x}{value[1]:02x}{value[2]:02x}"
