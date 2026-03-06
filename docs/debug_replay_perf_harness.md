# Replay + Perf Observability Harness (R-036)

## Objective
Define closeout metric and evidence harness for the macOS-first replay/perf milestone (`R-036`).

## Phase Policy
1. This phase is macOS-first only.
2. Windows/Linux behavior must remain explicit stubs/capability-declared.
3. Go/No-Go is evaluated in macOS context only and must close with explicit reopen intent for multi-platform expansion.

## Metric Contract
1. Metric ID: `r-036-closeout-v1`
2. Formula: `0.4*replay_determinism + 0.25*frame_step_safety + 0.35*bundle_completeness`
3. Go threshold: `89`

## Hard No-Go Conditions
1. Replay digest mismatch in required seed matrix.
2. Frame-step violates deterministic ordering.
3. Bundle export misses required artifact classes.
4. Non-mac behavior is undefined instead of explicit stub/capability declaration.

## Required Evidence
1. Replay matrix tests.
2. Frame-step determinism tests.
3. Bundle validator outputs.
4. MacOS-first Go/No-Go packet with explicit non-mac stub/capability matrix and reopen plan note.

## Required Commands
1. `uv run pytest tests -k "debug_replay or debug_frame_step or debug_bundle" -q`
2. `uv run python ops/planning/agile/validate_milestone_task_links.py`

## Non-mac Explicit Stub Matrix
1. `windows`: unsupported in this phase; declares replay/frame-step/hud/bundle stub capabilities with explicit reason.
2. `linux`: unsupported in this phase; declares replay/frame-step/hud/bundle stub capabilities with explicit reason.

## Reopen Intent
Close this phase on macOS evidence only, then reopen `R-036` to implement and validate Windows/Linux adapter parity.
