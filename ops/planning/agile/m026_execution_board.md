# P-026 Execution Board

Milestone: `P-026` Runtime Performance Hardening Closeout Signoff  
Epic: `E-2801`  
Task chain: `T-2801 -> (T-2802, T-2803, T-2804) -> T-2805`  
Last updated: `2026-03-04` (T-2814 done)

## Evidence Integrity Remediation (No-Go Until Provenance PASS)
1. Scope: reopen closeout execution due to evidence integrity gaps.
2. Architecture status: `No-Go` until provenance-based evidence passes.
3. Non-negotiable boundaries:
   - `RenderTarget` interface boundary unchanged
   - App protocol + `AppContext` compatibility preserved
   - `SensorProvider` contract preserved
   - `HDIThread` / `SensorManagerThread` separation preserved
   - Deterministic behavior requirements preserved
   - No backend-internal coupling into app logic

## GateFlow Dependency Chain
1. `T-2810` + `T-2811` -> `T-2812` -> `T-2813`

## Incremental-Present Remediation Chain (Current)
1. `T-2814` + `T-2815` + `T-2816` in parallel.
2. `T-2817` after `T-2814`, `T-2815`, and `T-2816` are complete.
3. `T-2818` in parallel track; must complete before final determinism signoff.
4. Final architecture re-review only after `T-2814..T-2818` are `Done` and strict validator passes with scenario-level target enforcement.

## Focused Remediation Set (Strict Evidence Validator)
1. `T-2806` must clear summary blockers:
   - `frame_p99_present`
   - `input_p99_present`
   - `resize_recovery_present`
2. `T-2807` must clear determinism replay blockers:
   - seed coverage `>= 8`
   - runs/seed `>= 10`
   - mismatch count `== 0`
3. `T-2808` must clear incremental matrix blockers:
   - required scenarios include `horizontal_pan`, `mixed_burst`, `sensor_overlay` and full required scenario set
   - drag target passes (`drag_interaction observed >= target`)
4. `T-2809` is final validator gate:
   - rebuild packet/hash manifest
   - `validate_closeout_evidence.py` returns `PASS`

## Execution Order
1. `T-2806`
2. `T-2807` and `T-2808` in parallel after `T-2806`
3. `T-2809` after both `T-2807` and `T-2808`

## Intake
2. `T-2817` Validator hard-gates for incremental targets + exception caps.
3. `T-2818` Determinism seed-fidelity hardening.

## Success Criteria Spec
1. `T-2814` Hover transitions invalidate localized old/new component bounds (+ safety margin), not full frame.
2. `T-2814` Theme transitions use scoped component invalidation when derivable; full-frame only for full-surface theme deltas.
3. `T-2814` Pointer-only non-delta frames take idle/no-op compose path.
4. `T-2815` Fractional scroll accumulator + quantized dirty-strip compose behavior defined.
5. `T-2815` Bounded bi-axial dirty decomposition (edge strips + corner patch) replaces unconditional full-frame fallback where safe.
6. `T-2816` Explicit resize scenarios split into `resize_stress_fullframe_allowed` and `resize_overlap_incremental_required`.
7. `T-2816` Resize stress retains measured resize recovery metric.
8. `T-2816` Resize overlap scenario enforces measured `incremental_present_pct >= 75%`.

## Safety Tests Spec
1. `T-2814` Preserve `RenderTarget`, App protocol/`AppContext`, and `SensorProvider` boundaries; no backend coupling into app logic.
2. `T-2814` Preserve deterministic behavior and `HDIThread`/`SensorManagerThread` separation.
3. `T-2815` Preserve same boundaries while removing only safe fallback paths (no interface/contract changes).
4. `T-2816` Overlap resize measurement avoids app re-init artifacts; `app_reinit_count` remains zero for overlap scenario.

## Implementation Tests Spec
1. `T-2814` `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py -k "hover or drag or theme or dirty_rect" -q`
2. `T-2815` `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py -k "scroll or fractional or diagonal or dirty_rect" -q`
3. `T-2816` `PYTHONPATH=. uv run pytest tests/test_perf_tools.py -q`

## Edge Case Tests Spec
1. `T-2814` Theme background delta must force full-frame invalidation as full-surface effect fallback.
2. `T-2814` Pointer-move with no hover transition must produce `idle_skip` with zero dirty rects.
3. `T-2815` Subpixel deltas must remain deterministic via residual accumulation and bounded quantized updates.
4. `T-2815` Bi-axial scroll must use bounded dirty decomposition + corner patch; no unconditional full-frame fallback.
5. `T-2816` Resize overlap policy check fails if `incremental_present_pct < 75%`.
6. `T-2816` Resize stress and overlap policy checks are tied to measured artifacts only (no synthetic fallbacks).

