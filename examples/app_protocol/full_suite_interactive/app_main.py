from __future__ import annotations

from dataclasses import dataclass
import html
import os
import time

from luvatrix_core.core.ui_frame_renderer import MatrixUIFrameRenderer
from luvatrix_ui.component_schema import CoordinatePoint
from luvatrix_ui.controls.svg_component import SVGComponent
from luvatrix_ui.text.component import TextComponent
from luvatrix_ui.text.renderer import FontSpec, TextAppearance, TextSizeSpec

@dataclass
class InteractionState:
    mouse_x: float = 0.0
    mouse_y: float = 0.0
    mouse_in_window: bool = False
    mouse_error: str | None = "window not active / pointer out of bounds"
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
    active_coord_frame: str = "screen_tl"


def select_sensors(requested: list[str], available_sensors: list[str]) -> list[str]:
    if not requested:
        return list(available_sensors)
    selected = []
    for sensor in requested:
        if sensor not in available_sensors:
            raise ValueError(
                f"unsupported sensor `{sensor}` on this runtime; choose from: {', '.join(available_sensors)}"
            )
        if sensor not in selected:
            selected.append(sensor)
    return selected


def _sensor_text(sample) -> str:
    if sample.status != "OK":
        return f"{sample.status}"
    return f"{sample.value}"


