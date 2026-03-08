from __future__ import annotations

import json
from pathlib import Path

from ops.ci.verify_p013_gate_catalog import validate_catalog


def test_catalog_validates_current_file() -> None:
    payload = json.loads(Path("ops/ci/p013_gate_catalog.json").read_text(encoding="utf-8"))
    assert validate_catalog(payload) == []


def test_catalog_rejects_duplicate_gate_ids() -> None:
    payload = {
        "milestone_id": "P-013",
        "gates": [
            {
                "id": "x",
                "owner": "team:a",
                "required_command": "uvx --from gateflow==0.1.0a3 gateflow --root . validate links",
                "pass_criteria": "ok",
            },
            {
                "id": "x",
                "owner": "team:b",
                "required_command": "uvx --from gateflow==0.1.0a3 gateflow --root . validate closeout",
                "pass_criteria": "ok",
            },
        ],
        "escalation_path": ["a", "b"],
    }
    errors = validate_catalog(payload)
    assert any("duplicate gate id" in e for e in errors)
