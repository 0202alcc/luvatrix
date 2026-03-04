from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any

from luvatrix_core.core.hdi_thread import HDIEvent
from luvatrix_core.core.sensor_manager import SensorManagerThread, SensorProvider, TTLCachedSensorProvider
from luvatrix_ui.planes_runtime import load_plane_app

RESIZE_STRESS_FULLFRAME_ALLOWED = "resize_stress_fullframe_allowed"
RESIZE_OVERLAP_INCREMENTAL_REQUIRED = "resize_overlap_incremental_required"
RESIZE_STRESS_ALIAS = "resize_stress"


@dataclass
class _Matrix:
    width: int
    height: int


class _PerfCtx:
    def __init__(self, *, width: int, height: int) -> None:
        self.matrix = _Matrix(width=width, height=height)
        self._events: list[HDIEvent] = []
        self.polled_event_ids: list[list[int]] = []
        self._queued_frame_idx: dict[int, int] = {}
        self.current_frame_idx: int = 0
        self.input_to_present_ms: list[float] = []
        self.frame_budget_ms: float = 1000.0 / 60.0

    def begin_ui_frame(
        self,
        renderer,
        *,
        content_width_px: float,
        content_height_px: float,
        clear_color: tuple[int, int, int, int],
        dirty_rects=None,
        scroll_shift=None,
    ) -> None:
        _ = (renderer, content_width_px, content_height_px, clear_color, dirty_rects, scroll_shift)

    def mount_component(self, component) -> None:
        _ = component

    def finalize_ui_frame(self) -> None:
        return None

    def poll_hdi_events(self, max_events: int):
        out = list(self._events[: max(0, int(max_events))])
        self._events = self._events[max(0, int(max_events)) :]
        self.polled_event_ids.append([int(event.event_id) for event in out])
        return out

    def queue(self, event: HDIEvent) -> None:
        self._queued_frame_idx[int(event.event_id)] = int(self.current_frame_idx)
        self._events.append(event)

    def pending_hdi_events(self) -> int:
        return len(self._events)

    def set_frame_idx(self, frame_idx: int) -> None:
        self.current_frame_idx = int(frame_idx)

    def mark_present(self, event_ids: list[int]) -> None:
        for event_id in event_ids:
            queued_idx = self._queued_frame_idx.pop(int(event_id), None)
            if queued_idx is None:
                continue
            lag_frames = max(0, int(self.current_frame_idx) - int(queued_idx))
            latency_ms = float(lag_frames + 1) * self.frame_budget_ms
            self.input_to_present_ms.append(latency_ms)


class _FastPathProvider(SensorProvider):
    path_class = "fast_path"

    def __init__(self, value: object, unit: str) -> None:
        self._value = value
        self._unit = unit

    def read(self) -> tuple[object, str]:
        return (self._value, self._unit)


class _SlowMetadataProvider(SensorProvider):
    path_class = "cached_path"

    def __init__(self, value: object, unit: str, delay_s: float) -> None:
        self._value = value
        self._unit = unit
        self._delay_s = delay_s

    def read(self) -> tuple[object, str]:
        time.sleep(self._delay_s)
        return (self._value, self._unit)


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if q <= 0:
        return float(min(values))
    if q >= 100:
        return float(max(values))
    ordered = sorted(float(v) for v in values)
    idx = (len(ordered) - 1) * (q / 100.0)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return float(ordered[lo])
    blend = idx - float(lo)
    return float(ordered[lo] * (1.0 - blend) + ordered[hi] * blend)


