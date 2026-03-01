from __future__ import annotations

import json
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable

from luvatrix_ui.component_schema import CoordinatePoint
from luvatrix_ui.controls.svg_component import SVGComponent
from luvatrix_ui.planes_protocol import compile_planes_to_ui_ir, resolve_web_metadata
from luvatrix_ui.text.component import TextComponent
from luvatrix_ui.text.renderer import TextAppearance, TextSizeSpec

from luvatrix_core.core.ui_frame_renderer import MatrixUIFrameRenderer


EventHandler = Callable[[dict[str, Any], dict[str, Any]], object | None]


@dataclass(frozen=True)
class ScrollIntent:
    delta_x: float
    delta_y: float
    source: str
    phase: str = "update"


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
        self._svg_markup_cache: dict[Path, str] = {}

        self._planes = json.loads(self._plane_path.read_text(encoding="utf-8"))
        self.metadata = resolve_web_metadata(self._planes["app"])
        self._ui_page = None
        self._bg_color = (0, 0, 0, 255)
        self.state.setdefault("active_theme", "default")
        self.state.setdefault("hover_component_id", None)
        self.state.setdefault("last_pointer_xy", None)
        self.state.setdefault("viewport_scroll", {})
        self.state.setdefault("plane_scroll", {"x": 0.0, "y": 0.0})
        self.state.setdefault("prefetch_margin_px", {"x": 96.0, "y": 96.0})
        self.state.setdefault("perf", {})
        self._component_index: dict[str, Any] = {}
        self._plane_index: dict[str, Any] = {}
        self._frame_perf: dict[str, float] = {}
        self._frame_counts: dict[str, int] = {}

    def register_handler(self, target: str, handler: EventHandler) -> None:
        self._handlers[target] = handler

    def init(self, ctx) -> None:
        self._ensure_compiled(ctx)

    def loop(self, ctx, dt: float) -> None:
        frame_start_ns = time.perf_counter_ns()
        self._begin_perf_frame()
        self._ensure_compiled(ctx)
        assert self._ui_page is not None
        input_start_ns = time.perf_counter_ns()
        self._dispatch_events(ctx, dt)
        self._add_perf_ns("input_ns", time.perf_counter_ns() - input_start_ns)
        self._bg_color = self._resolve_background()

        raster_start_ns = time.perf_counter_ns()
        ctx.begin_ui_frame(
            self._renderer,
            content_width_px=float(self._ui_page.matrix.width),
            content_height_px=float(self._ui_page.matrix.height),
            clear_color=self._bg_color,
        )
        self._add_perf_ns("raster_ns", time.perf_counter_ns() - raster_start_ns)
        ordered = self._ui_page.ordered_components_for_draw()
        viewport_content_refs = self._viewport_content_refs()
        prefetch_x, prefetch_y = self._prefetch_margins()
        considered = 0
        culled = 0
        mounted = 0
        for component in ordered:
            if not component.visible:
                continue
            if not self._component_is_active(component):
                continue
            considered += 1
            if component.component_id in viewport_content_refs:
                # Viewport content is rendered through the viewport camera pass.
                continue
            resolved_x, resolved_y = self._resolved_position(component)
            cull_start_ns = time.perf_counter_ns()
            if not self._is_component_in_camera_region(
                x=resolved_x,
                y=resolved_y,
                width=float(component.width),
                height=float(component.height),
                margin_x=prefetch_x,
                margin_y=prefetch_y,
            ):
                self._add_perf_ns("cull_ns", time.perf_counter_ns() - cull_start_ns)
                culled += 1
                continue
            self._add_perf_ns("cull_ns", time.perf_counter_ns() - cull_start_ns)
            if component.component_type == "viewport":
                mount_start_ns = time.perf_counter_ns()
                self._mount_viewport_cutout_mask(ctx, component)
                self._add_perf_ns("mount_ns", time.perf_counter_ns() - mount_start_ns)
                mounted += 1
                continue
            frame = component.resolved_frame(self._ui_page.default_frame)
            if component.component_type == "text":
                props = component.style if isinstance(component.style, dict) else {}
                text = str(props.get("text", component.component_id))
                color_hex = self._resolve_text_color(component.component_id, props)
                font_size_px = float(props.get("font_size_px", 14.0))
                max_width_px = props.get("max_width_px")
                if max_width_px is not None:
                    max_width_px = float(max_width_px)
                mount_start_ns = time.perf_counter_ns()
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
                self._add_perf_ns("mount_ns", time.perf_counter_ns() - mount_start_ns)
                mounted += 1
                continue
            if component.component_type == "svg":
                if component.asset is None:
                    continue
                svg_path = (self._plane_dir / component.asset.source).resolve()
                svg_markup = self._load_svg_markup(svg_path)
                mount_start_ns = time.perf_counter_ns()
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
                self._add_perf_ns("mount_ns", time.perf_counter_ns() - mount_start_ns)
                mounted += 1
                continue
            # viewport and other component types are validated at compile-time.
        mount_scrollbar_start_ns = time.perf_counter_ns()
        self._mount_plane_scrollbars(ctx)
        self._add_perf_ns("mount_ns", time.perf_counter_ns() - mount_scrollbar_start_ns)
        present_start_ns = time.perf_counter_ns()
        self.state["perf"] = {
            "components_considered": int(considered),
            "components_culled": int(culled),
            "components_mounted": int(mounted),
            "prefetch_margin_x_px": float(prefetch_x),
            "prefetch_margin_y_px": float(prefetch_y),
            "svg_cache_size": int(len(self._svg_markup_cache)),
            "events_polled": int(self._frame_counts.get("events_polled", 0)),
            "events_processed": int(self._frame_counts.get("events_processed", 0)),
            "scroll_events": int(self._frame_counts.get("scroll_events", 0)),
            "hit_test_calls": int(self._frame_counts.get("hit_test_calls", 0)),
            "timing_ms": {
                "input": self._ns_to_ms(self._frame_perf.get("input_ns", 0.0)),
                "hit_test": self._ns_to_ms(self._frame_perf.get("hit_test_ns", 0.0)),
                "scroll_update": self._ns_to_ms(self._frame_perf.get("scroll_update_ns", 0.0)),
                "cull": self._ns_to_ms(self._frame_perf.get("cull_ns", 0.0)),
                "mount": self._ns_to_ms(self._frame_perf.get("mount_ns", 0.0)),
                "raster": self._ns_to_ms(self._frame_perf.get("raster_ns", 0.0)),
                "present": 0.0,
                "frame_total": 0.0,
            },
        }
        ctx.finalize_ui_frame()
        self._add_perf_ns("present_ns", time.perf_counter_ns() - present_start_ns)
        self._add_perf_ns("frame_total_ns", time.perf_counter_ns() - frame_start_ns)
        perf = self.state.get("perf")
        if isinstance(perf, dict):
            timings = perf.get("timing_ms")
            if isinstance(timings, dict):
                timings["present"] = self._ns_to_ms(self._frame_perf.get("present_ns", 0.0))
                timings["frame_total"] = self._ns_to_ms(self._frame_perf.get("frame_total_ns", 0.0))

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
        self._component_index = {component.component_id: component for component in self._ui_page.components}
        self._plane_index = {plane.plane_id: plane for plane in getattr(self._ui_page, "plane_manifest", ())}
        self._initialize_viewport_scroll_state()
        self._initialize_plane_scroll_state()
        self._bg_color = _parse_hex_rgba(self._ui_page.background)

    def _dispatch_events(self, ctx, dt: float) -> None:
        if self._ui_page is None:
            return
        events = ctx.poll_hdi_events(128)
        self._frame_counts["events_polled"] = int(len(events))
        if not events:
            return
        for event in events:
            self._frame_counts["events_processed"] = int(self._frame_counts.get("events_processed", 0)) + 1
            payload = event.payload if isinstance(event.payload, dict) else {}
            self._record_pointer_xy(payload)
            intent = _scroll_intent_from_event(event.event_type, payload)
            if intent is not None:
                self._frame_counts["scroll_events"] = int(self._frame_counts.get("scroll_events", 0)) + 1
                self._dispatch_viewport_scroll(payload, intent)
            if event.event_type == "pointer_move":
                self._dispatch_hover(payload, dt)
                continue
            hook = _hook_for_event(event.event_type, payload)
            target_component = self._pick_component_for_event(payload)
            if hook is None:
                continue
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
        hit_start_ns = time.perf_counter_ns()
        self._frame_counts["hit_test_calls"] = int(self._frame_counts.get("hit_test_calls", 0)) + 1
        xy = self._extract_event_xy(payload)
        if xy is None:
            self._add_perf_ns("hit_test_ns", time.perf_counter_ns() - hit_start_ns)
            return None
        x, y = xy
        for component in self._ui_page.ordered_components_for_hit_test():
            if not self._component_is_active(component):
                continue
            bounds = component.resolved_interaction_bounds(self._ui_page.default_frame)
            resolved_x, resolved_y = self._resolved_position(component)
            if resolved_x <= x <= resolved_x + bounds.width and resolved_y <= y <= resolved_y + bounds.height:
                self._add_perf_ns("hit_test_ns", time.perf_counter_ns() - hit_start_ns)
                return component
        self._add_perf_ns("hit_test_ns", time.perf_counter_ns() - hit_start_ns)
        return None

    def _viewport_stack_for_point(self, x: float, y: float) -> list[Any]:
        if self._ui_page is None:
            return []
        stack: list[Any] = []
        for component in self._ui_page.ordered_components_for_hit_test():
            if not self._component_is_active(component):
                continue
            if component.component_type != "viewport":
                continue
            bounds = component.resolved_interaction_bounds(self._ui_page.default_frame)
            resolved_x, resolved_y = self._resolved_position(component)
            if resolved_x <= x <= resolved_x + bounds.width and resolved_y <= y <= resolved_y + bounds.height:
                stack.append(component)
        return stack

    def _dispatch_viewport_scroll(self, payload: dict[str, Any], intent: ScrollIntent) -> None:
        scroll_start_ns = time.perf_counter_ns()
        xy = self._extract_event_xy(payload)
        if xy is None:
            self._add_perf_ns("scroll_update_ns", time.perf_counter_ns() - scroll_start_ns)
            return
        px, py = xy
        stack = self._viewport_stack_for_point(px, py)
        rem_x = float(intent.delta_x)
        rem_y = float(intent.delta_y)
        for viewport in stack:
            consumed_x, consumed_y = self._apply_viewport_scroll_intent(
                viewport,
                ScrollIntent(delta_x=rem_x, delta_y=rem_y, source=intent.source, phase=intent.phase),
            )
            rem_x -= consumed_x
            rem_y -= consumed_y
            if abs(rem_x) <= 1e-9 and abs(rem_y) <= 1e-9:
                break
        if abs(rem_x) > 1e-9 or abs(rem_y) > 1e-9:
            self._apply_plane_scroll_intent(ScrollIntent(delta_x=rem_x, delta_y=rem_y, source=intent.source, phase=intent.phase))
        self._add_perf_ns("scroll_update_ns", time.perf_counter_ns() - scroll_start_ns)

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
        x, y = self._resolved_position_base(component)
        if self._is_overlay_attached(component) or self._is_camera_fixed(component):
            return (x, y)
        plane_x, plane_y = self._plane_scroll_position()
        return (x - plane_x, y - plane_y)

    def _prefetch_margins(self) -> tuple[float, float]:
        entry = self.state.get("prefetch_margin_px")
        if isinstance(entry, dict):
            try:
                mx = max(0.0, float(entry.get("x", 96.0)))
                my = max(0.0, float(entry.get("y", 96.0)))
                return (mx, my)
            except (TypeError, ValueError):
                return (96.0, 96.0)
        return (96.0, 96.0)

    def _is_component_in_camera_region(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        margin_x: float,
        margin_y: float,
    ) -> bool:
        if self._ui_page is None:
            return True
        view_w = float(self._ui_page.matrix.width)
        view_h = float(self._ui_page.matrix.height)
        left = -margin_x
        top = -margin_y
        right = view_w + margin_x
        bottom = view_h + margin_y
        comp_right = x + max(0.0, width)
        comp_bottom = y + max(0.0, height)
        if comp_right < left:
            return False
        if comp_bottom < top:
            return False
        if x > right:
            return False
        if y > bottom:
            return False
        return True

    def _load_svg_markup(self, svg_path: Path) -> str:
        cached = self._svg_markup_cache.get(svg_path)
        if cached is not None:
            return cached
        markup = svg_path.read_text(encoding="utf-8")
        self._svg_markup_cache[svg_path] = markup
        return markup

    def _begin_perf_frame(self) -> None:
        self._frame_perf = {}
        self._frame_counts = {
            "events_polled": 0,
            "events_processed": 0,
            "scroll_events": 0,
            "hit_test_calls": 0,
        }

    def _add_perf_ns(self, key: str, delta_ns: int) -> None:
        self._frame_perf[key] = float(self._frame_perf.get(key, 0.0) + max(0, int(delta_ns)))

    @staticmethod
    def _ns_to_ms(value_ns: float) -> float:
        return float(value_ns) / 1_000_000.0

    def _resolved_position_base(self, component) -> tuple[float, float]:
        if self._ui_page is None:
            return (float(component.position.x), float(component.position.y))
        x = float(component.position.x)
        y = float(component.position.y)
        if self._ui_page.ir_version == "planes-v2":
            plane_id = getattr(component, "plane_id", None)
            if isinstance(plane_id, str) and plane_id:
                plane = self._plane_index.get(plane_id)
                if plane is not None:
                    x += float(plane.resolved_position.x)
                    y += float(plane.resolved_position.y)
        props = component.style if isinstance(component.style, dict) else {}
        align = str(props.get("align", "")).lower()
        if align == "center":
            x = (float(self._ui_page.matrix.width) - float(component.width)) / 2.0
        v_align = str(props.get("v_align", "")).lower()
        if v_align == "bottom":
            margin_bottom_px = float(props.get("margin_bottom_px", 0.0))
            y = float(self._ui_page.matrix.height) - float(component.height) - margin_bottom_px
        return (x, y)

    def _is_camera_fixed(self, component) -> bool:
        props = component.style if isinstance(component.style, dict) else {}
        return bool(props.get("camera_fixed", False))

    def _is_overlay_attached(self, component) -> bool:
        return str(getattr(component, "attachment_kind", "plane")) == "camera_overlay"

    def _component_is_active(self, component) -> bool:
        if self._ui_page is None:
            return True
        if self._ui_page.ir_version != "planes-v2":
            return True
        if self._is_overlay_attached(component):
            return True
        active = set(getattr(self._ui_page, "active_plane_ids", ()))
        if not active:
            return True
        plane_id = getattr(component, "plane_id", None)
        if not isinstance(plane_id, str):
            return False
        return plane_id in active

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
        self._mount_viewport_content(ctx, component, x=x, y=y, frame=frame)

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
        self._mount_viewport_scrollbars(ctx, component, x=x, y=y, frame=frame)


    def _initialize_viewport_scroll_state(self) -> None:
        if self._ui_page is None:
            return
        state = self.state.setdefault("viewport_scroll", {})
        if not isinstance(state, dict):
            state = {}
            self.state["viewport_scroll"] = state
        for component in self._ui_page.components:
            if component.component_type != "viewport":
                continue
            style = component.style if isinstance(component.style, dict) else {}
            scroll = style.get("scroll")
            sx = 0.0
            sy = 0.0
            if isinstance(scroll, dict):
                sx = float(scroll.get("x", 0.0))
                sy = float(scroll.get("y", 0.0))
            cx, cy = self._clamp_viewport_scroll(component, sx, sy)
            state[component.component_id] = {"x": cx, "y": cy}

    def _initialize_plane_scroll_state(self) -> None:
        state = self.state.setdefault("plane_scroll", {"x": 0.0, "y": 0.0})
        if not isinstance(state, dict):
            state = {"x": 0.0, "y": 0.0}
            self.state["plane_scroll"] = state
        try:
            sx = float(state.get("x", 0.0))
            sy = float(state.get("y", 0.0))
        except (TypeError, ValueError):
            sx = 0.0
            sy = 0.0
        cx, cy = self._clamp_plane_scroll(sx, sy)
        state["x"] = cx
        state["y"] = cy

    def _plane_scroll_position(self) -> tuple[float, float]:
        state = self.state.get("plane_scroll")
        if isinstance(state, dict):
            try:
                return (float(state.get("x", 0.0)), float(state.get("y", 0.0)))
            except (TypeError, ValueError):
                return (0.0, 0.0)
        return (0.0, 0.0)

    def _clamp_plane_scroll(self, x: float, y: float) -> tuple[float, float]:
        max_x, max_y = self._plane_scroll_limits()
        cx = min(max(0.0, float(x)), max_x)
        cy = min(max(0.0, float(y)), max_y)
        return (cx, cy)

    def _plane_scroll_limits(self) -> tuple[float, float]:
        if self._ui_page is None:
            return (0.0, 0.0)
        max_x = 0.0
        max_y = 0.0
        refs = self._viewport_content_refs()
        for component in self._ui_page.components:
            if not component.visible:
                continue
            if component.component_id in refs:
                continue
            if self._is_overlay_attached(component) or self._is_camera_fixed(component):
                continue
            if not self._component_is_active(component):
                continue
            base_x, base_y = self._resolved_position_base(component)
            right = base_x + float(component.width)
            bottom = base_y + float(component.height)
            max_x = max(max_x, right - float(self._ui_page.matrix.width))
            max_y = max(max_y, bottom - float(self._ui_page.matrix.height))
        return (max_x, max_y)

    def _apply_plane_scroll_intent(self, intent: ScrollIntent) -> tuple[float, float]:
        state = self.state.setdefault("plane_scroll", {"x": 0.0, "y": 0.0})
        if not isinstance(state, dict):
            state = {"x": 0.0, "y": 0.0}
            self.state["plane_scroll"] = state
        cur_x, cur_y = self._plane_scroll_position()
        next_x = cur_x + float(intent.delta_x)
        next_y = cur_y + float(intent.delta_y)
        clamped_x, clamped_y = self._clamp_plane_scroll(next_x, next_y)
        state["x"] = clamped_x
        state["y"] = clamped_y
        return (clamped_x - cur_x, clamped_y - cur_y)

    def _mount_plane_scrollbars(self, ctx) -> None:
        if self._ui_page is None:
            return
        max_x, max_y = self._plane_scroll_limits()
        if max_x <= 1e-9 and max_y <= 1e-9:
            return
        view_w = float(self._ui_page.matrix.width)
        view_h = float(self._ui_page.matrix.height)
        scroll_x, scroll_y = self._plane_scroll_position()
        frame = self._ui_page.default_frame
        track_color = "#1f344d"
        thumb_color = "#9bc9f8"

        if max_x > 1e-9:
            track_h = 6.0
            track_x = 4.0
            track_y = view_h - track_h - 2.0
            track_w = max(16.0, view_w - 12.0)
            track_markup = (
                '<svg width="100" height="10" xmlns="http://www.w3.org/2000/svg">'
                f'<rect x="0" y="0" width="100" height="10" rx="4" fill="{track_color}"/>'
                "</svg>"
            )
            ctx.mount_component(
                SVGComponent(
                    component_id="__plane_scrollbar_x_track",
                    svg_markup=track_markup,
                    position=CoordinatePoint(track_x, track_y, frame),
                    width=track_w,
                    height=track_h,
                    opacity=0.86,
                )
            )
            content_w = view_w + max_x
            thumb_ratio = max(0.08, min(1.0, view_w / max(content_w, 1e-9)))
            thumb_w = max(12.0, track_w * thumb_ratio)
            span = max(0.0, track_w - thumb_w)
            thumb_x = track_x + span * (scroll_x / max_x)
            thumb_markup = (
                '<svg width="100" height="10" xmlns="http://www.w3.org/2000/svg">'
                f'<rect x="0" y="0" width="100" height="10" rx="4" fill="{thumb_color}"/>'
                "</svg>"
            )
            ctx.mount_component(
                SVGComponent(
                    component_id="__plane_scrollbar_x_thumb",
                    svg_markup=thumb_markup,
                    position=CoordinatePoint(thumb_x, track_y, frame),
                    width=thumb_w,
                    height=track_h,
                    opacity=0.96,
                )
            )

        if max_y > 1e-9:
            track_w = 6.0
            track_x = view_w - track_w - 2.0
            track_y = 72.0
            track_h = max(16.0, view_h - 82.0)
            track_markup = (
                '<svg width="10" height="100" xmlns="http://www.w3.org/2000/svg">'
                f'<rect x="0" y="0" width="10" height="100" rx="4" fill="{track_color}"/>'
                "</svg>"
            )
            ctx.mount_component(
                SVGComponent(
                    component_id="__plane_scrollbar_y_track",
                    svg_markup=track_markup,
                    position=CoordinatePoint(track_x, track_y, frame),
                    width=track_w,
                    height=track_h,
                    opacity=0.86,
                )
            )
            content_h = view_h + max_y
            thumb_ratio = max(0.08, min(1.0, view_h / max(content_h, 1e-9)))
            thumb_h = max(12.0, track_h * thumb_ratio)
            span = max(0.0, track_h - thumb_h)
            thumb_y = track_y + span * (scroll_y / max_y)
            thumb_markup = (
                '<svg width="10" height="100" xmlns="http://www.w3.org/2000/svg">'
                f'<rect x="0" y="0" width="10" height="100" rx="4" fill="{thumb_color}"/>'
                "</svg>"
            )
            ctx.mount_component(
                SVGComponent(
                    component_id="__plane_scrollbar_y_thumb",
                    svg_markup=thumb_markup,
                    position=CoordinatePoint(track_x, thumb_y, frame),
                    width=track_w,
                    height=thumb_h,
                    opacity=0.96,
                )
            )

    def _viewport_content_refs(self) -> set[str]:
        refs: set[str] = set()
        if self._ui_page is None:
            return refs
        for component in self._ui_page.components:
            if component.component_type != "viewport":
                continue
            style = component.style if isinstance(component.style, dict) else {}
            ref = style.get("content_ref")
            if isinstance(ref, str) and ref.strip():
                refs.add(ref)
        return refs

    def _viewport_scroll_position(self, viewport_component) -> tuple[float, float]:
        state = self.state.get("viewport_scroll")
        if isinstance(state, dict):
            entry = state.get(viewport_component.component_id)
            if isinstance(entry, dict):
                try:
                    return (float(entry.get("x", 0.0)), float(entry.get("y", 0.0)))
                except (TypeError, ValueError):
                    pass
        style = viewport_component.style if isinstance(viewport_component.style, dict) else {}
        scroll = style.get("scroll")
        if isinstance(scroll, dict):
            try:
                return (float(scroll.get("x", 0.0)), float(scroll.get("y", 0.0)))
            except (TypeError, ValueError):
                return (0.0, 0.0)
        return (0.0, 0.0)

    def _clamp_viewport_scroll(self, viewport_component, x: float, y: float) -> tuple[float, float]:
        style = viewport_component.style if isinstance(viewport_component.style, dict) else {}
        ref = style.get("content_ref")
        max_x = 0.0
        max_y = 0.0
        if isinstance(ref, str) and ref in self._component_index:
            content = self._component_index[ref]
            max_x = max(0.0, float(content.width) - float(viewport_component.width))
            max_y = max(0.0, float(content.height) - float(viewport_component.height))
        cx = min(max(0.0, float(x)), max_x)
        cy = min(max(0.0, float(y)), max_y)
        return (cx, cy)

    def _apply_viewport_scroll_intent(self, viewport_component, intent: ScrollIntent) -> tuple[float, float]:
        style = viewport_component.style if isinstance(viewport_component.style, dict) else {}
        speed_x = 1.0
        speed_y = 1.0
        scroll_speed = style.get("scroll_speed")
        if isinstance(scroll_speed, dict):
            try:
                speed_x = float(scroll_speed.get("x", 1.0))
                speed_y = float(scroll_speed.get("y", 1.0))
            except (TypeError, ValueError):
                speed_x = 1.0
                speed_y = 1.0
        cur_x, cur_y = self._viewport_scroll_position(viewport_component)
        next_x = cur_x + (intent.delta_x * speed_x)
        next_y = cur_y + (intent.delta_y * speed_y)
        clamped_x, clamped_y = self._clamp_viewport_scroll(viewport_component, next_x, next_y)
        state = self.state.setdefault("viewport_scroll", {})
        if not isinstance(state, dict):
            state = {}
            self.state["viewport_scroll"] = state
        state[viewport_component.component_id] = {"x": clamped_x, "y": clamped_y}
        consumed_x = (clamped_x - cur_x) / speed_x if abs(speed_x) > 1e-12 else 0.0
        consumed_y = (clamped_y - cur_y) / speed_y if abs(speed_y) > 1e-12 else 0.0
        return (consumed_x, consumed_y)

    def _mount_viewport_content(self, ctx, viewport_component, *, x: float, y: float, frame: str) -> None:
        style = viewport_component.style if isinstance(viewport_component.style, dict) else {}
        ref = style.get("content_ref")
        if not isinstance(ref, str) or ref not in self._component_index:
            return
        content = self._component_index[ref]
        scroll_x, scroll_y = self._viewport_scroll_position(viewport_component)
        content_x = x - scroll_x
        content_y = y - scroll_y
        if content.component_type == "svg":
            if content.asset is None:
                return
            svg_path = (self._plane_dir / content.asset.source).resolve()
            svg_markup = self._load_svg_markup(svg_path)
            ctx.mount_component(
                SVGComponent(
                    component_id=f"{viewport_component.component_id}__content",
                    svg_markup=svg_markup,
                    position=CoordinatePoint(content_x, content_y, frame),
                    width=content.width,
                    height=content.height,
                    opacity=float(content.opacity),
                )
            )
            return
        if content.component_type == "viewport":
            self._mount_viewport_content(ctx, content, x=content_x, y=content_y, frame=frame)
            self._mount_viewport_scrollbars(ctx, content, x=content_x, y=content_y, frame=frame)
            return
        if content.component_type == "text":
            props = content.style if isinstance(content.style, dict) else {}
            text = str(props.get("text", content.component_id))
            color_hex = self._resolve_text_color(content.component_id, props)
            font_size_px = float(props.get("font_size_px", 14.0))
            max_width_px = props.get("max_width_px")
            if max_width_px is not None:
                max_width_px = float(max_width_px)
            ctx.mount_component(
                TextComponent(
                    component_id=f"{viewport_component.component_id}__content",
                    text=text,
                    position=CoordinatePoint(content_x, content_y, frame),
                    size=TextSizeSpec(unit="px", value=font_size_px),
                    appearance=TextAppearance(color_hex=color_hex, opacity=float(content.opacity)),
                    max_width_px=max_width_px,
                )
            )

    def _mount_viewport_scrollbars(self, ctx, viewport_component, *, x: float, y: float, frame: str) -> None:
        style = viewport_component.style if isinstance(viewport_component.style, dict) else {}
        ref = style.get("content_ref")
        if not isinstance(ref, str) or ref not in self._component_index:
            return
        content = self._component_index[ref]
        view_w = float(viewport_component.width)
        view_h = float(viewport_component.height)
        content_w = float(content.width)
        content_h = float(content.height)
        if view_w <= 0 or view_h <= 0:
            return
        scroll_x, scroll_y = self._viewport_scroll_position(viewport_component)
        track_color = "#1f344d"
        thumb_color = "#89b7e6"

        if content_w > view_w + 1e-9:
            track_h = 5.0
            track_y = y + view_h - track_h - 2.0
            track_markup = (
                '<svg width="100" height="10" xmlns="http://www.w3.org/2000/svg">'
                f'<rect x="0" y="0" width="100" height="10" rx="4" fill="{track_color}"/>'
                "</svg>"
            )
            ctx.mount_component(
                SVGComponent(
                    component_id=f"{viewport_component.component_id}__scrollbar_x_track",
                    svg_markup=track_markup,
                    position=CoordinatePoint(x + 2.0, track_y, frame),
                    width=max(8.0, view_w - 4.0),
                    height=track_h,
                    opacity=0.82,
                )
            )
            thumb_ratio = max(0.08, min(1.0, view_w / content_w))
            thumb_w = max(10.0, (view_w - 4.0) * thumb_ratio)
            max_scroll_x = max(1e-9, content_w - view_w)
            span = max(0.0, (view_w - 4.0) - thumb_w)
            thumb_x = x + 2.0 + span * (scroll_x / max_scroll_x)
            thumb_markup = (
                '<svg width="100" height="10" xmlns="http://www.w3.org/2000/svg">'
                f'<rect x="0" y="0" width="100" height="10" rx="4" fill="{thumb_color}"/>'
                "</svg>"
            )
            ctx.mount_component(
                SVGComponent(
                    component_id=f"{viewport_component.component_id}__scrollbar_x_thumb",
                    svg_markup=thumb_markup,
                    position=CoordinatePoint(thumb_x, track_y, frame),
                    width=thumb_w,
                    height=track_h,
                    opacity=0.95,
                )
            )

        if content_h > view_h + 1e-9:
            track_w = 5.0
            track_x = x + view_w - track_w - 2.0
            track_markup = (
                '<svg width="10" height="100" xmlns="http://www.w3.org/2000/svg">'
                f'<rect x="0" y="0" width="10" height="100" rx="4" fill="{track_color}"/>'
                "</svg>"
            )
            ctx.mount_component(
                SVGComponent(
                    component_id=f"{viewport_component.component_id}__scrollbar_y_track",
                    svg_markup=track_markup,
                    position=CoordinatePoint(track_x, y + 2.0, frame),
                    width=track_w,
                    height=max(8.0, view_h - 4.0),
                    opacity=0.82,
                )
            )
            thumb_ratio = max(0.08, min(1.0, view_h / content_h))
            thumb_h = max(10.0, (view_h - 4.0) * thumb_ratio)
            max_scroll_y = max(1e-9, content_h - view_h)
            span = max(0.0, (view_h - 4.0) - thumb_h)
            thumb_y = y + 2.0 + span * (scroll_y / max_scroll_y)
            thumb_markup = (
                '<svg width="10" height="100" xmlns="http://www.w3.org/2000/svg">'
                f'<rect x="0" y="0" width="10" height="100" rx="4" fill="{thumb_color}"/>'
                "</svg>"
            )
            ctx.mount_component(
                SVGComponent(
                    component_id=f"{viewport_component.component_id}__scrollbar_y_thumb",
                    svg_markup=thumb_markup,
                    position=CoordinatePoint(track_x, thumb_y, frame),
                    width=track_w,
                    height=thumb_h,
                    opacity=0.95,
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


def _scroll_intent_from_event(event_type: str, payload: dict[str, Any]) -> ScrollIntent | None:
    if event_type == "scroll":
        try:
            dx = float(payload.get("delta_x", 0.0))
            dy = float(payload.get("delta_y", 0.0))
        except (TypeError, ValueError):
            return None
        # Match system-native scroll direction expectations by treating positive
        # wheel deltas as moving the viewport camera in the opposite direction.
        return ScrollIntent(delta_x=-dx, delta_y=-dy, source="wheel", phase="update")
    if event_type in {"pan", "swipe"}:
        try:
            dx = float(payload.get("delta_x", 0.0))
            dy = float(payload.get("delta_y", 0.0))
        except (TypeError, ValueError):
            return None
        return ScrollIntent(delta_x=-dx, delta_y=-dy, source="touch_drag", phase="update")
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
