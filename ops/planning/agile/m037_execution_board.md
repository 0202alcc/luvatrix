# A-037 Execution Board

Milestone: `A-037` App-Configurable Debug Policy + Compatibility  
Scope lock: macOS-first only. Non-mac paths must be explicit stubs/capability-declared.  
Task chain: `T-2923 -> T-2910`

## Intake
1. None.

## Success Criteria Spec
1. `T-2923` Closeout harness defines a macOS-context Go/No-Go metric for manifest debug policy compatibility.

## Safety Tests Spec
1. `T-2923` Hard No-Go if legacy app behavior regresses, debug fallback can be removed without explicit policy approval, P-026 evidence fails, or non-mac behavior is implicit/undefined.

## Implementation Tests Spec
1. `T-2923` `uv run pytest tests -k "debug_manifest or legacy_debug_conformance" -q`
2. `T-2923` `uv run python ops/planning/api/validate_closeout_evidence.py --milestone-id P-026`
3. `T-2923` `uv run python ops/planning/agile/validate_milestone_task_links.py`

## Edge Case Tests Spec
1. `T-2923` Manifest debug policy must default to compatibility-safe behavior when policy block is absent.
2. `T-2923` Non-mac policy behavior must remain explicit capability stubs with unsupported reasons.

## Prototype Stage 1
1. `T-2923` Execution board and closeout harness packet skeleton created for A-037.

## Prototype Stage 2+
1. `T-2910` App manifest debug policy parser and validation rules implemented with macOS-first non-mac stub declarations.
2. `T-2910` Legacy compatibility tests and debug manifest policy tests implemented.

## Verification Review
1. `T-2910` Manifest debug policy defaults verified to preserve existing app behavior in macOS scope.
2. `T-2910` Manifest policy schema/version checks verified by targeted unit tests.
3. `T-2910` Explicit non-mac stub/capability declaration behavior verified by tests/docs.

## Integration Ready
1. `T-2923` Harness/evidence contract aligns with milestone closeout criteria and required checks.
2. `T-2910` Runtime manifest policy code, tests, and docs are ready for milestone integration.

## Done
1. `T-2923` Completed closeout harness definitions and A-037 command/evidence contract.
2. `T-2910` Completed app manifest debug policy + backward compatibility path with macOS-first explicit non-mac stubs.