def _scenario_event(scenario: str, i: int) -> HDIEvent | None:
    if scenario in {"scroll", "render_copy_chain"}:
        return HDIEvent(
            event_id=i + 1,
            ts_ns=i + 1,
            window_id="perf",
            device="trackpad",
            event_type="scroll",
            status="OK",
            payload={"x": 180.0, "y": 200.0, "delta_x": -18.0, "delta_y": -9.0, "phase": "changed"},
        )
    if scenario == "horizontal_pan":
        return HDIEvent(
            event_id=i + 1,
            ts_ns=i + 1,
            window_id="perf",
            device="trackpad",
            event_type="scroll",
            status="OK",
            payload={"x": 180.0, "y": 200.0, "delta_x": -14.0, "delta_y": 0.0, "phase": "changed"},
        )
    if scenario == "drag":
        phase = "single" if i % 6 == 0 else "drag"
        return HDIEvent(
            event_id=i + 1,
            ts_ns=i + 1,
            window_id="perf",
            device="mouse",
            event_type=("press" if i % 6 == 0 else "pointer_move"),
            status="OK",
            payload={"x": 120.0 + (i % 11), "y": 140.0 + (i % 7), "phase": phase},
        )
    if scenario == "drag_heavy":
        phase = "single" if i % 10 == 0 else "drag"
        return HDIEvent(
            event_id=i + 1,
            ts_ns=i + 1,
            window_id="perf",
            device="mouse",
            event_type=("press" if i % 10 == 0 else "pointer_move"),
            status="OK",
            payload={"x": 90.0 + float((i * 3) % 17), "y": 110.0 + float((i * 2) % 13), "phase": phase},
        )
    if scenario == RESIZE_OVERLAP_INCREMENTAL_REQUIRED:
        if i % 4 in {0, 1}:
            return HDIEvent(
                event_id=i + 1,
                ts_ns=i + 1,
                window_id="perf",
                device="trackpad",
                event_type="scroll",
                status="OK",
                payload={"x": 180.0, "y": 200.0, "delta_x": -6.0, "delta_y": -2.0, "phase": "changed"},
            )
        return HDIEvent(
            event_id=i + 1,
            ts_ns=i + 1,
            window_id="perf",
            device="mouse",
            event_type=("press" if i % 12 == 0 else "pointer_move"),
            status="OK",
            payload={"x": 110.0 + float((i * 2) % 17), "y": 125.0 + float((i * 3) % 13), "phase": "drag"},
        )
    return None


def _scenario_matrix_dims(scenario: str, i: int, base_w: int, base_h: int) -> tuple[int, int]:
    if scenario not in {RESIZE_STRESS_FULLFRAME_ALLOWED, RESIZE_OVERLAP_INCREMENTAL_REQUIRED}:
        return (base_w, base_h)
    # Deterministic resize cadence around base extent; overlap scenario uses smaller deltas.
    if scenario == RESIZE_OVERLAP_INCREMENTAL_REQUIRED:
        offsets = ((0, 0), (48, 28), (-36, -20), (64, 36), (-28, -16))
    else:
        offsets = ((0, 0), (160, 90), (-120, -60), (220, 120), (-80, -40))
    dx, dy = offsets[i % len(offsets)]
    return (max(200, base_w + dx), max(120, base_h + dy))


def _normalize_scenario_name(scenario: str) -> str:
    if scenario == RESIZE_STRESS_ALIAS:
        return RESIZE_STRESS_FULLFRAME_ALLOWED
    return scenario


def _should_reinit_on_resize(scenario: str) -> bool:
    return scenario == RESIZE_STRESS_FULLFRAME_ALLOWED


