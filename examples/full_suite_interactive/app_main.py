from __future__ import annotations

import json
import os
import sys
import time

from luvatrix.app import App, InputState


_COORD_FRAME_ORDER = ("screen_tl", "cartesian_bl", "cartesian_center")


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


def _hdi_ascii_table(state: InputState) -> str:
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
    state: InputState,
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
            "Luvatrix Full Suite Interactive Example (App Protocol v3)",
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


def select_sensors(requested: list[str], available_sensors: list[str]) -> list[str]:
    if not requested:
        return list(available_sensors)
    selected: list[str] = []
    for sensor in requested:
        if sensor not in available_sensors:
            raise ValueError(
                f"unsupported sensor `{sensor}` on this runtime; choose from: {', '.join(available_sensors)}"
            )
        if sensor not in selected:
            selected.append(sensor)
    return selected


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


def _debug_text_chunks(value: str, width: int, max_lines: int) -> list[str]:
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -.:_|")
    compact = " ".join("".join(ch if ch.upper() in allowed else " " for ch in value.upper()).split())
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


def _frame_clear_color(state: InputState, t: int) -> tuple[int, int, int, int]:
    base_r = int((t * 3 + 35) % 255)
    base_g = int((t * 2 + 70) % 255)
    base_b = int((t * 4 + 20) % 255)
    rotate_boost = int(max(-30.0, min(30.0, state.rotation * 2.0)))
    scroll_boost = int(max(-40.0, min(40.0, state.scroll_y * 0.5)))
    r = max(0, min(255, base_r + rotate_boost))
    g = max(0, min(255, base_g + scroll_boost))
    b = max(0, min(255, base_b))
    return (r, g, b, 255)


