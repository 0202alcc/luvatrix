from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from luvatrix_core.core.app_runtime import AppContext
from luvatrix_core.core.hdi_thread import HDIEvent
from luvatrix_core.core.sensor_manager import SensorSample
from luvatrix_core.core.window_matrix import WindowMatrix
from luvatrix_ui.planes_runtime import load_plane_app


@dataclass
class _Matrix:
    width: int
    height: int


class _PerfGateCtx:
    def __init__(self, *, width: int, height: int) -> None:
        self.matrix = _Matrix(width=width, height=height)
        self._events: list[HDIEvent] = []

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
        _ = max_events
        out = list(self._events)
        self._events = []
        return out

    def queue(self, event: HDIEvent) -> None:
        self._events.append(event)


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


def _run_trial(samples: int) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[2]
    plane_path = repo_root / "examples" / "app_protocol" / "planes_v2_poc" / "plane.json"
    app = load_plane_app(plane_path, handlers={})
    ctx = _PerfGateCtx(width=1600, height=1000)
    app.init(ctx)
    frame_times_ms: list[float] = []
    compose_modes: list[str] = []
    dirty_counts: list[int] = []

    for i in range(samples):
        if i % 3 == 0:
            ctx.queue(
                HDIEvent(
                    event_id=i + 1,
                    ts_ns=i + 1,
                    window_id="perf",
                    device="trackpad",
                    event_type="scroll",
                    status="OK",
                    payload={
                        "x": 180.0,
                        "y": 200.0,
                        "delta_x": -18.0,
                        "delta_y": -9.0,
                        "phase": "changed",
                    },
                )
            )
        app.loop(ctx, 1.0 / 60.0)
        perf = app.state.get("perf", {}) if isinstance(app.state, dict) else {}
        timing = perf.get("timing_ms", {}) if isinstance(perf, dict) else {}
        frame_times_ms.append(float(timing.get("frame_total", 0.0)))
        compose_modes.append(str(perf.get("compose_mode", "unknown")))
        dirty_counts.append(int(perf.get("dirty_rect_count", 0)))

    p95_ms = _percentile(frame_times_ms, 95.0)
    p50_ms = _percentile(frame_times_ms, 50.0)
    jitter_ms = max(0.0, p95_ms - p50_ms)
    incremental_frames = int(sum(1 for mode in compose_modes if mode == "partial_dirty"))
    full_frames = int(sum(1 for mode in compose_modes if mode == "full_frame"))
    presented_frames = int(incremental_frames + full_frames)
    incremental_pct = (float(incremental_frames) * 100.0 / float(presented_frames)) if presented_frames > 0 else 0.0
    full_pct = (float(full_frames) * 100.0 / float(presented_frames)) if presented_frames > 0 else 0.0
    return {
        "samples": int(samples),
        "p95_ms": float(p95_ms),
        "p50_ms": float(p50_ms),
        "jitter_ms": float(jitter_ms),
        "incremental_present_pct": float(incremental_pct),
        "full_present_pct": float(full_pct),
        "compose_modes": compose_modes,
        "dirty_counts": dirty_counts,
    }


class _NoopSensorManager:
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def read_sensor(self, sensor_type: str) -> SensorSample:
        return SensorSample(
            sample_id=0,
            ts_ns=0,
            sensor_type=sensor_type,
            status="UNAVAILABLE",
            value=None,
            unit=None,
        )


class _QueuedHDI:
    def __init__(self) -> None:
        self._events: list[HDIEvent] = []

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def queue(self, event: HDIEvent) -> None:
        self._events.append(event)

    def poll_events(self, max_events: int) -> list[HDIEvent]:
        out = list(self._events[: max_events])
        self._events = self._events[max_events:]
        return out


