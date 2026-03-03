# R-025 Execution Board

Milestone: `R-025` Event loop and input scheduling tightening  
Epic: `E-2601`  
Task chain: `T-2601 -> T-2602 -> T-2603 -> T-2604`  
Last updated: `2026-03-03`

## Intake
1. None.

## Success Criteria Spec
1. `T-2601` Profile HDI/event queue idle and burst behavior with deterministic ordering preserved.

## Safety Tests Spec
1. `T-2602` Ensure burst coalescing does not introduce nondeterministic routing/drops.

## Implementation Tests Spec
1. `T-2603` Verify no-change render-path suppression without frame-correctness regressions.

## Edge Case Tests Spec
1. `T-2604` Add deterministic ordering and latency telemetry regressions for burst replay paths.

## Prototype Stage 1
1. `T-2601` HDI burst baseline profiling artifacts.
2. `T-2602` Deterministic coalescing + event-budget tuning implementation.
3. `T-2603` Idle/no-change render skip validation through compose-mode telemetry.
4. `T-2604` Regression coverage for ordering digest and latency telemetry.

## Prototype Stage 2+
1. None.

## Verification Review
1. Evidence commands:
- `PYTHONPATH=. uv run python tools/perf/run_suite.py --scenario input_burst --out artifacts/perf/input_burst_candidate.json`
- `PYTHONPATH=. uv run pytest tests/test_hdi_thread.py tests/test_planes_runtime.py tests/test_perf_tools.py -q`
- `PYTHONPATH=. uv run pytest tests -k "event_order or coalescing or determinism" -q`

## Integration Ready
1. Merged to `main`: `098e6b0`.
2. Post-merge verification artifact: `artifacts/perf/input_burst_main_postmerge.json`.

## Done
1. `T-2601` Done with before/after HDI burst profiling (`r025_hdi_burst_pre.json`, `r025_hdi_burst_post.json`).
2. `T-2602` Done with deterministic motion coalescing and adaptive event-budget processing.
3. `T-2603` Done with idle/no-change render suppression represented by `idle_skip` compose telemetry and dirty-rect guards.
4. `T-2604` Done with ordering digest + latency/coalescing telemetry and regression tests.

## Blocked
1. None.
