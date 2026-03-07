# P-013 Flaky Quarantine Workflow

## Objective

`T-402` introduces a deterministic quarantine policy so flaky tests are tracked, time-bounded, and tied to remediation owners.

## Source of Truth

- Manifest: `ops/ci/flaky_quarantine_manifest.json`
- Validator: `ops/ci/flaky_quarantine.py`

## Required Fields Per Entry

1. `test_id`
2. `reason`
3. `owner`
4. `ticket_id`
5. `quarantined_on`
6. `expires_on`
7. `remediation_status`

## Governance Rules

1. `owner` must be a team tag (`team:*`).
2. `ticket_id` must map to a remediation task (`T-*`).
3. Quarantine age must not exceed configured max days.
4. Expired entries must be `verified` or the gate fails.

## Verification Command

```bash
PYTHONPATH=. uv run python ops/ci/flaky_quarantine.py --manifest ops/ci/flaky_quarantine_manifest.json --max-quarantine-days 14
```
