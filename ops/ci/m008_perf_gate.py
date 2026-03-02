from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from luvatrix_core.core.hdi_thread import HDIEvent
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
    return {
        "samples": int(samples),
        "p95_ms": float(p95_ms),
        "p50_ms": float(p50_ms),
        "jitter_ms": float(jitter_ms),
        "compose_modes": compose_modes,
        "dirty_counts": dirty_counts,
    }


def run_perf_gate(samples: int, budget_p95_ms: float, budget_jitter_ms: float) -> dict[str, Any]:
    first = _run_trial(samples)
    second = _run_trial(samples)
    deterministic = (
        first["compose_modes"] == second["compose_modes"]
        and first["dirty_counts"] == second["dirty_counts"]
    )
    p95_ms = float(first["p95_ms"])
    jitter_ms = float(first["jitter_ms"])
    passed = deterministic and p95_ms <= float(budget_p95_ms) and jitter_ms <= float(budget_jitter_ms)
    return {
        "passed": bool(passed),
        "deterministic": bool(deterministic),
        "budget_p95_ms": float(budget_p95_ms),
        "budget_jitter_ms": float(budget_jitter_ms),
        "result": first,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="M-008 perf gate (p95/jitter + deterministic smoke)")
    parser.add_argument("--samples", type=int, default=60)
    parser.add_argument("--budget-p95-ms", type=float, default=40.0)
    parser.add_argument("--budget-jitter-ms", type=float, default=25.0)
    args = parser.parse_args()

    summary = run_perf_gate(
        samples=max(1, int(args.samples)),
        budget_p95_ms=float(args.budget_p95_ms),
        budget_jitter_ms=float(args.budget_jitter_ms),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if bool(summary.get("passed", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