def _run_scenario_trial(scenario: str, samples: int, width: int, height: int) -> dict[str, Any]:
    scenario = _normalize_scenario_name(scenario)
    repo_root = Path(__file__).resolve().parents[2]
    plane_path = repo_root / "examples" / "app_protocol" / "planes_v2_poc" / "plane.json"
    app = load_plane_app(plane_path, handlers={})
    ctx = _PerfCtx(width=width, height=height)
    app.init(ctx)
    app_reinit_count = 0

    frame_total_ms: list[float] = []
    copy_counts: list[int] = []
    copy_bytes: list[int] = []
    compose_modes: list[str] = []
    dirty_counts: list[int] = []
    copy_pack_ms: list[float] = []
    copy_map_ms: list[float] = []
    copy_memcpy_ms: list[float] = []
    queue_submit_ms: list[float] = []
    queue_present_ms: list[float] = []
    swapchain_recreate_counts: list[int] = []
    dirty_area_ratios: list[float] = []
    events_processed: list[int] = []
    event_budgets: list[int] = []
    pending_after_frame: list[int] = []
    event_order_digest_trace: list[str] = []

    event_id_counter = 1
    resize_change_indices: list[int] = []
    for i in range(samples):
        ctx.set_frame_idx(i)
        if scenario == "input_burst":
            if i % 24 == 3:
                for j in range(512):
                    ctx.queue(
                        HDIEvent(
                            event_id=event_id_counter,
                            ts_ns=(i * 1_000_000) + j + 1,
                            window_id="perf",
                            device="trackpad",
                            event_type="scroll",
                            status="OK",
                            payload={
                                "x": 180.0 + float(j % 7),
                                "y": 200.0 + float(j % 5),
                                "delta_x": -3.0,
                                "delta_y": -1.0,
                                "phase": "changed",
                            },
                        )
                    )
                    event_id_counter += 1
            elif i % 6 == 0:
                ctx.queue(
                    HDIEvent(
                        event_id=event_id_counter,
                        ts_ns=(i * 1_000_000) + 1,
                        window_id="perf",
                        device="mouse",
                        event_type="pointer_move",
                        status="OK",
                        payload={"x": 120.0 + float(i % 11), "y": 140.0 + float(i % 7)},
                    )
                )
                event_id_counter += 1
        elif scenario == "mixed_burst":
            # Deterministic mixed-load schedule: scroll bursts + drag + occasional press.
            if i % 10 in {1, 2, 3, 4}:
                ctx.queue(
                    HDIEvent(
                        event_id=event_id_counter,
                        ts_ns=(i * 1_000_000) + 1,
                        window_id="perf",
                        device="trackpad",
                        event_type="scroll",
                        status="OK",
                        payload={"x": 170.0, "y": 210.0, "delta_x": -4.0, "delta_y": -2.0, "phase": "changed"},
                    )
                )
                event_id_counter += 1
            if i % 6 == 0:
                ctx.queue(
                    HDIEvent(
                        event_id=event_id_counter,
                        ts_ns=(i * 1_000_000) + 2,
                        window_id="perf",
                        device="mouse",
                        event_type=("press" if i % 18 == 0 else "pointer_move"),
                        status="OK",
                        payload={"x": 110.0 + float(i % 19), "y": 130.0 + float(i % 15), "phase": "drag"},
                    )
                )
                event_id_counter += 1
        elif scenario == "sensor_overlay":
            if i % 2 == 0:
                ctx.queue(
                    HDIEvent(
                        event_id=event_id_counter,
                        ts_ns=(i * 1_000_000) + 1,
                        window_id="perf",
                        device="trackpad",
                        event_type="scroll",
                        status="OK",
                        payload={"x": 150.0, "y": 190.0, "delta_x": -2.0, "delta_y": -3.0, "phase": "changed"},
                    )
                )
                event_id_counter += 1
            if i % 5 == 0:
                ctx.queue(
                    HDIEvent(
                        event_id=event_id_counter,
                        ts_ns=(i * 1_000_000) + 2,
                        window_id="perf",
                        device="mouse",
                        event_type="pointer_move",
                        status="OK",
                        payload={"x": 100.0 + float(i % 23), "y": 120.0 + float(i % 21), "phase": "single"},
                    )
                )
                event_id_counter += 1
        else:
            event = _scenario_event(scenario, i)
            if event is not None:
                ctx.queue(event)
        w, h = _scenario_matrix_dims(scenario, i, width, height)
        if (w, h) != (ctx.matrix.width, ctx.matrix.height):
            resize_change_indices.append(i)
            ctx.matrix.width = w
            ctx.matrix.height = h
            if _should_reinit_on_resize(scenario):
                app = load_plane_app(plane_path, handlers={})
                app.init(ctx)
                app_reinit_count += 1
        app.loop(ctx, 1.0 / 60.0)
        perf = app.state.get("perf", {}) if isinstance(app.state, dict) else {}
        timing = perf.get("timing_ms", {}) if isinstance(perf, dict) else {}
        copy_timing = perf.get("copy_timing_ms", {}) if isinstance(perf, dict) else {}
        frame_total_ms.append(float(timing.get("frame_total", 0.0)))
        copy_counts.append(int(perf.get("copy_count", 0)))
        copy_bytes.append(int(perf.get("copy_bytes", 0)))
        compose_modes.append(str(perf.get("compose_mode", "unknown")))
        dirty_counts.append(int(perf.get("dirty_rect_count", 0)))
        copy_pack_ms.append(float(copy_timing.get("upload_pack", 0.0)) + float(copy_timing.get("ui_pack", 0.0)))
        copy_map_ms.append(float(copy_timing.get("upload_map", 0.0)))
        copy_memcpy_ms.append(float(copy_timing.get("upload_memcpy", 0.0)))
        queue_submit_ms.append(float(copy_timing.get("queue_submit", 0.0)))
        queue_present_ms.append(float(copy_timing.get("queue_present", 0.0)))
        swapchain_recreate_counts.append(int(perf.get("swapchain_recreate_count", 0)))
        dirty_area_ratios.append(float(perf.get("dirty_rect_area_ratio", 0.0)))
        events_processed.append(int(perf.get("events_processed", 0)))
        event_budgets.append(int(perf.get("event_budget", 0)))
        pending_after_frame.append(int(perf.get("event_queue_pending_after", 0)))
        event_order_digest_trace.append(str(perf.get("event_order_digest", "0")))
        if ctx.polled_event_ids:
            ctx.mark_present(ctx.polled_event_ids[-1])

    p95_ms = _percentile(frame_total_ms, 95.0)
    p50_ms = _percentile(frame_total_ms, 50.0)
    p99_ms = _percentile(frame_total_ms, 99.0)
    frame_budget_ms = 1000.0 / 60.0
    dropped_frames = int(sum(1 for v in frame_total_ms if float(v) > frame_budget_ms))
    dropped_ratio = float(dropped_frames) / float(samples) if samples > 0 else 0.0

    resize_recovery_samples_ms: list[float] = []
    if scenario == RESIZE_STRESS_FULLFRAME_ALLOWED:
        for change_idx in resize_change_indices:
            # Direct recovery measurement: first frame index after resize where 3-frame moving average
            # is below 16.7ms budget.
            for j in range(change_idx, len(frame_total_ms) - 2):
                avg = (frame_total_ms[j] + frame_total_ms[j + 1] + frame_total_ms[j + 2]) / 3.0
                if avg <= frame_budget_ms:
                    resize_recovery_samples_ms.append(float(j - change_idx + 1) * frame_budget_ms)
                    break

    incremental_frames = int(sum(1 for mode in compose_modes if mode == "partial_dirty"))
    full_frames = int(sum(1 for mode in compose_modes if mode == "full_frame"))
    presented_frames = int(incremental_frames + full_frames)
    incremental_pct = (float(incremental_frames) * 100.0 / float(presented_frames)) if presented_frames > 0 else 0.0
    full_pct = (float(full_frames) * 100.0 / float(presented_frames)) if presented_frames > 0 else 0.0
    return {
        "samples": int(samples),
        "p95_frame_total_ms": float(p95_ms),
        "p50_frame_total_ms": float(p50_ms),
        "p99_frame_total_ms": float(p99_ms),
        "jitter_ms": float(max(0.0, p95_ms - p50_ms)),
        "dropped_frames": int(dropped_frames),
        "dropped_frame_ratio": float(dropped_ratio),
        "p95_copy_bytes": int(round(_percentile([float(v) for v in copy_bytes], 95.0))),
        "p95_copy_count": int(round(_percentile([float(v) for v in copy_counts], 95.0))),
        "p95_copy_pack_ms": float(_percentile(copy_pack_ms, 95.0)),
        "p95_copy_map_ms": float(_percentile(copy_map_ms, 95.0)),
        "p95_copy_memcpy_ms": float(_percentile(copy_memcpy_ms, 95.0)),
        "p95_queue_submit_ms": float(_percentile(queue_submit_ms, 95.0)),
        "p95_queue_present_ms": float(_percentile(queue_present_ms, 95.0)),
        "p95_swapchain_recreate_count": int(round(_percentile([float(v) for v in swapchain_recreate_counts], 95.0))),
        "p95_dirty_area_ratio": float(_percentile(dirty_area_ratios, 95.0)),
        "incremental_present_pct": float(incremental_pct),
        "full_present_pct": float(full_pct),
        "incremental_frames": int(incremental_frames),
        "full_frames": int(full_frames),
        "presented_frames": int(presented_frames),
        "compose_modes": compose_modes,
        "dirty_counts": dirty_counts,
        "copy_counts": copy_counts,
        "copy_bytes": copy_bytes,
        "events_processed": events_processed,
        "p95_events_processed": float(_percentile([float(v) for v in events_processed], 95.0)),
        "event_budget_trace": event_budgets,
        "p95_event_budget": float(_percentile([float(v) for v in event_budgets], 95.0)),
        "pending_after_trace": pending_after_frame,
        "max_pending_after": int(max(pending_after_frame) if pending_after_frame else 0),
        "p95_pending_after": float(_percentile([float(v) for v in pending_after_frame], 95.0)),
        "event_order_digest_trace": event_order_digest_trace,
        "event_poll_trace": ctx.polled_event_ids,
        "p95_input_to_present_ms": float(_percentile(ctx.input_to_present_ms, 95.0)),
        "p99_input_to_present_ms": float(_percentile(ctx.input_to_present_ms, 99.0)),
        "input_to_present_ms_trace": [float(v) for v in ctx.input_to_present_ms],
        "app_reinit_count": int(app_reinit_count),
        "resize_recovery_samples_ms": [float(v) for v in resize_recovery_samples_ms],
        "resize_recovery_sec": (
            float(_percentile(resize_recovery_samples_ms, 95.0)) / 1000.0 if resize_recovery_samples_ms else None
        ),
    }