class FullSuiteInteractiveApp(App):
    def setup(self) -> None:
        self._aspect = os.getenv("LUVATRIX_FSI_ASPECT", "stretch")
        self._dashboard_interval = float(os.getenv("LUVATRIX_FSI_DASHBOARD_INTERVAL", "0.35"))
        self._rewrite_delay = float(os.getenv("LUVATRIX_FSI_REWRITE_DELAY", "0.0"))
        self._debug = os.getenv("LUVATRIX_FSI_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")
        raw_available = os.getenv("LUVATRIX_FSI_AVAILABLE_SENSORS", "")
        available = [x.strip() for x in raw_available.split(",") if x.strip()] or self.sensors.available()
        raw_sensors = os.getenv("LUVATRIX_FSI_SENSORS", "")
        requested = [x.strip() for x in raw_sensors.split(",") if x.strip()]
        self._sensors = self.sensors.select(requested, available=available)
        self._state = InputState()
        self._frame_count = 0
        self._started = time.perf_counter()
        self._last_print = 0.0
        self._win_count = 0
        self._win_start = self._started
        self._last_fps = 0.0
        self._debug_lines: tuple[str, str, str] = ("", "", "")
        self._debug_err_chunks: list[str] = []
        self._last_debug_text_ts = 0.0
        self.coordinates.set_default(os.getenv("LUVATRIX_FSI_COORD_FRAME", self.coordinates.default))

        print("[full_suite] app protocol v3 public API enabled", file=sys.stderr, flush=True)
        print("available functional sensors:")
        for sensor in self._sensors:
            sample = self.sensors.read(sensor)
            is_functional = sample.status == "OK"
            print(f"  - {sensor}: {'available' if is_functional else sample.status}")

    def update(self, dt: float) -> None:
        _ = dt
        self._state = self.input.snapshot(max_events=256, frame="screen_tl")
        self.coordinates.bind_switch_keys(self._state, frames=_COORD_FRAME_ORDER)
        self._frame_count += 1
        now = time.perf_counter()
        if self._debug:
            self._update_debug_overlay(now)
        if now - self._last_print >= self._dashboard_interval:
            fps = self._last_fps or (self._frame_count / max(1e-6, now - self._started))
            samples = self.sensors.read_many(self._sensors)
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

    def render(self) -> None:
        width = self.display.width_px
        height = self.display.height_px
        clear = _frame_clear_color(self._state, self._frame_count)
        with self.frame(clear=clear) as frame:
            frame.shader_rect(
                "full_suite_background",
                width=float(width),
                height=float(height),
                uniforms=(float(time.perf_counter() - self._started) * 120.0, float(self._state.rotation), float(self._state.scroll_y)),
                z_index=0,
            )
            self._draw_pointer(frame, width, height)
            self._draw_status(frame, width, height)

    def teardown(self) -> None:
        print("\nshutting down...")

    def _draw_pointer(self, frame, width: int, height: int) -> None:
        if self._state.active_touches:
            for idx, (_touch_id, (touch_x, touch_y)) in enumerate(sorted(self._state.active_touches.items())):
                radius = 18.0 + min(50.0, 70.0 * max(0.0, self._state.pressure))
                frame.circle(
                    cx=max(0.0, min(float(width), touch_x)),
                    cy=max(0.0, min(float(height), touch_y)),
                    radius=radius,
                    fill=(102, 221, 255, 96),
                    stroke=(248, 250, 252, 255),
                    stroke_width=2.0,
                    z_index=10 + idx,
                )
            return
        if not self._state.mouse_in_window:
            return
        radius = 24.0 + min(50.0, 90.0 * self._state.pressure + 35.0 * abs(self._state.pinch))
        frame.circle(
            cx=max(0.0, min(float(width), self._state.mouse_x)),
            cy=max(0.0, min(float(height), self._state.mouse_y)),
            radius=radius,
            fill=(255, 102, 170, 96) if self._state.left_down else (102, 221, 255, 96),
            stroke=(255, 136, 204, 255) if self._state.right_down else (232, 247, 255, 255),
            stroke_width=2.0,
            z_index=10,
        )
        dx, dy = self.coordinates.from_render(
            self._state.mouse_x,
            self._state.mouse_y,
            frame=self.coordinates.default,
        )
        text_x = max(0.0, min(float(width - 180), self._state.mouse_x + 12.0))
        text_y = max(0.0, min(float(height - 24), self._state.mouse_y - 22.0))
        frame.text(
            _mouse_label_text(self.coordinates.default, dx, dy),
            x=text_x,
            y=text_y,
            font_size_px=14.0,
            color=(248, 250, 252, 255),
            z_index=20,
            cache_key="mouse_label",
        )

    def _draw_status(self, frame, width: int, height: int) -> None:
        _ = width
        bottom = float(height)
        lines = [
            ("1 screen_tl | 2 cart_bl", 84.0, 12.0, (226, 232, 240, 255), "frame_hint"),
            ("3 cart_ctr | c cycle", 66.0, 12.0, (226, 232, 240, 255), "frame_hint_more"),
            (f"active frame: {self.coordinates.default}", 46.0, 12.0, (254, 240, 138, 255), "active_frame"),
            (
                f"touches:{self._state.touch_count} scale:{self._state.gesture_scale:.2f} rot:{self._state.gesture_rotation:.2f}",
                28.0,
                10.0,
                (186, 230, 253, 255),
                "touch_status",
            ),
        ]
        if self._debug:
            lines.extend(
                (line, 12.0 + idx * 11.0, 8.0, (186, 230, 253, 255), f"runtime_status_{idx}")
                for idx, line in enumerate(self._debug_lines)
            )
            lines.extend(
                (line, 106.0 + idx * 14.0, 9.0, (254, 202, 202, 255), f"runtime_error_{idx}")
                for idx, line in enumerate(self._debug_err_chunks)
            )
        for text, offset, size, color, key in lines:
            frame.text(
                text,
                x=8.0,
                y=max(0.0, bottom - offset),
                font_size_px=size,
                color=color,
                z_index=30,
                cache_key=key,
            )

    def _update_debug_overlay(self, now_t: float) -> None:
        display_link = _ios_display_link_telemetry()
        runtime = self.ctx.runtime_telemetry()
        win_elapsed = now_t - self._win_start
        if win_elapsed >= 2.0:
            self._last_fps = (self._frame_count - self._win_count) / max(1e-6, win_elapsed)
            self._win_count = self._frame_count
            self._win_start = now_t
        if now_t - self._last_debug_text_ts < 0.25:
            return
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
        accel_err = os.getenv("LUVATRIX_IOS_ACCEL_IMPORT_ERROR", "").replace("\n", " ")
        self._debug_err_chunks = _debug_text_chunks(accel_err, 38, 4) if accel_err else []
        self._last_debug_text_ts = now_t


def create() -> FullSuiteInteractiveApp:
    return FullSuiteInteractiveApp()