def _truncate(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    if max_len <= 3:
        return value[:max_len]
    return value[: max_len - 3] + "..."


def _sensor_ascii_table(samples: dict[str, object], selected_sensors: list[str]) -> str:
    headers = ("sensor", "status", "value", "unit")
    rows: list[tuple[str, str, str, str]] = []
    for sensor in selected_sensors:
        sample = samples[sensor]
        rows.append(
            (
                sensor,
                sample.status,
                _truncate(_sensor_text(sample), 56),
                "" if sample.unit is None else str(sample.unit),
            )
        )
    col_widths = [
        max(len(headers[0]), *(len(r[0]) for r in rows)) if rows else len(headers[0]),
        max(len(headers[1]), *(len(r[1]) for r in rows)) if rows else len(headers[1]),
        max(len(headers[2]), *(len(r[2]) for r in rows)) if rows else len(headers[2]),
        max(len(headers[3]), *(len(r[3]) for r in rows)) if rows else len(headers[3]),
    ]
    rule = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    out = [
        rule,
        "| " + " | ".join(headers[i].ljust(col_widths[i]) for i in range(4)) + " |",
        rule,
    ]
    for row in rows:
        out.append("| " + " | ".join(row[i].ljust(col_widths[i]) for i in range(4)) + " |")
    out.append(rule)
    return "\n".join(out)


def _hdi_ascii_table(state: InteractionState) -> str:
    headers = ("signal", "value", "status")
    mouse_status = "OK" if state.mouse_in_window else f"OUT ({state.mouse_error})"
    rows = [
        ("mouse_xy", f"{state.mouse_x:.1f}, {state.mouse_y:.1f}", mouse_status),
        ("click_left", str(state.left_down), "OK"),
        ("click_right", str(state.right_down), "OK"),
        ("pressure", f"{state.pressure:.3f}", "OK"),
        ("pinch", f"{state.pinch:.3f}", "OK"),
        ("rotation", f"{state.rotation:.3f}", "OK"),
        ("scroll_xy", f"{state.scroll_x:.3f}, {state.scroll_y:.3f}", "OK"),
        ("key_last", state.key_last or "-", state.key_state or "NO_EVENT"),
        ("keys_down", ",".join(state.keys_down or []), "OK"),
    ]
    col_widths = [
        max(len(headers[0]), *(len(r[0]) for r in rows)),
        max(len(headers[1]), *(len(r[1]) for r in rows)),
        max(len(headers[2]), *(len(r[2]) for r in rows)),
    ]
    rule = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    out = [
        rule,
        "| " + " | ".join(headers[i].ljust(col_widths[i]) for i in range(3)) + " |",
        rule,
    ]
    for row in rows:
        out.append("| " + " | ".join(row[i].ljust(col_widths[i]) for i in range(3)) + " |")
    out.append(rule)
    return "\n".join(out)


def format_dashboard(
    state: InteractionState,
    samples: dict[str, object],
    selected_sensors: list[str],
    aspect_mode: str,
    fps_estimate: float,
) -> str:
    mouse_line = f"mouse x | mouse y: {state.mouse_x:.1f}, {state.mouse_y:.1f}"
    if not state.mouse_in_window:
        mouse_line += f" [out-of-bounds: {state.mouse_error}]"
    return "\n".join(
        [
            "Luvatrix Full Suite Interactive Example (App Protocol)",
            f"aspect mode: {aspect_mode}",
            f"fps(est): {fps_estimate:5.1f}",
            "",
            mouse_line,
            "",
            "hdi telemetry:",
            _hdi_ascii_table(state),
            "microphone level: N/A (metadata only)",
            "speaker level: N/A (metadata only)",
            "",
            "sensor telemetry:",
            _sensor_ascii_table(samples, selected_sensors),
            "",
            "close window to exit",
        ]
    )


def _apply_hdi_events(state: InteractionState, events: list[object], surface_height: int) -> None:
    _ = surface_height
    for event in events:
        if event.device == "keyboard":
            if event.status == "OK" and isinstance(event.payload, dict):
                key = str(event.payload.get("key", "")).strip()
                phase = str(event.payload.get("phase", ""))
                if key:
                    state.key_last = key
                if phase:
                    state.key_state = phase
                active_keys = event.payload.get("active_keys")
                if isinstance(active_keys, list):
                    state.keys_down = [str(k) for k in active_keys]
            else:
                state.key_state = event.status
        if event.device == "mouse" and event.event_type == "pointer_move":
            if event.status == "OK" and isinstance(event.payload, dict):
                state.mouse_x = float(event.payload.get("x", state.mouse_x))
                state.mouse_y = float(event.payload.get("y", state.mouse_y))
                state.mouse_in_window = True
                state.mouse_error = None
            else:
                state.mouse_in_window = False
                state.mouse_error = "window not active / pointer out of bounds"
        if event.device != "trackpad" or not isinstance(event.payload, dict):
            continue
        if event.event_type == "click":
            button = int(event.payload.get("button", -1))
            phase = str(event.payload.get("phase", ""))
            is_down = phase == "down"
            if button == 0:
                state.left_down = is_down
            elif button == 1:
                state.right_down = is_down
        elif event.event_type == "pressure":
            state.pressure = float(event.payload.get("pressure", state.pressure))
        elif event.event_type == "pinch":
            state.pinch = float(event.payload.get("magnification", state.pinch))
        elif event.event_type == "rotate":
            state.rotation = float(event.payload.get("rotation", state.rotation))
        elif event.event_type == "scroll":
            state.scroll_x = float(event.payload.get("delta_x", state.scroll_x))
            state.scroll_y = float(event.payload.get("delta_y", state.scroll_y))


_COORD_FRAME_ORDER = ("screen_tl", "cartesian_bl", "cartesian_center")


def _next_coord_frame(current: str, key: str) -> str | None:
    k = key.strip().lower()
    if k == "1":
        return "screen_tl"
    if k == "2":
        return "cartesian_bl"
    if k == "3":
        return "cartesian_center"
    if k in ("c", "f"):
        if current not in _COORD_FRAME_ORDER:
            return _COORD_FRAME_ORDER[0]
        idx = _COORD_FRAME_ORDER.index(current)
        return _COORD_FRAME_ORDER[(idx + 1) % len(_COORD_FRAME_ORDER)]
    return None


def _detect_frame_switch(events: list[object], current_frame: str) -> str | None:
    for event in events:
        if event.device != "keyboard" or event.status != "OK" or not isinstance(event.payload, dict):
            continue
        phase = str(event.payload.get("phase", ""))
        if phase not in ("down", "single"):
            continue
        key = str(event.payload.get("key", ""))
        next_frame = _next_coord_frame(current_frame, key)
        if next_frame is not None:
            return next_frame
    return None


def _mouse_label_text(display_frame: str, display_x: float, display_y: float) -> str:
    return f"{display_frame} x={display_x:.1f}, y={display_y:.1f}"


def _frame_clear_color(state: InteractionState, t: int) -> tuple[int, int, int, int]:
    base_r = int((t * 3 + 35) % 255)
    base_g = int((t * 2 + 70) % 255)
    base_b = int((t * 4 + 20) % 255)
    rotate_boost = int(max(-30.0, min(30.0, state.rotation * 2.0)))
    scroll_boost = int(max(-40.0, min(40.0, state.scroll_y * 0.5)))
    r = max(0, min(255, base_r + rotate_boost))
    g = max(0, min(255, base_g + scroll_boost))
    b = max(0, min(255, base_b))
    return (r, g, b, 255)


def _build_scene_svg(width: int, height: int, state: InteractionState) -> str:
    if not state.mouse_in_window:
        return (
            f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            f'<rect x="0" y="0" width="{width}" height="{height}" fill="none" stroke="#ffffff22" stroke-width="1"/>'
            "</svg>"
        )
    radius = 24.0 + min(50.0, 90.0 * state.pressure + 35.0 * abs(state.pinch))
    cx = max(0.0, min(float(width), state.mouse_x))
    cy = max(0.0, min(float(height), state.mouse_y))
    circle_fill = "#ff66aa66" if state.left_down else "#66ddff66"
    circle_stroke = "#ff88cc" if state.right_down else "#e8f7ff"
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{radius:.2f}" fill="{circle_fill}" stroke="{circle_stroke}" stroke-width="2"/>'
        "</svg>"
    )


