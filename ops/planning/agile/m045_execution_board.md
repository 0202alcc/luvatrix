# F-045 Execution Board

Milestone: `F-045`  
Framework: `gateflow_v1`  
Branch: `codex/m-f-045-gateflow-repo-extraction`

## Intake
- [ ] `T-4500` [CLOSEOUT HARNESS] Define F-045 closeout metric + evidence harness
- [ ] `T-4501` Create standalone `gateflow` repo skeleton/package
- [ ] `T-4502` Move refactored modules + CLI entrypoint into standalone repo
- [ ] `T-4503` Add packaging/install path (`uvx gateflow`, future `pipx`)
- [ ] `T-4504` Port test fixtures and integration suites to standalone repo
- [ ] `T-4505` Publish pre-release tag + install documentation

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
2. `PYTHONPATH=. uv run python ops/planning/api/validate_closeout_packet.py --milestone-id F-045`
