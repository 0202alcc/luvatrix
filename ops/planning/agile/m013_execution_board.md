# P-013 Execution Board

Milestone: `P-013` CI hardening, flaky governance, and non-regression gate packs  
Task chain: `T-401 -> (T-402, T-403) -> T-2911`

## Intake
1. None.

## Success Criteria Spec
1. `T-401` Deterministic gate ownership catalog and pass-criteria contract are defined for P-013 required checks.

## Safety Tests Spec
1. `T-401` Gate catalog must enforce explicit owner, command, and pass criteria fields with deterministic validation output.

## Implementation Tests Spec
1. `T-401` `PYTHONPATH=. uv run --with pytest pytest tests/test_p013_gate_catalog.py -q`
2. `T-401` `PYTHONPATH=. uv run python ops/ci/verify_p013_gate_catalog.py`

## Edge Case Tests Spec
1. `T-401` Duplicate gate identifiers must fail validation.
2. `T-401` Missing escalation path must fail validation.

## Prototype Stage 1
1. `T-401` Added `ops/ci/p013_gate_catalog.json` and validator script to codify gate ownership.

## Prototype Stage 2+
1. `T-402` Added flaky quarantine manifest contract and deterministic validator (`ops/ci/flaky_quarantine.py`).

## Verification Review
1. `T-402` `PYTHONPATH=. uv run --with pytest pytest tests/test_flaky_quarantine.py -q`
2. `T-402` `PYTHONPATH=. uv run python ops/ci/flaky_quarantine.py --manifest ops/ci/flaky_quarantine_manifest.json --max-quarantine-days 14`
3. `T-403` `PYTHONPATH=. uv run --with pytest pytest tests/test_render_ci_smoke_summary.py -q`

## Integration Ready
1. `T-402` Flaky quarantine governance artifacts are ready for milestone integration.
2. `T-403` Smoke signal workflow and artifact summary publishing are ready for milestone integration.

## Done
1. `T-401` Completed deterministic gate ownership contract and validator with test coverage.
2. `T-402` Completed flaky quarantine manifest, validator, and remediation policy docs.
3. `T-403` Completed smoke signal summary workflow and artifact-link publishing.
4. `T-2911` Completed non-regression gate-pack runner + CI workflow, including P-026 evidence enforcement.
