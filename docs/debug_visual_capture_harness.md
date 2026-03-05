# Visual + Capture Harness (U-035)

## Objective
Define closeout metric and evidence harness for the macOS-first visual/capture milestone (`U-035`).

## Phase Policy
1. This phase is macOS-first only.
2. Windows/Linux behavior must remain explicit stubs/capability-declared.
3. Go/No-Go is evaluated in macOS context only and must close with explicit reopen intent for multi-platform expansion.

## Metric Contract
1. Metric ID: `u-035-closeout-v1`
2. Formula: `0.45*capture_contract + 0.25*overlay_safety + 0.3*runtime_budget_safety`
3. Go threshold: `87`

## Hard No-Go Conditions
1. Capture start/stop violates render budget envelope.
2. Metadata sidecar misses required provenance keys.
3. Overlay toggles alter app state/render semantics.
4. Non-mac behavior is undefined instead of explicit stub/capability declaration.

## Required Evidence
1. Screenshot schema tests.
2. Recording lifecycle perf tests.
3. Overlay regression snapshots.
4. MacOS-first Go/No-Go packet with explicit non-mac stub/capability matrix and reopen plan note.

## Required Commands
1. `uv run pytest tests -k "debug_screenshot or debug_recording or debug_overlay" -q`
2. `uv run python ops/planning/agile/validate_milestone_task_links.py`

## Non-mac Explicit Stub Matrix
1. `windows`: unsupported in this phase; declares capture/overlay stub capabilities with explicit reason.
2. `linux`: unsupported in this phase; declares capture/overlay stub capabilities with explicit reason.

## Reopen Intent
Reopen `U-035` after macOS closeout to implement and verify Windows/Linux runtime adapters and parity tests.