def _run_scenario(scenario: str, samples: int, width: int, height: int) -> dict[str, Any]:
    first = _run_scenario_trial(scenario, samples, width, height)
    second = _run_scenario_trial(scenario, samples, width, height)
    deterministic = (
        first["compose_modes"] == second["compose_modes"]
        and first["dirty_counts"] == second["dirty_counts"]
        and first["copy_counts"] == second["copy_counts"]
        and first["copy_bytes"] == second["copy_bytes"]
        and first["events_processed"] == second["events_processed"]
        and first["event_budget_trace"] == second["event_budget_trace"]
        and first["pending_after_trace"] == second["pending_after_trace"]
        and first["event_order_digest_trace"] == second["event_order_digest_trace"]
        and first["event_poll_trace"] == second["event_poll_trace"]
    )
    return {"deterministic": bool(deterministic), "result": first}


def _run_sensor_polling_trial(samples: int) -> dict[str, Any]:
    poll_interval_s = 0.01
    providers: dict[str, SensorProvider] = {
        "thermal.temperature": _FastPathProvider(71.5, "C"),
        "power.voltage_current": _FastPathProvider({"voltage_v": 12.1, "current_a": 0.8}, "mixed"),
        "sensor.motion": _FastPathProvider({"x": 0.0, "y": 1.0, "z": 0.0}, "raw"),
        "camera.device": TTLCachedSensorProvider(
            _SlowMetadataProvider({"available": True, "device_count": 1}, "metadata", delay_s=0.0025),
            ttl_s=0.2,
        ),
        "microphone.device": TTLCachedSensorProvider(
            _SlowMetadataProvider({"available": True, "device_count": 1, "default_present": True}, "metadata", delay_s=0.002),
            ttl_s=0.2,
        ),
        "speaker.device": TTLCachedSensorProvider(
            _SlowMetadataProvider({"available": True, "device_count": 1, "default_present": True}, "metadata", delay_s=0.002),
            ttl_s=0.2,
        ),
    }
    mgr = SensorManagerThread(providers=providers, poll_interval_s=poll_interval_s)
    mgr.set_sensor_enabled("sensor.motion", True, actor="perf")
    mgr.set_sensor_enabled("camera.device", True, actor="perf")
    mgr.set_sensor_enabled("microphone.device", True, actor="perf")
    mgr.set_sensor_enabled("speaker.device", True, actor="perf")
    mgr.start()
    try:
        # Warm-up so the manager has at least one sample and stable cadence.
        time.sleep(poll_interval_s * 2.5)
        for _ in range(samples):
            _ = mgr.read_sensor("thermal.temperature")
            _ = mgr.read_sensor("power.voltage_current")
            _ = mgr.read_sensor("sensor.motion")
            _ = mgr.read_sensor("camera.device")
            _ = mgr.read_sensor("microphone.device")
            _ = mgr.read_sensor("speaker.device")
            time.sleep(poll_interval_s)
    finally:
        mgr.stop()
    diag = mgr.diagnostics_snapshot()
    cycle_cost_ms = [float(v) for v in diag.get("poll_cycle_cost_ms", [])]
    cycle_interval_ms = [float(v) for v in diag.get("poll_cycle_interval_ms", [])]
    class_latency = diag.get("provider_latency_by_class", {})
    assert isinstance(class_latency, dict)
    return {
        "samples": int(samples),
        "polling_cpu_cost_ms": float(sum(cycle_cost_ms) / len(cycle_cost_ms)) if cycle_cost_ms else 0.0,
        "jitter_ms": float(_percentile(cycle_interval_ms, 95.0) - _percentile(cycle_interval_ms, 50.0))
        if cycle_interval_ms
        else 0.0,
        "cycle_cost_p95_ms": float(_percentile(cycle_cost_ms, 95.0)),
        "cycle_interval_p95_ms": float(_percentile(cycle_interval_ms, 95.0)),
        "provider_latency_by_class": class_latency,
        "provider_latency_by_sensor": diag.get("provider_latency_by_sensor", {}),
        "path_classes": sorted(class_latency.keys()),
    }


