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


class _PerfCtx:
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
    return None


def _scenario_matrix_dims(scenario: str, i: int, base_w: int, base_h: int) -> tuple[int, int]:
    if scenario != "resize_stress":
        return (base_w, base_h)
    # Deterministic resize cadence around base extent.
    offsets = ((0, 0), (160, 90), (-120, -60), (220, 120), (-80, -40))
    dx, dy = offsets[i % len(offsets)]
    return (max(200, base_w + dx), max(120, base_h + dy))


def _run_scenario_trial(scenario: str, samples: int, width: int, height: int) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[2]
    plane_path = repo_root / "examples" / "app_protocol" / "planes_v2_poc" / "plane.json"
    app = load_plane_app(plane_path, handlers={})
    ctx = _PerfCtx(width=width, height=height)
    app.init(ctx)

    frame_total_ms: list[float] = []
    copy_counts: list[int] = []
    copy_bytes: list[int] = []
    compose_modes: list[str] = []
    dirty_counts: list[int] = []
    copy_pack_ms: list[float] = []
    copy_map_ms: list[float] = []
    copy_memcpy_ms: list[float] = []

    for i in range(samples):
        event = _scenario_event(scenario, i)
        if event is not None:
            ctx.queue(event)
        w, h = _scenario_matrix_dims(scenario, i, width, height)
        if (w, h) != (ctx.matrix.width, ctx.matrix.height):
            ctx.matrix.width = w
            ctx.matrix.height = h
            app = load_plane_app(plane_path, handlers={})
            app.init(ctx)
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

    p95_ms = _percentile(frame_total_ms, 95.0)
    p50_ms = _percentile(frame_total_ms, 50.0)
    return {
        "samples": int(samples),
        "p95_frame_total_ms": float(p95_ms),
        "p50_frame_total_ms": float(p50_ms),
        "jitter_ms": float(max(0.0, p95_ms - p50_ms)),
        "p95_copy_bytes": int(round(_percentile([float(v) for v in copy_bytes], 95.0))),
        "p95_copy_count": int(round(_percentile([float(v) for v in copy_counts], 95.0))),
        "p95_copy_pack_ms": float(_percentile(copy_pack_ms, 95.0)),
        "p95_copy_map_ms": float(_percentile(copy_map_ms, 95.0)),
        "p95_copy_memcpy_ms": float(_percentile(copy_memcpy_ms, 95.0)),
        "compose_modes": compose_modes,
        "dirty_counts": dirty_counts,
        "copy_counts": copy_counts,
        "copy_bytes": copy_bytes,
    }


def _run_scenario(scenario: str, samples: int, width: int, height: int) -> dict[str, Any]:
    first = _run_scenario_trial(scenario, samples, width, height)
    second = _run_scenario_trial(scenario, samples, width, height)
    deterministic = (
        first["compose_modes"] == second["compose_modes"]
        and first["dirty_counts"] == second["dirty_counts"]
        and first["copy_counts"] == second["copy_counts"]
        and first["copy_bytes"] == second["copy_bytes"]
    )
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
    valid = {"render_copy_chain", "idle", "scroll", "drag", "resize_stress", "all_interactive"}
    if scenario not in valid:
        raise ValueError(f"unsupported scenario: {scenario}")
    scenario_list = ["idle", "scroll", "drag", "resize_stress"] if scenario == "all_interactive" else [scenario]
    out: dict[str, Any] = {
        "suite": scenario,
        "samples": int(samples),
        "matrix": {"width": int(width), "height": int(height)},
        "copy_chain_map": _copy_chain_map(width, height),
        "scenarios": {},
    }
    for name in scenario_list:
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
