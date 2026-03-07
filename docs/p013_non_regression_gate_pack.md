# P-013 Non-Regression Gate Pack

## Objective

`T-2911` consolidates CI non-regression gates under P-013, including explicit P-026 evidence checks.

## Runner

- Script: `ops/ci/p013_non_regression_gate.py`
- Output: `artifacts/p013/non_regression_gate_summary.json`

## Commands in Pack

1. `uv run --with pytest pytest tests -k "debug_manifest or legacy_debug_conformance" -q`
2. `uv run python ops/planning/api/validate_closeout_evidence.py --milestone-id P-026`
3. `uv run python ops/planning/agile/validate_milestone_task_links.py`

## Verification

Dry run:

```bash
PYTHONPATH=. uv run python ops/ci/p013_non_regression_gate.py
```

Execute full pack:

```bash
PYTHONPATH=. uv run python ops/ci/p013_non_regression_gate.py --execute
```