def _run_sensor_polling(samples: int) -> dict[str, Any]:
    first = _run_sensor_polling_trial(samples)
    second = _run_sensor_polling_trial(samples)
    deterministic = first.get("path_classes", []) == second.get("path_classes", []) and first.get(
        "provider_latency_by_class", {}
    ).keys() == second.get("provider_latency_by_class", {}).keys()
    return {"deterministic": bool(deterministic), "result": first}


def _copy_chain_map(width: int, height: int) -> list[dict[str, Any]]:
    frame_bytes = int(width * height * 4)
    return [
        {
            "stage": "WindowMatrix.submit_write_batch.stage_clone",
            "ownership": "WindowMatrix internal staged copy",
            "bytes_formula": "matrix_w * matrix_h * 4",
            "nominal_bytes": frame_bytes,
        },
        {
            "stage": "AppContext.finalize_ui_frame.ui_pack",
            "ownership": "UI frame slices copied into ReplaceRect payloads or FullRewrite tensor",
            "bytes_formula": "sum(dirty_rect_w * dirty_rect_h * 4) or full frame bytes",
            "nominal_bytes": frame_bytes,
        },
        {
            "stage": "DisplayRuntime.read_snapshot",
            "ownership": "WindowMatrix -> DisplayRuntime snapshot clone",
            "bytes_formula": "matrix_w * matrix_h * 4",
            "nominal_bytes": frame_bytes,
        },
        {
            "stage": "MoltenVKMacOSBackend._upload_rgba_to_staging.pack/map/memcpy",
            "ownership": "CPU packed bytes mapped into Vulkan staging memory",
            "bytes_formula": "upload_w * upload_h * 4",
            "nominal_bytes": frame_bytes,
        },
    ]


