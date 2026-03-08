# R-036 Closeout Packet

## Objective Summary
R-036 delivered a macOS-first replay/perf observability contract set: deterministic replay digest evaluation, paused-state frame-step controls, perf HUD snapshots, and deterministic debug bundle export schemas. Non-mac behavior remains explicit capability-declared stubs in this phase.

## Task Final States
1. `T-2922` Done: closeout harness metric/evidence contract and execution board established.
2. `T-2907` Done: deterministic input replay manifest + digest contract implemented with non-mac replay stubs.
3. `T-2908` Done: frame-step guard and perf HUD contract implemented with explicit non-mac stubs.
4. `T-2909` Done: bundle export manifest + required artifact-class validator implemented with explicit non-mac stubs.

## Evidence
1. `PYTHONPATH=. uv run pytest tests/test_debug_replay.py -q` -> pass.
2. `PYTHONPATH=. uv run pytest tests/test_debug_frame_step.py -q` -> pass.
3. `PYTHONPATH=. uv run pytest tests/test_debug_bundle.py -q` -> pass.
4. `PYTHONPATH=. uv run pytest tests -k "debug_replay or debug_frame_step or debug_bundle" -q` -> pass (`14 passed, 400 deselected`).
5. `PYTHONPATH=. uv run python ops/planning/agile/validate_milestone_task_links.py` -> pass.

## Determinism
1. Replay digest computed from canonical sequence/timestamp/event-type/payload digest fields and compared against expected seed-pinned digest.
2. Frame-step increments exactly one frame only from paused state and persists ordering digest for deterministic stepping audit.
3. Bundle output path is deterministic by bundle ID and class completeness validator enforces required observability classes.

## Protocol Compatibility
1. Debug menu capability registry extended without breaking existing IDs.
2. Platform capability matrices preserve macOS-first support while explicitly declaring Windows/Linux stubs for replay/frame-step/hud/bundle.
3. Existing screenshot/record/overlay contracts remain backward compatible with added observability capabilities.

## Modularity
1. Contracts are additive in `luvatrix_core.core.debug_capture` and `luvatrix_core.core.debug_menu`.
2. Replay, frame-step/HUD, and bundle logic are covered by isolated test files for composable validation.
3. Documentation split by task contract to keep implementation and policy traceability clear.

## Residual Risks
1. Cross-platform runtime adapters for Windows/Linux are intentionally unimplemented in this phase; only explicit stubs are declared.
2. Manifest/schema contracts are currently unit-test validated, not yet wired to full runtime artifact generation pipeline.
3. Reopen intent: reopen `R-036` for multi-platform adapter implementation and parity verification after this macOS Go closeout.