def _run_visual_parity_trial(samples: int) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[2]
    plane_path = repo_root / "examples" / "app_protocol" / "planes_v2_poc" / "plane.json"
    sequence = [
        {"x": 180.0, "y": 200.0, "delta_x": -18.0, "delta_y": -9.0},
        {"x": 180.0, "y": 200.0, "delta_x": -12.0, "delta_y": -6.0},
        {"x": 180.0, "y": 200.0, "delta_x": 9.0, "delta_y": 4.0},
    ]

    def _run(force_full: bool) -> list[Any]:
        hdi = _QueuedHDI()
        ctx = AppContext(
            matrix=WindowMatrix(1000, 1600),
            hdi=hdi,  # type: ignore[arg-type]
            sensor_manager=_NoopSensorManager(),  # type: ignore[arg-type]
            granted_capabilities={"window.write", "hdi.mouse"},
        )
        app = load_plane_app(plane_path, handlers={})
        app.init(ctx)
        app.loop(ctx, 1.0 / 60.0)
        snapshots: list[Any] = [ctx.read_matrix_snapshot()]
        for i in range(max(1, int(samples))):
            payload = dict(sequence[i % len(sequence)])
            if force_full:
                app.state["force_full_invalidation"] = True
                app.state["force_full_invalidation_reason"] = "perf_gate_visual_parity"
            hdi.queue(
                HDIEvent(
                    event_id=i + 1,
                    ts_ns=i + 1,
                    window_id="perf",
                    device="mouse",
                    event_type="scroll",
                    status="OK",
                    payload=payload,
                )
            )
            app.loop(ctx, 1.0 / 60.0)
            snapshots.append(ctx.read_matrix_snapshot())
        return snapshots

    incremental = _run(force_full=False)
    forced_full = _run(force_full=True)
    mismatch_count = 0
    compare_frames = min(len(incremental), len(forced_full))
    for i in range(compare_frames):
        if not bool((incremental[i] == forced_full[i]).all().item()):
            mismatch_count += 1
    return {
        "frames_compared": int(compare_frames),
        "mismatch_frames": int(mismatch_count),
        "passed": bool(mismatch_count == 0 and len(incremental) == len(forced_full)),
    }


def run_perf_gate(
    samples: int,
    budget_p95_ms: float,
    budget_jitter_ms: float,
    *,
    min_incremental_pct: float = 1.0,
    max_visual_mismatch_frames: int = 0,
) -> dict[str, Any]:
    first = _run_trial(samples)
    second = _run_trial(samples)
    visual = _run_visual_parity_trial(min(12, max(3, int(samples // 5))))
    deterministic = (
        first["compose_modes"] == second["compose_modes"]
        and first["dirty_counts"] == second["dirty_counts"]
    )
    p95_ms = float(first["p95_ms"])
    jitter_ms = float(first["jitter_ms"])
    incremental_pct = float(first.get("incremental_present_pct", 0.0))
    visual_mismatch = int(visual.get("mismatch_frames", 0))
    passed = (
        deterministic
        and p95_ms <= float(budget_p95_ms)
        and jitter_ms <= float(budget_jitter_ms)
        and incremental_pct >= float(min_incremental_pct)
        and visual_mismatch <= int(max_visual_mismatch_frames)
        and bool(visual.get("passed", False))
    )
    return {
        "passed": bool(passed),
        "deterministic": bool(deterministic),
        "budget_p95_ms": float(budget_p95_ms),
        "budget_jitter_ms": float(budget_jitter_ms),
        "min_incremental_pct": float(min_incremental_pct),
        "max_visual_mismatch_frames": int(max_visual_mismatch_frames),
        "visual_parity": visual,
        "result": first,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="M-008 perf gate (p95/jitter + deterministic smoke)")
    parser.add_argument("--samples", type=int, default=60)
    parser.add_argument("--budget-p95-ms", type=float, default=40.0)
    parser.add_argument("--budget-jitter-ms", type=float, default=25.0)
    parser.add_argument("--min-incremental-pct", type=float, default=1.0)
    parser.add_argument("--max-visual-mismatch-frames", type=int, default=0)
    args = parser.parse_args()

    summary = run_perf_gate(
        samples=max(1, int(args.samples)),
        budget_p95_ms=float(args.budget_p95_ms),
        budget_jitter_ms=float(args.budget_jitter_ms),
        min_incremental_pct=float(args.min_incremental_pct),
        max_visual_mismatch_frames=max(0, int(args.max_visual_mismatch_frames)),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if bool(summary.get("passed", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