class FullSuiteInteractiveApp:
    def __init__(self) -> None:
        self._sensors: list[str] = []
        self._aspect = os.getenv("LUVATRIX_FSI_ASPECT", "stretch")
        self._coord_frame = os.getenv("LUVATRIX_FSI_COORD_FRAME", "screen_tl")
        self._dashboard_interval = float(os.getenv("LUVATRIX_FSI_DASHBOARD_INTERVAL", "0.35"))
        self._rewrite_delay = float(os.getenv("LUVATRIX_FSI_REWRITE_DELAY", "0.0"))
        self._state = InteractionState()
        self._width = 0
        self._height = 0
        self._frame_count = 0
        self._started = 0.0
        self._last_print = 0.0
        self._ui_renderer = MatrixUIFrameRenderer()

    def init(self, ctx) -> None:
        raw_available = os.getenv("LUVATRIX_FSI_AVAILABLE_SENSORS", "")
        available = [x.strip() for x in raw_available.split(",") if x.strip()]
        raw_sensors = os.getenv("LUVATRIX_FSI_SENSORS", "")
        requested = [x.strip() for x in raw_sensors.split(",") if x.strip()]
        self._sensors = select_sensors(requested, available)
        if self._coord_frame not in _COORD_FRAME_ORDER:
            self._coord_frame = "screen_tl"
        self._state.active_coord_frame = self._coord_frame
        ctx.set_default_coordinate_frame(self._coord_frame)

        snap = ctx.read_matrix_snapshot()
        self._height, self._width, _ = snap.shape
        self._started = time.perf_counter()
        self._last_print = 0.0
        self._ui_renderer.prepare_font(
            FontSpec(family="Comic Mono"),
            size_px=12.0,
            charset="abcdefghijklmnopqrstuvwxyz0123456789:.,_-|= ",
        )
        self._ui_renderer.prepare_font(
            FontSpec(family="Comic Mono"),
            size_px=14.0,
            charset="abcdefghijklmnopqrstuvwxyz0123456789:.,_-|= ",
        )

        print("available functional sensors:")
        for sensor in self._sensors:
            sample = ctx.read_sensor(sensor)
            is_functional = sample.status == "OK"
            print(f"  - {sensor}: {'available' if is_functional else sample.status}")

    def loop(self, ctx, dt: float) -> None:
        _ = dt
        events = ctx.poll_hdi_events(max_events=256, frame="screen_tl")
        _apply_hdi_events(self._state, events, self._height)
        next_frame = _detect_frame_switch(events, self._coord_frame)
        if next_frame is not None and next_frame != self._coord_frame:
            self._coord_frame = next_frame
            self._state.active_coord_frame = next_frame
            ctx.set_default_coordinate_frame(next_frame)

        clear_color = _frame_clear_color(self._state, self._frame_count)
        ctx.begin_ui_frame(
            self._ui_renderer,
            content_width_px=float(self._width),
            content_height_px=float(self._height),
            clear_color=clear_color,
        )
        ctx.mount_component(
            SVGComponent(
                component_id="mouse_orb",
                svg_markup=_build_scene_svg(self._width, self._height, self._state),
                position=CoordinatePoint(0.0, 0.0, "screen_tl"),
                width=float(self._width),
                height=float(self._height),
            )
        )
        if self._state.mouse_in_window:
            dx, dy = ctx.from_render_coords(self._state.mouse_x, self._state.mouse_y, frame=self._coord_frame)
            label = _mouse_label_text(self._coord_frame, dx, dy)
            text_x = max(0.0, min(float(self._width - 180), self._state.mouse_x + 12.0))
            text_y = max(0.0, min(float(self._height - 24), self._state.mouse_y - 22.0))
            ctx.mount_component(
                TextComponent(
                    component_id="mouse_label",
                    text=label,
                    position=CoordinatePoint(text_x, text_y, "screen_tl"),
                    appearance=TextAppearance(color_hex="#f8fafc"),
                    size=TextSizeSpec(unit="px", value=14.0),
                )
            )
        ctx.mount_component(
            TextComponent(
                component_id="frame_hint",
                text="keys: 1 screen_tl | 2 cartesian_bl | 3 cartesian_center | c cycle",
                position=CoordinatePoint(8.0, 8.0, "screen_tl"),
                appearance=TextAppearance(color_hex="#e2e8f0"),
                size=TextSizeSpec(unit="px", value=12.0),
            )
        )
        ctx.mount_component(
            TextComponent(
                component_id="active_frame",
                text=f"active frame: {html.escape(self._coord_frame)}",
                position=CoordinatePoint(8.0, 24.0, "screen_tl"),
                appearance=TextAppearance(color_hex="#fef08a"),
                size=TextSizeSpec(unit="px", value=12.0),
            )
        )
        self._frame_count += 1
        ctx.finalize_ui_frame()

        now = time.perf_counter()
        if now - self._last_print >= self._dashboard_interval:
            fps = self._frame_count / max(1e-6, now - self._started)
            samples = {sensor: ctx.read_sensor(sensor) for sensor in self._sensors}
            dashboard = format_dashboard(
                state=self._state,
                samples=samples,
                selected_sensors=self._sensors,
                aspect_mode=self._aspect,
                fps_estimate=fps,
            )
            print("\x1b[2J\x1b[H" + dashboard, end="", flush=True)
            self._last_print = now
            if self._rewrite_delay > 0:
                time.sleep(self._rewrite_delay)

    def stop(self, ctx) -> None:
        print("\nshutting down...")


def create():
    return FullSuiteInteractiveApp()
