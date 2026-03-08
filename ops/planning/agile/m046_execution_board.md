# F-046 Execution Board

Milestone: `F-046`  
Framework: `gateflow_v1`  
Branch: `codex/m-f-046-import-luvatrix`

## Intake
- [x] `T-4600` [CLOSEOUT HARNESS] Define F-046 closeout metric + evidence harness
- [ ] `T-4601` Implement `gateflow import-luvatrix --path <repo>`
- [ ] `T-4602` Map milestone/task/board/backlog/closeout semantics exactly
- [ ] `T-4603` Validate post-import with `gateflow validate all`
- [ ] `T-4604` Add deterministic drift report + explicit remediation output

## Success Criteria Spec
- [ ] None

## Safety Tests Spec
- [ ] None

## Implementation Tests Spec
- [ ] None

## Edge Case Tests Spec
- [ ] None

## Prototype Stage 1
- [ ] None

## Prototype Stage 2+
- [ ] None

## Verification Review
- [ ] None

## Integration Ready
- [ ] None

## Done
- [ ] None

## Blocked
- [ ] None

## Evidence Commands
1. `PYTHONPATH=. uv run python ops/planning/agile/validate_milestone_task_links.py`
2. `PYTHONPATH=. uv run python ops/planning/api/validate_closeout_packet.py --milestone-id F-046`
3. `PYTHONPATH=gateflow/src python3 -m pytest gateflow/tests -q`
