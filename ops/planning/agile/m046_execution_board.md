# F-046 Execution Board

Milestone: `F-046`  
Framework: `gateflow_v1`  
Branch: `codex/m-f-046-import-luvatrix`

## Intake
- [ ] None

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
- [x] `T-4600` [CLOSEOUT HARNESS] Define F-046 closeout metric + evidence harness
- [x] `T-4601` Implement `gateflow import-luvatrix --path <repo>`
- [x] `T-4602` Map milestone/task/board/backlog/closeout semantics exactly
- [x] `T-4603` Validate post-import with `gateflow validate all`
- [x] `T-4604` Add deterministic drift report + explicit remediation output

## Blocked
- [ ] None

## Evidence Commands
1. `PYTHONPATH=. uv run python ops/planning/agile/validate_milestone_task_links.py`
2. `PYTHONPATH=. uv run python ops/planning/api/validate_closeout_packet.py --milestone-id F-046`
3. `PYTHONPATH=gateflow/src python3 -m pytest gateflow/tests -q`
4. `PYTHONPATH=gateflow/src python3 -m gateflow.cli import-luvatrix --path /Users/aleccandidato/Projects/luvatrix`
5. `PYTHONPATH=gateflow/src python3 -m gateflow.cli --root /Users/aleccandidato/Projects/luvatrix validate all`