## Prototype Stage 1
1. `T-2814` Dirty-signature diffing updated to compare against last presented frame state.
2. `T-2815` Residual-based scroll quantization path added and wired through compose planning.
3. `T-2816` Added explicit resize scenario constants and closeout-required suite inclusion for overlap policy measurement.

## Prototype Stage 2+
1. `T-2814` Scoped hover dirty rects implemented for old/new component bounds with 1px safety margin.
2. `T-2814` Scoped theme dirty rects implemented for theme-dependent text color diffs; background theme diffs route to full frame.
3. `T-2815` Bi-axial strip decomposition with explicit corner patch implemented; drag/press pointer-local dirty patching added for bounded updates.
4. `T-2816` Overlap scenario now runs resize cadence without app re-init while stress scenario preserves fullframe-allowed re-init path.
5. `T-2816` Measured summary and strict validator updated for scenario split and overlap `>=75%` hard gate.

## Verification Review
1. `T-2806` Summary regenerated with `p99` and resize recovery evidence present.
2. `T-2807` Determinism replay matrix regenerated with `8` seeds x `10` runs and zero mismatches.
3. `T-2808` Incremental matrix regenerated with full required scenarios and drag target compliance.
4. `T-2809` Closeout packet/hash manifest rebuilt; strict evidence validator returns PASS.
5. `T-2814` Evidence:
   - `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py -k "hover or drag or theme or dirty_rect" -q` -> pass (`3 passed, 28 deselected`).
   - `PYTHONPATH=. uv run python tools/perf/run_suite.py --scenario mixed_burst --samples 120 --width 1280 --height 720 --out artifacts/perf/closeout/raw_mixed_burst.json`
   - Mixed-burst raw artifact path: `artifacts/perf/closeout/raw_mixed_burst.json`
6. `T-2815` Evidence:
   - `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py -k "scroll or fractional or diagonal or dirty_rect" -q` -> pass (`14 passed, 19 deselected`).
   - `PYTHONPATH=. uv run python tools/perf/run_suite.py --scenario horizontal_pan --samples 120 --width 1280 --height 720 --out artifacts/perf/closeout/raw_horizontal_pan.json` -> `incremental_present_pct=98.59154929577464`.
   - `PYTHONPATH=. uv run python tools/perf/run_suite.py --scenario drag_heavy --samples 120 --width 1280 --height 720 --out artifacts/perf/closeout/raw_drag_heavy.json` -> `incremental_present_pct=99.16666666666667`.
7. `T-2816` Evidence:
   - `PYTHONPATH=. uv run pytest tests/test_perf_tools.py -q` -> pass (`4 passed`).
   - `PYTHONPATH=. uv run python tools/perf/run_suite.py --scenario resize_stress --samples 120 --width 1280 --height 720 --out artifacts/perf/closeout/raw_resize_stress_fullframe_allowed.json` -> scenario key `resize_stress_fullframe_allowed` with measured `resize_recovery_sec=0.016666666666666666`.
   - `PYTHONPATH=. uv run python tools/perf/run_suite.py --scenario closeout_required --samples 120 --width 1280 --height 720 --out artifacts/perf/closeout/raw_closeout_required.json` -> includes `resize_overlap_incremental_required` with `incremental_present_pct=99.16666666666667` and `app_reinit_count=0`.
   - `PYTHONPATH=. uv run python tools/perf/build_p026_measured_summary.py --raw artifacts/perf/closeout/raw_closeout_required.json --out artifacts/perf/closeout/measured_summary.json` -> overlap policy threshold pass (`>=75%`).
   - `PYTHONPATH=. uv run python ops/planning/api/validate_closeout_evidence.py --milestone-id P-026` -> `validation: PASS (evidence)`.
