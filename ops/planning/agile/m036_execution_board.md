# R-036 Execution Board

Milestone: `R-036` Replay + Perf Observability  
Scope lock: macOS-first only. Non-mac paths must be explicit stubs/capability-declared.  
Task chain: `T-2922 -> T-2907 -> T-2908 -> T-2909`

## Intake
1. None.

## Success Criteria Spec
1. `T-2922` Milestone closeout metric contract defined with macOS-context Go/No-Go threshold and explicit non-mac stub declaration requirements.

## Safety Tests Spec
1. `T-2922` Hard No-Go if replay digest mismatches required seed matrix, frame-step violates deterministic ordering, bundle exports miss required artifact classes, or non-mac behavior is implicit/undefined.

## Implementation Tests Spec
1. `T-2922` `uv run pytest tests -k "debug_replay or debug_frame_step or debug_bundle" -q`
2. `T-2922` `uv run python ops/planning/agile/validate_milestone_task_links.py`

## Edge Case Tests Spec
1. `T-2922` Non-mac platform declarations must remain explicit stubs with unsupported reasons.
2. `T-2922` Replay/frame-step/bundle contracts must preserve deterministic provenance keys and ordering digests.

## Prototype Stage 1
1. `T-2922` Execution board + harness spec drafted and linked to milestone closeout criteria.

## Prototype Stage 2+
1. `T-2907` Replay contract coverage expanded with deterministic digest comparison path and explicit non-mac replay stub declarations.
2. `T-2908` Frame-step transition guard + perf HUD snapshot schema implemented with explicit non-mac stub declarations.
3. `T-2909` Bundle export manifest schema and deterministic bundle zip-path contract implemented with artifact-class validation.

## Verification Review
1. `T-2907` Replay digest generation and mismatch-path assertions verified via `tests/test_debug_replay.py`.
2. `T-2907` Platform matrix reviewed for explicit replay stub declarations on non-mac targets.
3. `T-2908` Frame-step paused-state guard and perf HUD field assertions verified via `tests/test_debug_frame_step.py`.
4. `T-2908` Debug menu capability mapping verified for `debug.frame.step` and `debug.perf.hud`.
5. `T-2909` Bundle manifest required-field and artifact-class completeness checks verified via `tests/test_debug_bundle.py`.
6. `T-2909` Debug menu and platform matrices reviewed for explicit `debug.bundle.export` support + non-mac bundle stubs.

## Integration Ready
1. `T-2907` Replay contract module/tests/docs are ready for milestone branch integration.
2. `T-2908` Frame-step + perf HUD module/tests/docs are ready for milestone branch integration.
3. `T-2909` Bundle export module/tests/docs are ready for milestone branch integration.

## Done
1. `T-2907` Completed deterministic replay manifest + digest contract and explicit non-mac replay stub matrix coverage.
2. `T-2908` Completed frame-step determinism guard and perf HUD snapshot contract with explicit non-mac stub capability coverage.
3. `T-2909` Completed deterministic debug bundle export manifest contract with required artifact-class validator and explicit non-mac bundle stubs.
