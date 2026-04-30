from __future__ import annotations

from dataclasses import dataclass, field
import html
import json
import os
import sys
import time

_UI_IMPORT_ERROR: ImportError | None = None

try:
    from luvatrix_core.core.ui_frame_renderer import MatrixUIFrameRenderer
    from luvatrix_ui.component_schema import CoordinatePoint
    from luvatrix_ui.controls.svg_component import SVGComponent
    from luvatrix_ui.text.component import TextComponent
    from luvatrix_ui.text.renderer import FontSpec, TextAppearance, TextSizeSpec
    _HAS_UI = True
except ImportError as exc:
    _UI_IMPORT_ERROR = exc
    _HAS_UI = False

@dataclass
class InteractionState:
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
        ("touches", str(state.touch_count), "OK"),
        ("gesture", f"{state.gesture_scale:.3f}, {state.gesture_rotation:.3f}", "OK"),
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
        if event.device == "touch" and isinstance(event.payload, dict):
            if event.event_type == "touch" and event.status == "OK":
                touch_id = int(event.payload.get("touch_id", 0))
                phase = str(event.payload.get("phase", ""))
                x = float(event.payload.get("x", state.mouse_x))
                y = float(event.payload.get("y", state.mouse_y))
                if phase in ("down", "move"):
                    state.active_touches[touch_id] = (x, y)
                    state.mouse_x = x
                    state.mouse_y = y
                    state.mouse_in_window = True
                    state.mouse_error = None
                    state.pressure = float(event.payload.get("force", state.pressure))
                elif phase in ("up", "cancel"):
                    state.active_touches.pop(touch_id, None)
                state.touch_count = len(state.active_touches)
            elif event.event_type == "gesture" and event.status == "OK":
                kind = str(event.payload.get("kind", ""))
                if kind == "pan":
                    state.gesture_pan_x = float(event.payload.get("translation_x", state.gesture_pan_x))
                    state.gesture_pan_y = float(event.payload.get("translation_y", state.gesture_pan_y))
                elif kind == "pinch":
                    state.gesture_scale = float(event.payload.get("scale", state.gesture_scale))
                    state.pinch = state.gesture_scale - 1.0
                elif kind == "rotate":
                    state.gesture_rotation = float(event.payload.get("rotation", state.gesture_rotation))
                    state.rotation = state.gesture_rotation
        if event.device not in ("mouse", "trackpad") or not isinstance(event.payload, dict):
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


def _ios_display_link_telemetry() -> dict[str, object]:
    path = os.getenv("LUVATRIX_IOS_DISPLAY_LINK_TELEMETRY_PATH", "")
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


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


_DEBUG_GLYPHS: dict[str, tuple[str, ...]] = {
    " ": ("000", "000", "000", "000", "000"),
    "-": ("000", "000", "111", "000", "000"),
    ".": ("000", "000", "000", "000", "010"),
    ":": ("000", "010", "000", "010", "000"),
    "_": ("000", "000", "000", "000", "111"),
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "A": ("010", "101", "111", "101", "101"),
    "B": ("110", "101", "110", "101", "110"),
    "C": ("111", "100", "100", "100", "111"),
    "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"),
    "F": ("111", "100", "110", "100", "100"),
    "G": ("111", "100", "101", "101", "111"),
    "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"),
    "J": ("001", "001", "001", "101", "111"),
    "K": ("101", "101", "110", "101", "101"),
    "L": ("100", "100", "100", "100", "111"),
    "M": ("101", "111", "111", "101", "101"),
    "N": ("101", "111", "111", "111", "101"),
    "O": ("111", "101", "101", "101", "111"),
    "P": ("111", "101", "111", "100", "100"),
    "Q": ("111", "101", "101", "111", "001"),
    "R": ("111", "101", "111", "110", "101"),
    "S": ("111", "100", "111", "001", "111"),
    "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "111"),
    "V": ("101", "101", "101", "101", "010"),
    "W": ("101", "101", "111", "111", "101"),
    "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "010", "010", "010"),
    "Z": ("111", "001", "010", "100", "111"),
}


