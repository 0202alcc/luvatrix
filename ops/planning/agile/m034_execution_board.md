# F-034 Execution Board

Milestone: `F-034` Cross-Platform Debug Menu Foundation  
Scope lock: macOS-first only. Non-mac paths must be explicit stubs/capability-declared.  
Task chain: `T-2920 -> T-2901 -> T-2902 -> T-2903`

## Intake
1. `T-2920` [CLOSEOUT HARNESS] Define debug menu foundation closeout metric and evidence harness.
2. `T-2901` Menu crash hardening + safe dispatch contract.
3. `T-2902` Debug capability registry + menu ID standard.
4. `T-2903` Cross-platform menu adapter spec (macOS/Windows/Linux).

## Success Criteria Spec
1. `T-2920` Milestone closeout metric contract defined with macOS-context Go/No-Go threshold and explicit non-mac stub declaration requirements.

## Safety Tests Spec
1. `T-2920` Hard No-Go if any menu action can crash process or non-mac behavior is implicit/undefined.

## Implementation Tests Spec
1. `T-2920` `uv run pytest tests -k "debug_menu_dispatch or debug_capabilities or debug_menu_adapter" -q`
2. `T-2920` `uv run python ops/planning/agile/validate_milestone_task_links.py`

## Edge Case Tests Spec
1. `T-2920` Unknown menu action must degrade to deterministic no-op + warning.
2. `T-2920` Unknown platform adapter must return explicit unsupported capability declarations.

## Prototype Stage 1
1. `T-2920` Execution board + harness spec drafted and linked to milestone criteria.

## Prototype Stage 2+
1. `T-2920` Harness validated against implemented task/test command set.

## Verification Review
1. Pending.

## Integration Ready
1. Pending.

## Done
1. Pending.
