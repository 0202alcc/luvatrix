# R-040 Execution Board

Milestone: `R-040`  
Name: `macOS Debug Menu Functionalization (Full Actions)`  
Framework: `gateflow_v1`

## Intake
- [x] `T-3300` [CLOSEOUT HARNESS] Define R-040 closeout metric + evidence contract
- [x] `T-3301` Implement real screenshot action pipeline
- [x] `T-3302` Implement real recording start/stop pipeline
- [x] `T-3303` Implement overlay runtime toggles (bounds/dirty-rect/coordinates)
- [x] `T-3304` Implement replay start action (seed/session-based)
- [x] `T-3305` Implement frame-step action + paused-state controls
- [x] `T-3306` Implement perf HUD toggle + runtime metric surface
- [x] `T-3307` Implement debug bundle export action (captures/replay/perf/provenance)
- [x] `T-3308` Integrate menu action-state updates (enabled/disabled reflects runtime state)
- [x] `T-3309` E2E macOS example-app menu functional smoke harness
- [x] `T-3310` Rollback/kill-switch hardening + final closeout packet

## Success Criteria Spec
- [x] No menu action remains stubbed on macOS for supported policy.

## Safety Tests Spec
- [x] No action dispatch can crash process; handler exceptions degrade to warning/noop.

## Implementation Tests Spec
- [x] Debug action functional pytest selection passes.

## Edge Case Tests Spec
- [x] Rollback and policy-disabled paths return deterministic `DISABLED`.

## Prototype Stage 1
- [x] Runtime handler wiring merged.

## Prototype Stage 2+
- [x] Action-state synchronization + functional smoke harness merged.

## Verification Review
- [x] Required command bundle executed with artifact evidence.

## Integration Ready
- [x] Milestone branch includes all task merges and closeout packet.

## Done
- [ ] Milestone PR merged to `main` with required checks passing (pending).

## Blocked
- [ ] None.