def _draw_debug_text(frame, text: str, *, x: int, y: int, scale: int, color: tuple[int, int, int, int]) -> None:
    h, w, _ = frame.shape
    cursor = int(x)
    for raw_ch in text.upper():
        glyph = _DEBUG_GLYPHS.get(raw_ch, _DEBUG_GLYPHS[" "])
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit != "1":
                    continue
                x0 = cursor + gx * scale
                y0 = int(y) + gy * scale
                x1 = min(w, x0 + scale)
                y1 = min(h, y0 + scale)
                if x0 < w and y0 < h and x1 > 0 and y1 > 0:
                    frame[max(0, y0):y1, max(0, x0):x1, :] = color
        cursor += 4 * scale


def _debug_text_safe(value: str, max_len: int) -> str:
    safe = []
    for ch in value.upper():
        safe.append(ch if ch in _DEBUG_GLYPHS else " ")
    return "".join(safe).strip()[:max_len]


def _debug_text_chunks(value: str, width: int, max_lines: int) -> list[str]:
    safe = []
    for ch in value.upper():
        safe.append(ch if ch in _DEBUG_GLYPHS else " ")
    compact = " ".join("".join(safe).split())
    chunks: list[str] = []
    for line_idx in range(max_lines):
        start = line_idx * width
        if start >= len(compact):
            break
        chunk = compact[start : start + width]
        if line_idx == max_lines - 1 and start + width < len(compact) and width > 3:
            chunk = chunk[: width - 3] + "..."
        chunks.append(chunk)
    return chunks


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
        self._win_count = 0
        self._win_start = 0.0
        self._last_fps: float = 0.0
        self._ui_renderer = MatrixUIFrameRenderer() if _HAS_UI else None
        self._debug = os.getenv("LUVATRIX_FSI_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")
        self._last_debug_text_ts: float = 0.0
        self._debug_lines: tuple[str, str, str] = ("", "", "")
        self._debug_err_chunks: list[str] = []

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
        self._backing_height, self._backing_width, _ = snap.shape
        self._width = int(round(float(getattr(ctx, "display_width_px", self._backing_width))))
        self._height = int(round(float(getattr(ctx, "display_height_px", self._backing_height))))
        self._started = time.perf_counter()
        self._win_start = self._started
        self._win_count = 0
        self._last_fps = 0.0
        self._last_print = 0.0
        if _HAS_UI:
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
            print("[full_suite] ui renderer enabled", file=sys.stderr, flush=True)
        else:
            print(
                f"[full_suite] ui renderer disabled; using color-only fallback: {_UI_IMPORT_ERROR}",
                file=sys.stderr,
                flush=True,
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

        if getattr(ctx, "supports_scene_graph", False):
            self._loop_scene(ctx)
        elif _HAS_UI:
            try:
                self._loop_ui(ctx)
            except Exception as _ui_err:
                print(f"[full_suite] _loop_ui failed, falling back: {_ui_err}", file=sys.stderr, flush=True)
                self._loop_fallback(ctx)
        else:
            self._loop_fallback(ctx)
        self._frame_count += 1

        now = time.perf_counter()
        if now - self._last_print >= self._dashboard_interval:
            fps = self._last_fps or (self._frame_count / max(1e-6, now - self._started))
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

    def _loop_scene(self, ctx) -> None:
        ctx.begin_scene_frame()
        ctx.clear_scene((0, 0, 0, 255))
        ctx.draw_shader_rect(
            x=0.0,
            y=0.0,
            width=float(self._width),
            height=float(self._height),
            shader="full_suite_background",
            uniforms=(float(time.perf_counter() - self._started) * 120.0, float(self._state.rotation), float(self._state.scroll_y)),
            z_index=0,
        )
        if self._state.active_touches:
            for idx, (touch_id, (touch_x, touch_y)) in enumerate(sorted(self._state.active_touches.items())):
                radius = 18.0 + min(50.0, 70.0 * max(0.0, self._state.pressure))
                ctx.draw_circle(
                    cx=max(0.0, min(float(self._width), touch_x)),
                    cy=max(0.0, min(float(self._height), touch_y)),
                    radius=radius,
                    fill_rgba=(102, 221, 255, 96),
                    stroke_rgba=(248, 250, 252, 255),
                    stroke_width=2.0,
                    z_index=10 + idx,
                )
        elif self._state.mouse_in_window:
            radius = 24.0 + min(50.0, 90.0 * self._state.pressure + 35.0 * abs(self._state.pinch))
            ctx.draw_circle(
                cx=max(0.0, min(float(self._width), self._state.mouse_x)),
                cy=max(0.0, min(float(self._height), self._state.mouse_y)),
                radius=radius,
                fill_rgba=(255, 102, 170, 96) if self._state.left_down else (102, 221, 255, 96),
                stroke_rgba=(255, 136, 204, 255) if self._state.right_down else (232, 247, 255, 255),
                stroke_width=2.0,
                z_index=10,
            )
            dx, dy = ctx.from_render_coords(self._state.mouse_x, self._state.mouse_y, frame=self._coord_frame)
            text_x = max(0.0, min(float(self._width - 180), self._state.mouse_x + 12.0))
            text_y = max(0.0, min(float(self._height - 24), self._state.mouse_y - 22.0))
            ctx.draw_text(
                _mouse_label_text(self._coord_frame, dx, dy),
                x=text_x,
                y=text_y,
                font_family="Comic Mono",
                font_size_px=14.0,
                color_rgba=(248, 250, 252, 255),
                z_index=20,
                cache_key="mouse_label",
            )

        bottom = float(self._height)
        scene_lines = [
            ("1 screen_tl | 2 cart_bl", 84.0, 12.0, (226, 232, 240, 255), "frame_hint"),
            ("3 cart_ctr | c cycle", 66.0, 12.0, (226, 232, 240, 255), "frame_hint_more"),
            (f"active frame: {self._coord_frame}", 46.0, 12.0, (254, 240, 138, 255), "active_frame"),
            (
                f"touches:{self._state.touch_count} scale:{self._state.gesture_scale:.2f} rot:{self._state.gesture_rotation:.2f}",
                28.0,
                10.0,
                (186, 230, 253, 255),
                "touch_status",
            ),
        ]
        for text, offset, size, color, key in scene_lines:
            ctx.draw_text(
                text,
                x=8.0,
                y=max(0.0, bottom - offset),
                font_family="Comic Mono",
                font_size_px=size,
                color_rgba=color,
                z_index=30,
                cache_key=key,
            )

        accel_name = os.getenv("LUVATRIX_IOS_ACCEL_IMPORT_ERROR", "")
        if _HAS_UI and self._ui_renderer is not None and hasattr(self._ui_renderer, "diagnostics"):
            diag = self._ui_renderer.diagnostics()
            font_source = str(diag.get("font_source", "?"))
            if len(font_source) > 18:
                font_source = font_source[:18]
            status = (
                f"accel:{diag.get('accel', '?')} "
                f"pil:{int(bool(diag.get('pil')))} "
                f"np:{int(bool(diag.get('numpy')))} "
                f"font:{font_source}"
            )
        elif accel_name:
            status = "accel:import-error scene"
        else:
            status = "scene:retained"
        if self._debug:
            display_link = _ios_display_link_telemetry()
            runtime = ctx.runtime_telemetry()
            now_t = time.perf_counter()
            win_elapsed = now_t - self._win_start
            if win_elapsed >= 2.0:
                self._last_fps = (self._frame_count - self._win_count) / max(1e-6, win_elapsed)
                self._win_count = self._frame_count
                self._win_start = now_t
            if now_t - self._last_debug_text_ts >= 0.25:
                fallback_app_fps = self._last_fps or (self._frame_count / max(1e-6, now_t - self._started))
                app_fps = float(runtime.get("app_loop_fps", 0.0) or fallback_app_fps)
                present_fps = float(runtime.get("present_success_fps", 0.0) or 0.0)
                dl_fps = float(display_link.get("measured_fps", 0.0) or 0.0)
                self._debug_lines = (
                    f"a:{app_fps:.0f} p:{present_fps:.0f} dl:{dl_fps:.0f} mx:{int(display_link.get('screen_max_fps', 0) or 0)}",
                    (
                        f"act:{int(bool(runtime.get('app_active', 1)))} "
                        f"nil:{int(runtime.get('next_drawable_nil', 0) or 0)} "
                        f"slow:{int(runtime.get('next_drawable_slow', 0) or 0)} "
                        f"ms:{float(runtime.get('last_present_ms', 0.0) or 0.0):.1f}"
                    ),
                    (
                        f"nd:{int(runtime.get('last_nd_ms_x10', 0) or 0) / 10:.1f} "
                        f"enc:{int(runtime.get('last_enc_ms_x10', 0) or 0) / 10:.1f} "
                        f"txt:{int(runtime.get('last_txt_ms_x10', 0) or 0) / 10:.1f} "
                        f"ovl:{int(runtime.get('last_ovl_ms_x10', 0) or 0) / 10:.1f} "
                        f"cmt:{int(runtime.get('last_cmt_ms_x10', 0) or 0) / 10:.1f}"
                    ),
                )
                err = accel_name.replace("\n", " ")
                self._debug_err_chunks = _debug_text_chunks(err, 38, 4) if err else []
                self._last_debug_text_ts = now_t
            for idx, line in enumerate(self._debug_lines):
                ctx.draw_text(
                    line,
                    x=8.0,
                    y=max(0.0, bottom - (12.0 + idx * 11.0)),
                    font_family="Comic Mono",
                    font_size_px=8.0,
                    color_rgba=(186, 230, 253, 255),
                    z_index=30,
                    cache_key=f"runtime_status_{idx}",
                )
            for idx, chunk in enumerate(self._debug_err_chunks):
                ctx.draw_text(
                    chunk,
                    x=8.0,
                    y=max(0.0, bottom - (106.0 + idx * 14.0)),
                    font_family="Comic Mono",
                    font_size_px=9.0,
                    color_rgba=(254, 202, 202, 255),
                    z_index=30,
                    cache_key=f"runtime_error_{idx}",
                )
        ctx.finalize_scene_frame()

    def _loop_ui(self, ctx) -> None:
        from luvatrix_core import accel
        clear_color = _frame_clear_color(self._state, self._frame_count)
        ctx.begin_ui_frame(
            self._ui_renderer,
            content_width_px=float(self._width),
            content_height_px=float(self._height),
            clear_color=clear_color,
        )
        if self._state.mouse_in_window or accel.BACKEND == "torch":
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
                text="1 screen_tl | 2 cart_bl",
                position=CoordinatePoint(8.0, max(0.0, float(self._height) - 84.0), "screen_tl"),
                appearance=TextAppearance(color_hex="#e2e8f0"),
                size=TextSizeSpec(unit="px", value=12.0),
            )
        )
        ctx.mount_component(
            TextComponent(
                component_id="frame_hint_more",
                text="3 cart_ctr | c cycle",
                position=CoordinatePoint(8.0, max(0.0, float(self._height) - 66.0), "screen_tl"),
                appearance=TextAppearance(color_hex="#e2e8f0"),
                size=TextSizeSpec(unit="px", value=12.0),
            )
        )
        ctx.mount_component(
            TextComponent(
                component_id="active_frame",
                text=f"active frame: {html.escape(self._coord_frame)}",
                position=CoordinatePoint(8.0, max(0.0, float(self._height) - 46.0), "screen_tl"),
                appearance=TextAppearance(color_hex="#fef08a"),
                size=TextSizeSpec(unit="px", value=12.0),
            )
        )
        diag = self._ui_renderer.diagnostics() if hasattr(self._ui_renderer, "diagnostics") else {}
        if diag:
            import os as _os
            font_source = str(diag.get("font_source", "?"))
            if len(font_source) > 18:
                font_source = font_source[:18]
            ctx.mount_component(
                TextComponent(
                    component_id="runtime_status",
                    text=(
                        f"accel:{diag.get('accel', '?')} "
                        f"pil:{int(bool(diag.get('pil')))} "
                        f"np:{int(bool(diag.get('numpy')))} "
                        f"font:{font_source}"
                    ),
                    position=CoordinatePoint(8.0, max(0.0, float(self._height) - 24.0), "screen_tl"),
                    appearance=TextAppearance(color_hex="#bae6fd"),
                    size=TextSizeSpec(unit="px", value=10.0),
                )
            )
            err = str(_os.getenv("LUVATRIX_IOS_ACCEL_IMPORT_ERROR", "")).replace("\n", " ")
            if err:
                for idx, chunk in enumerate(_debug_text_chunks(err, 38, 6)):
                    ctx.mount_component(
                        TextComponent(
                            component_id=f"runtime_error_{idx}",
                            text=chunk,
                            position=CoordinatePoint(
                                8.0,
                                max(0.0, float(self._height) - (106.0 + idx * 14.0)),
                                "screen_tl",
                            ),
                            appearance=TextAppearance(color_hex="#fecaca"),
                            size=TextSizeSpec(unit="px", value=9.0),
                        )
                    )
            platform_info = _debug_text_safe(
                f"{_os.getenv('LUVATRIX_IOS_SYS_PLATFORM', '')} {_os.getenv('LUVATRIX_IOS_SYS_EXECUTABLE', '')}",
                38,
            )
            if platform_info:
                ctx.mount_component(
                    TextComponent(
                        component_id="runtime_platform",
                        text=platform_info,
                        position=CoordinatePoint(8.0, max(0.0, float(self._height) - 124.0), "screen_tl"),
                        appearance=TextAppearance(color_hex="#fed7aa"),
                        size=TextSizeSpec(unit="px", value=10.0),
                    )
                )
            native_diag = str(_os.getenv("LUVATRIX_IOS_NATIVE_DIAG", ""))
            if native_diag:
                ctx.mount_component(
                    TextComponent(
                        component_id="runtime_native_diag",
                        text=_debug_text_safe(native_diag, 38),
                        position=CoordinatePoint(8.0, max(0.0, float(self._height) - 142.0), "screen_tl"),
                        appearance=TextAppearance(color_hex="#bbf7d0"),
                        size=TextSizeSpec(unit="px", value=10.0),
                    )
                )
        ctx.finalize_ui_frame()

    def _loop_fallback(self, ctx) -> None:
        from luvatrix_core import accel
        from luvatrix_core.core.window_matrix import FullRewrite, WriteBatch
        h, w = self._height, self._width
        if hasattr(self, "_backing_height") and hasattr(self, "_backing_width"):
            h, w = self._backing_height, self._backing_width
        r, g, b, _ = _frame_clear_color(self._state, self._frame_count)
        frame = accel.zeros((h, w, 4))
        frame[:, :, 0] = r
        frame[:, :, 1] = g
        frame[:, :, 2] = b
        frame[:, :, 3] = 255
        reason = "UI OFF"
        detail = ""
        if _UI_IMPORT_ERROR is not None:
            reason = f"UI OFF {type(_UI_IMPORT_ERROR).__name__}"
            detail = _debug_text_safe(str(_UI_IMPORT_ERROR), 30)
        scale = max(2, min(6, w // 120))
        base_y = max(0, h - (30 * scale if detail else 18 * scale))
        _draw_debug_text(frame, reason, x=8 * scale, y=base_y, scale=scale, color=(255, 255, 255, 255))
        if detail:
            _draw_debug_text(frame, detail, x=8 * scale, y=base_y + 9 * scale, scale=scale, color=(255, 255, 255, 255))
        ctx.submit_write_batch(WriteBatch([FullRewrite(frame)]))

    def stop(self, ctx) -> None:
        print("\nshutting down...")


def create():
    return FullSuiteInteractiveApp()
