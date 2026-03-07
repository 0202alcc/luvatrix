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
                "required_command": "uv run python a.py",
                "pass_criteria": "ok",
            },
            {
                "id": "x",
                "owner": "team:b",
                "required_command": "uv run python b.py",
                "pass_criteria": "ok",
            },
        ],
        "escalation_path": ["a", "b"],
    }
    errors = validate_catalog(payload)
    assert any("duplicate gate id" in e for e in errors)