1. Unified benchmark threshold gates (task `T-2801` canonical baseline):
- Frame time latency: `p50 <= 16.7ms`, `p95 <= 25.0ms`, `p99 <= 33.3ms` (interactive mixed-load scenarios).
- Input-to-present latency: `p95 <= 33.3ms`, `p99 <= 50.0ms` (burst input scenarios).
- Incremental present ratio: `>= 90%` in required interactive scenarios unless explicitly excepted in `T-2804`.
- Dropped frame budget: `<= 1.0%` per scenario run (`<= 2.0%` for resize stress only).
- Resize stability: no crash/hang; settle to stable present cadence within `<= 1.0s` after resize burst.
- Determinism: `8` fixed seeds x `10` runs/seed per required scenario with exact digest matches and zero invariant mismatches.
2. `T-2802` Vulkan decision record (normative text):
- “For `P-026` runtime performance hardening closeout, Vulkan is treated as a performance-validated but non-primary execution path. Objective signoff does not require Vulkan universal production readiness across all hardware/driver combinations. Objective signoff requires: (1) no architecture boundary violations, (2) deterministic behavior on required seeded suites, (3) stable fallback-blit parity, and (4) explicit runtime guardrails that prevent Vulkan-path instability from impacting app protocol compatibility or responsiveness guarantees.”
3. `T-2802` Disallowed wording in closeout/reporting:
- `Vulkan is fully production-ready on all devices.`
- `Vulkan correctness is guaranteed universally.`
- `Objective closeout proves backend-independent identical performance.`
- `No fallback needed.`
4. `T-2803` Snapshot invariants (must hold):
- Published revisioned snapshots are immutable post-publication; consumers cannot mutate snapshot memory.
- Producer publishes a new revision before writes affecting previously published state.
- No mutable backing reuse for published revisions without copy-on-write/equivalent isolation.
- Reads are bound to one monotonic revision id; repeated reads for same revision are byte-identical.
- No torn-frame reads; read-after-publish visibility covers frame content and dirty-rect metadata.
5. `T-2804` Incremental-present scenario targets:
- Vertical scroll `>=95%`, horizontal pan `>=92%`, drag `>=85%`, mixed burst `>=88%`, sensor overlay `>=90%`, resize-overlap `>=75%`, idle-to-burst `>=85%`.
- Full-screen invalidation control case: expected full-frame baseline (no ratio target).
6. `T-2804` Exception policy caps:
- Allowed only for full-surface effects, full-canvas transforms, swapchain-recreate windows, protocol-declared full invalidation.
- Full-frame share cap in required non-control scenarios: `<=15%`.
- Consecutive full-frame burst outside declared exception windows: `<=8` frames.
1. `T-2801` Unified closeout benchmark protocol evidence:
- `PYTHONPATH=. uv run python tools/perf/run_suite.py --scenario mixed_load --seed 1337 --out artifacts/perf/closeout/mixed_load_seed1337.json`
- `PYTHONPATH=. uv run python tools/perf/run_suite.py --scenario idle_burst_input --seed 1337 --out artifacts/perf/closeout/idle_burst_input_seed1337.json`
- `PYTHONPATH=. uv run python tools/perf/run_suite.py --scenario scroll_drag_heavy --seed 1337 --out artifacts/perf/closeout/scroll_drag_heavy_seed1337.json`
- `PYTHONPATH=. uv run python tools/perf/run_suite.py --scenario resize_stress --seed 1337 --out artifacts/perf/closeout/resize_stress_seed1337.json`
- `PYTHONPATH=. uv run python tools/perf/run_suite.py --scenario sensor_fast_cached --seed 1337 --out artifacts/perf/closeout/sensor_fast_cached_seed1337.json`
- `PYTHONPATH=. uv run python tools/perf/summarize_suite.py --in artifacts/perf/closeout --out artifacts/perf/closeout/summary.json`
2. `T-2802` Vulkan decision gate evidence:
- `PYTHONPATH=. uv run pytest tests/test_vulkan_target.py tests/test_display_runtime.py -q`
- `PYTHONPATH=. uv run python tools/perf/run_suite.py --scenario vulkan_soak --seed 1337 --out artifacts/perf/closeout/vulkan_soak_seed1337.json`
3. `T-2803` Snapshot immutability and determinism evidence:
- `PYTHONPATH=. uv run pytest tests/test_window_matrix.py tests/test_display_runtime.py -k \"snapshot or revision or immutability\" -q`
- `PYTHONPATH=. uv run python tools/perf/run_suite.py --scenario determinism_replay --seed 1337 --runs 20 --out artifacts/perf/closeout/determinism_replay_seed1337.json`
4. `T-2804` Incremental-present coverage closure evidence:
- `PYTHONPATH=. uv run python tools/perf/run_suite.py --scenario incremental_present_matrix --seed 1337 --out artifacts/perf/closeout/incremental_present_matrix_seed1337.json`
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_hdi_thread.py -k \"scroll or drag or dirty_rect\" -q`
5. `T-2805` Final packet reconciliation evidence:
- `PYTHONPATH=. uv run python ops/planning/agile/validate_milestone_task_links.py`
- `PYTHONPATH=. uv run python ops/planning/api/validate_closeout_packet.py --milestone-id P-026`

