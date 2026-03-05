# Debug Menu Foundation Harness (F-034 / T-2920)

## Objective
Define the closeout metric and evidence harness for the macOS-first debug menu foundation milestone.

## Phase Policy
1. This phase is macOS-only for Go/No-Go.
2. Windows/Linux behavior must be explicit stub/capability-declared.
3. Implicit behavior on non-mac platforms is disallowed.
4. Milestone may close in macOS context with reopen intent for cross-platform expansion.

## Closeout Metric Contract
1. Metric ID: `f-034-closeout-v1`
2. Formula: `0.4*menu_safety + 0.3*capability_standardization + 0.3*adapter_parity`
3. Go threshold: `88`

## Hard No-Go Conditions
1. Any menu action can crash app process.
2. Capability IDs are ambiguous or overlap semantically.
3. Adapter contract lacks parity guarantees for supported semantics.
4. Non-mac behavior is undefined instead of explicit stub/capability declaration.

## Required Evidence
1. Dispatch safety tests proving crash-proof behavior with deterministic fallback outcomes.
2. Capability registry tests proving canonical ID and one-action mapping.
3. Adapter conformance tests proving explicit macOS behavior and explicit non-mac stubs.
4. Milestone closeout packet documenting macOS-context decision and reopen plan for platform expansion.

## Required Commands
1. `uv run pytest tests -k "debug_menu_dispatch or debug_capabilities or debug_menu_adapter" -q`
2. `uv run python ops/planning/agile/validate_milestone_task_links.py`
3. `uv run python ops/planning/api/validate_closeout_packet.py --milestone-id F-034`
