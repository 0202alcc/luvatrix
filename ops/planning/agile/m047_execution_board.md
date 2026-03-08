# P-047 Execution Board

Milestone: `P-047`  
Framework: `gateflow_v1`  
Branch: `codex/m-p-047-luvatrix-adoption-deprecation`

## Intake
- [ ] `T-4701` Add Luvatrix wrappers that call installed gateflow CLI
- [ ] `T-4702` Deprecate legacy endpoint script with migration notices
- [ ] `T-4703` Update AGENTS/docs/cheatsheet to standalone command paths
- [ ] `T-4704` Run full planning workflow dry-run in Luvatrix via standalone gateflow

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
- [x] `T-4700` [CLOSEOUT HARNESS] Define P-047 closeout metric + evidence harness

## Blocked
- [ ] None

## Evidence Commands
1. `PYTHONPATH=. uv run python ops/planning/agile/validate_milestone_task_links.py`
2. `PYTHONPATH=. uv run python ops/planning/api/validate_closeout_packet.py --milestone-id P-047`
3. `uvx --from ./gateflow gateflow --root /Users/aleccandidato/Projects/luvatrix validate all`
4. `uvx --from ./gateflow gateflow --root /Users/aleccandidato/Projects/luvatrix api GET /milestones/P-047`
