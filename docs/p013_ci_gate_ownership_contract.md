# P-013 CI Gate Ownership Contract

## Objective

Define deterministic ownership and pass criteria for milestone `P-013` CI gates so task and milestone closeout evidence is reproducible.

## Source of Truth

- Gate catalog: `ops/ci/p013_gate_catalog.json`
- Validator: `ops/ci/verify_p013_gate_catalog.py`

## Required Gates

1. `gateflow-links` owned by `team:platform-ci`
2. `closeout-packet` owned by `team:release`
3. `non-regression-p026` owned by `team:platform-ci`

Each gate must declare a required command and explicit pass criteria string.

## Escalation

If any gate fails, follow `escalation_path` from the catalog and do not advance a task past `Verification Review` until remediation evidence is linked.

## Verification Command

```bash
PYTHONPATH=. uv run python ops/ci/verify_p013_gate_catalog.py
```
