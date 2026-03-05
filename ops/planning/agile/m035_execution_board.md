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
1. Pending.

## Integration Ready
1. Pending.

## Done
1. Pending.