## Exit Gate
1. Go/No-Go checklist (must all pass for architecture Go >=0.85):
- `T-2801..T-2805` complete with linked reproducible evidence.
- `RenderTarget` contract unchanged.
- App protocol + `AppContext` compatibility preserved.
- `SensorProvider` contract preserved.
- `HDIThread` / `SensorManagerThread` separation preserved.
- No backend-internal coupling introduced into app logic.
- Determinism replay passes with zero required-scenario digest/invariant mismatches.
- Incremental-present targets met or approved exceptions documented within caps.
- Vulkan decision record present and consistent across all artifacts/docs.
- No unresolved High severity risks without accepted waiver.
2. Explicit No-Go blockers:
- Any boundary contract violation.
- Any required determinism mismatch.
- Missing/conflicting Vulkan decision wording.
- Scenario target failures without approved exception rationale/caps.
- Unresolved High-severity render/sensor/input coupling risk.
- Missing or non-reproducible required evidence.

## Integration Ready
1. None.

## Done
1. `T-2801` Done with benchmark closeout telemetry (`input_tokens=12800`, `output_tokens=2600`, `wall_time_sec=1540`, `tool_calls=24`).
2. `T-2802` Done with Vulkan guardrails closeout telemetry (`input_tokens=7400`, `output_tokens=1700`, `wall_time_sec=980`, `tool_calls=16`).
3. `T-2803` Done with snapshot safety closeout telemetry (`input_tokens=8100`, `output_tokens=1900`, `wall_time_sec=1120`, `tool_calls=18`).
4. `T-2804` Done with incremental-present closeout telemetry (`input_tokens=8600`, `output_tokens=2100`, `wall_time_sec=1180`, `tool_calls=19`).
5. `T-2805` Done with final packet closeout telemetry (`input_tokens=5200`, `output_tokens=1400`, `wall_time_sec=760`, `tool_calls=12`).
6. `T-2806` Done with summary remediation telemetry (`input_tokens=3200`, `output_tokens=950`, `wall_time_sec=780`, `tool_calls=11`).
7. `T-2807` Done with determinism replay remediation telemetry (`input_tokens=4100`, `output_tokens=1100`, `wall_time_sec=920`, `tool_calls=13`).
8. `T-2808` Done with incremental matrix remediation telemetry (`input_tokens=3600`, `output_tokens=1000`, `wall_time_sec=840`, `tool_calls=12`).
9. `T-2809` Done with strict evidence validator closeout telemetry (`input_tokens=2800`, `output_tokens=800`, `wall_time_sec=640`, `tool_calls=9`).
10. `T-2810` Done with raw measured evidence regeneration telemetry (`input_tokens=5400`, `output_tokens=1300`, `wall_time_sec=1260`, `tool_calls=15`).
11. `T-2811` Done with replay matrix telemetry (`input_tokens=6900`, `output_tokens=1600`, `wall_time_sec=1680`, `tool_calls=18`).
12. `T-2812` Done with provenance-enforcing validator telemetry (`input_tokens=4800`, `output_tokens=1400`, `wall_time_sec=1140`, `tool_calls=14`).
13. `T-2813` Done with packet reconciliation telemetry (`input_tokens=3600`, `output_tokens=1000`, `wall_time_sec=840`, `tool_calls=11`).
14. `T-2815` Done with subpixel + bi-axial compose remediation telemetry (`input_tokens=9800`, `output_tokens=2100`, `wall_time_sec=3240`, `tool_calls=27`).
15. `T-2816` Done with resize scenario split + policy clarification telemetry (`input_tokens=6200`, `output_tokens=1500`, `wall_time_sec=2100`, `tool_calls=22`, `reopen_count=0`).
16. `T-2816` merged to `main` via PR #9; required checks on `main` validated before Done transition.
17. `T-2814` Done with dirty-region invalidation remediation telemetry (`input_tokens=7400`, `output_tokens=1800`, `wall_time_sec=2100`, `tool_calls=26`, `reopen_count=0`).
18. `T-2814` merged to `main`; required checks on `main` validated before Done transition.

## Blocked
1. None.
