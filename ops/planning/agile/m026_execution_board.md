# P-026 Execution Board

Milestone: `P-026` Runtime Performance Hardening Closeout Signoff  
Epic: `E-2801`  
Task chain: `T-2801 -> (T-2802, T-2803, T-2804) -> T-2805`  
Last updated: `2026-03-03`

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
1. None.

## Success Criteria Spec
1. None.

## Safety Tests Spec
1. None.

## Implementation Tests Spec
1. None.

## Edge Case Tests Spec
1. None.

## Prototype Stage 1
1. None.

## Prototype Stage 2+
1. None.

## Verification Review
1. `T-2806` Summary regenerated with `p99` and resize recovery evidence present.
2. `T-2807` Determinism replay matrix regenerated with `8` seeds x `10` runs and zero mismatches.
3. `T-2808` Incremental matrix regenerated with full required scenarios and drag target compliance.
4. `T-2809` Closeout packet/hash manifest rebuilt; strict evidence validator returns PASS.
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
1. `T-2806` Ready for `Done` transition after merge-to-main gate.
2. `T-2807` Ready for `Done` transition after merge-to-main gate.
3. `T-2808` Ready for `Done` transition after merge-to-main gate.
4. `T-2809` Ready for `Done` transition after merge-to-main gate.

## Done
1. `T-2801` Done with benchmark closeout telemetry (`input_tokens=12800`, `output_tokens=2600`, `wall_time_sec=1540`, `tool_calls=24`).
2. `T-2802` Done with Vulkan guardrails closeout telemetry (`input_tokens=7400`, `output_tokens=1700`, `wall_time_sec=980`, `tool_calls=16`).
3. `T-2803` Done with snapshot safety closeout telemetry (`input_tokens=8100`, `output_tokens=1900`, `wall_time_sec=1120`, `tool_calls=18`).
4. `T-2804` Done with incremental-present closeout telemetry (`input_tokens=8600`, `output_tokens=2100`, `wall_time_sec=1180`, `tool_calls=19`).
5. `T-2805` Done with final packet closeout telemetry (`input_tokens=5200`, `output_tokens=1400`, `wall_time_sec=760`, `tool_calls=12`).

## Blocked
1. None.
