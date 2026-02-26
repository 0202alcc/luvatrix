from __future__ import annotations

from dataclasses import dataclass, replace
import os
import time

import torch
from luvatrix_core.core.window_matrix import FullRewrite, WriteBatch

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


def _build_frame(
    height: int,
    width: int,
    state: InteractionState,
    t: int,
    xx: torch.Tensor,
    yy: torch.Tensor,
) -> torch.Tensor:
    frame = torch.zeros((height, width, 4), dtype=torch.uint8)
    base_r = ((xx * 0.6 + t * 1.8) % 255).to(torch.uint8)
    base_g = ((yy * 0.7 + t * 1.2) % 255).to(torch.uint8)
    base_b = (((xx + yy) * 0.35 + t * 2.2) % 255).to(torch.uint8)
    frame[:, :, 0] = base_r
    frame[:, :, 1] = base_g
    frame[:, :, 2] = base_b
    frame[:, :, 3] = 255

    if state.mouse_in_window:
        radius = 24.0 + min(50.0, 90.0 * state.pressure + 35.0 * abs(state.pinch))
        dist_sq = (xx - state.mouse_x) ** 2 + (yy - state.mouse_y) ** 2
        mask = dist_sq <= (radius * radius)
        intensity = 180 if state.left_down else 110
        frame[:, :, 0] = torch.where(mask, torch.full_like(frame[:, :, 0], intensity), frame[:, :, 0])
        frame[:, :, 1] = torch.where(mask, torch.full_like(frame[:, :, 1], 40 if state.right_down else 200), frame[:, :, 1])
        frame[:, :, 2] = torch.where(mask, torch.full_like(frame[:, :, 2], 255), frame[:, :, 2])

    rotate_boost = int(max(-40.0, min(40.0, state.rotation * 2.0)))
    scroll_boost = int(max(-50.0, min(50.0, state.scroll_y * 0.5)))
    frame[:, :, 0] = torch.clamp(frame[:, :, 0].to(torch.int16) + rotate_boost, 0, 255).to(torch.uint8)
    frame[:, :, 1] = torch.clamp(frame[:, :, 1].to(torch.int16) + scroll_boost, 0, 255).to(torch.uint8)
    return frame


class FullSuiteInteractiveApp:
    def __init__(self) -> None:
        self._sensors: list[str] = []
        self._aspect = os.getenv("LUVATRIX_FSI_ASPECT", "stretch")
        self._coord_frame = os.getenv("LUVATRIX_FSI_COORD_FRAME", "screen_tl")
        self._dashboard_interval = float(os.getenv("LUVATRIX_FSI_DASHBOARD_INTERVAL", "0.35"))
        self._rewrite_delay = float(os.getenv("LUVATRIX_FSI_REWRITE_DELAY", "0.0"))
        self._state = InteractionState()
        self._xx: torch.Tensor | None = None
        self._yy: torch.Tensor | None = None
        self._width = 0
        self._height = 0
        self._frame_count = 0
        self._started = 0.0
        self._last_print = 0.0

    def init(self, ctx) -> None:
        raw_available = os.getenv("LUVATRIX_FSI_AVAILABLE_SENSORS", "")
        available = [x.strip() for x in raw_available.split(",") if x.strip()]
        raw_sensors = os.getenv("LUVATRIX_FSI_SENSORS", "")
        requested = [x.strip() for x in raw_sensors.split(",") if x.strip()]
        self._sensors = select_sensors(requested, available)
        ctx.set_default_coordinate_frame(self._coord_frame)

        snap = ctx.read_matrix_snapshot()
        self._height, self._width, _ = snap.shape
        self._xx = torch.arange(self._width, dtype=torch.float32).unsqueeze(0).expand(self._height, self._width)
        self._yy = torch.arange(self._height, dtype=torch.float32).unsqueeze(1).expand(self._height, self._width)
        self._started = time.perf_counter()
        self._last_print = 0.0

        print("available functional sensors:")
        for sensor in self._sensors:
            sample = ctx.read_sensor(sensor)
            is_functional = sample.status == "OK"
            print(f"  - {sensor}: {'available' if is_functional else sample.status}")

    def loop(self, ctx, dt: float) -> None:
        assert self._xx is not None and self._yy is not None
        events = ctx.poll_hdi_events(max_events=256)
        _apply_hdi_events(self._state, events, self._height)
        if self._state.mouse_in_window:
            rx, ry = ctx.to_render_coords(self._state.mouse_x, self._state.mouse_y)
            render_state = replace(self._state, mouse_x=rx, mouse_y=ry)
        else:
            render_state = self._state
        frame = _build_frame(self._height, self._width, render_state, self._frame_count, self._xx, self._yy)
        self._frame_count += 1
        ctx.submit_write_batch(WriteBatch([FullRewrite(frame)]))

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
