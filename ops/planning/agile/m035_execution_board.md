# U-035 Execution Board

Milestone: `U-035` Visual + Capture Tooling  
Scope lock: macOS-first only. Non-mac paths must be explicit stubs/capability-declared.  
Task chain: `T-2921 -> T-2904 -> T-2905 -> T-2906`

## Intake
1. None.

## Success Criteria Spec
1. `T-2921` Milestone closeout metric contract defined with macOS-context Go/No-Go threshold and explicit non-mac stub declaration requirements.

## Safety Tests Spec
1. `T-2921` Hard No-Go if capture lifecycle exceeds render budget envelope, metadata sidecars are incomplete, overlay toggles are destructive, or non-mac behavior is implicit/undefined.

## Implementation Tests Spec
1. `T-2921` `uv run pytest tests -k "debug_screenshot or debug_recording or debug_overlay" -q`
2. `T-2921` `uv run python ops/planning/agile/validate_milestone_task_links.py`

## Edge Case Tests Spec
1. `T-2921` Non-mac platform declarations must remain explicit stubs with unsupported reasons.
2. `T-2921` Capture artifacts must preserve deterministic metadata keys and atomic pairing semantics.

## Prototype Stage 1
1. `T-2921` Execution board + harness spec drafted and linked to milestone criteria.

## Prototype Stage 2+
1. `T-2921` Harness validated against screenshot, recording, and overlay task contract/test coverage.

## Verification Review
1. `T-2921` Harness evidence commands validated against implemented tests and planning validators.
2. `T-2904` Screenshot sidecar contract reviewed for deterministic required metadata keys and atomic artifact pairing.
3. `T-2905` Recording contract reviewed for lifecycle budget envelope evaluation behavior.
4. `T-2906` Overlay contract reviewed for bounds/dirty-rect validation and non-destructive toggle semantics.

## Integration Ready
1. `T-2921` Harness and execution board are aligned to milestone closeout criteria.
2. `T-2904` Screenshot contract APIs/tests/docs are merged to the milestone branch.
3. `T-2905` Recording contract APIs/tests/docs are merged to the milestone branch.
4. `T-2906` Overlay contract APIs/tests/docs are merged to the milestone branch.

## Done
1. `T-2921` Completed closeout harness definitions and linked U-035 command set in docs + execution board.
2. `T-2904` Completed screenshot metadata sidecar contract with deterministic keys and atomic artifact pairing checks.
3. `T-2905` Completed recording artifact manifest and lifecycle budget envelope contract with deterministic validation coverage.
4. `T-2906` Completed overlay bounds/dirty-rect/coordinate contract with non-destructive toggle semantics and explicit non-mac stubs.
