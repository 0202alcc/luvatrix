from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from ops.ci.flaky_quarantine import validate_manifest


def test_manifest_file_is_valid() -> None:
    payload = json.loads(Path("ops/ci/flaky_quarantine_manifest.json").read_text(encoding="utf-8"))
    errors = validate_manifest(payload, max_quarantine_days=14, today=dt.date(2026, 3, 7))
    assert errors == []


def test_rejects_stale_quarantine_entry() -> None:
    payload = {
        "milestone_id": "P-013",
        "entries": [
            {
                "test_id": "tests/test_example.py::test_flaky",
                "reason": "intermittent timeout",
                "owner": "team:platform-ci",
                "ticket_id": "T-402",
                "quarantined_on": "2026-02-01",
                "expires_on": "2026-03-01",
                "remediation_status": "open",
            }
        ],
    }
    errors = validate_manifest(payload, max_quarantine_days=14, today=dt.date(2026, 3, 7))
    assert any("exceeds max quarantine age" in e for e in errors)
    assert any("expired without verified remediation" in e for e in errors)
