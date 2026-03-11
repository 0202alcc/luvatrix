# R-041 Closeout Packet

## Objective Summary
- Milestone `R-041` targets drag-path responsiveness in shader-heavy scenes with explicit no-lag acceptance gates.
- GO is only permitted when drag scenario latency, jitter, dirty-rect efficiency, and regression gates pass together.

## Task Final States
- `T-4820`: Closeout contract/harness defined for drag scenario GO/NO-GO.
- `T-4821`: Drag hot-path profiling instrumentation and baseline artifact capture.
- `T-4822`: Interaction-time adaptive quality path for stained-glass button during active drag.
- `T-4823`: Backdrop reuse/cache plus bounded ROI + optional half-resolution shader path.
- `T-4824`: Perf/regression gates for no-lag guarantee and interactive drag safety.

## Evidence
- Perf artifact: `artifacts/perf/r041_drag.json`.
- GO/NO-GO harness output: `artifacts/perf/r041_drag_go_no_go.json`.
- Required checks:
  - `PYTHONPATH=. uv run --with pytest pytest tests -k "planes_runtime or origin_refs or debug_overlay or debug_menu_dispatch" -q`
  - `PYTHONPATH=. uv run python tools/perf/run_suite.py --scenario drag --out artifacts/perf/r041_drag.json`
  - `PYTHONPATH=. uv run python ops/ci/r040_macos_debug_menu_functional_smoke.py`
  - `UV_TOOL_DIR=.uv-tools UV_CACHE_DIR=.uv-cache uvx --from gateflow==1.0.0 gateflow --root . validate links`
  - `UV_TOOL_DIR=.uv-tools UV_CACHE_DIR=.uv-cache uvx --from gateflow==1.0.0 gateflow --root . validate closeout`

## Determinism
- Drag perf suite must report deterministic replay for scenario `drag`.
- Event order and poll traces must remain deterministic for fixed seed inputs.

## Protocol Compatibility
- Hit-test and input-routing behavior remains compatible with existing Planes runtime semantics.
- Origin refs and debug overlay functionality are preserved and validated by regression checks.

## Modularity
- Runtime policy (adaptive quality) and renderer optimization (ROI/downsample/backdrop reuse) are isolated to stained-glass button paths.
- Baseline perf harness and GO/NO-GO evaluator are standalone tooling modules under `tools/perf/`.

## Residual Risks
- Threshold tuning may require hardware-profile calibration if environment deviates from target macOS baseline.
- Future shader/material profile expansions should preserve current drag-time downgrade/restore invariants.