def run_suite(scenario: str, samples: int, width: int, height: int) -> dict[str, Any]:
    normalized = _normalize_scenario_name(scenario)
    valid = {
        "render_copy_chain",
        "idle",
        "scroll",
        "horizontal_pan",
        "drag",
        "drag_heavy",
        "mixed_burst",
        "sensor_overlay",
        RESIZE_STRESS_ALIAS,
        RESIZE_STRESS_FULLFRAME_ALLOWED,
        RESIZE_OVERLAP_INCREMENTAL_REQUIRED,
        "input_burst",
        "sensor_polling",
        "all_interactive",
        "closeout_required",
    }
    if scenario not in valid:
        raise ValueError(f"unsupported scenario: {scenario}")
    if scenario == "all_interactive":
        scenario_list = ["idle", "scroll", "drag", RESIZE_STRESS_FULLFRAME_ALLOWED]
    elif scenario == "closeout_required":
        scenario_list = [
            "scroll",
            "horizontal_pan",
            "drag_heavy",
            "mixed_burst",
            "sensor_overlay",
            RESIZE_STRESS_FULLFRAME_ALLOWED,
            RESIZE_OVERLAP_INCREMENTAL_REQUIRED,
            "input_burst",
            "sensor_polling",
        ]
    else:
        scenario_list = [normalized]
    out: dict[str, Any] = {
        "suite": scenario,
        "samples": int(samples),
        "matrix": {"width": int(width), "height": int(height)},
        "copy_chain_map": _copy_chain_map(width, height),
        "scenarios": {},
        "provenance": {
            "command": " ".join(sys.argv),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "seed_list": [],
            "run_count": 2,
        },
    }
    try:
        out["provenance"]["commit_sha"] = (
            subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        )
    except Exception:
        out["provenance"]["commit_sha"] = "unknown"
    for name in scenario_list:
        if name == "sensor_polling":
            out["scenarios"][name] = _run_sensor_polling(samples)
        else:
            out["scenarios"][name] = _run_scenario(name, samples, width, height)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="P-021 deterministic performance suite")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--samples", type=int, default=60)
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    summary = run_suite(
        scenario=str(args.scenario),
        samples=max(1, int(args.samples)),
        width=max(64, int(args.width)),
        height=max(64, int(args.height)),
    )
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
