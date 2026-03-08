from __future__ import annotations

import json
from pathlib import Path

from gateflow.cli import main


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _seed(root: Path) -> None:
    assert main(["--root", str(root), "init", "scaffold", "--profile", "minimal"]) == 0


def test_validate_links_passes_for_consistent_references(tmp_path: Path, capsys) -> None:
    _seed(tmp_path)
    gateflow = tmp_path / ".gateflow"
    _write_json(
        gateflow / "milestones.json",
        {"items": [{"id": "P-044", "task_ids": ["T-4400"]}], "updated_at": "2026-03-07", "version": "gateflow_v1"},
    )
    _write_json(
        gateflow / "tasks.json",
        {
            "items": [{"id": "T-4400", "milestone_id": "P-044", "depends_on": []}],
            "updated_at": "2026-03-07",
            "version": "gateflow_v1",
        },
    )

    assert main(["--root", str(tmp_path), "validate", "links"]) == 0
    assert "validation: PASS (links)" in capsys.readouterr().out


def test_validate_links_fails_when_milestone_task_missing(tmp_path: Path, capsys) -> None:
    _seed(tmp_path)
    _ = capsys.readouterr()
    gateflow = tmp_path / ".gateflow"
    _write_json(
        gateflow / "milestones.json",
        {"items": [{"id": "P-044", "task_ids": ["T-4400"]}], "updated_at": "2026-03-07", "version": "gateflow_v1"},
    )
    _write_json(gateflow / "tasks.json", {"items": [], "updated_at": "2026-03-07", "version": "gateflow_v1"})

    assert main(["--root", str(tmp_path), "--json-errors", "validate", "links"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_type"] == "validation"
    assert payload["exit_code"] == 2
    assert any("missing task T-4400" in item for item in payload["errors"])


def test_validate_closeout_passes_for_required_sections(tmp_path: Path, capsys) -> None:
    _seed(tmp_path)
    gateflow = tmp_path / ".gateflow"
    _write_json(
        gateflow / "milestones.json",
        {
            "items": [{"id": "P-044", "status": "Complete"}],
            "updated_at": "2026-03-07",
            "version": "gateflow_v1",
        },
    )
    packet = gateflow / "closeout" / "p-044_closeout.md"
    packet.write_text(
        "\n".join(
            [
                "# Objective Summary",
                "# Task Final States",
                "# Evidence",
                "# Determinism",
                "# Protocol Compatibility",
                "# Modularity",
                "# Residual Risks",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert main(["--root", str(tmp_path), "validate", "closeout"]) == 0
    assert "validation: PASS (closeout)" in capsys.readouterr().out


def test_validate_all_aggregates_links_and_closeout(tmp_path: Path, capsys) -> None:
    _seed(tmp_path)
    _ = capsys.readouterr()
    gateflow = tmp_path / ".gateflow"
    _write_json(
        gateflow / "milestones.json",
        {
            "items": [{"id": "P-044", "status": "Complete", "task_ids": ["T-4400"]}],
            "updated_at": "2026-03-07",
            "version": "gateflow_v1",
        },
    )
    _write_json(
        gateflow / "tasks.json",
        {
            "items": [{"id": "T-4400", "milestone_id": "P-044", "depends_on": []}],
            "updated_at": "2026-03-07",
            "version": "gateflow_v1",
        },
    )
    # Missing packet should fail closeout lane in validate all.
    assert main(["--root", str(tmp_path), "--json-errors", "validate", "all"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_type"] == "validation"
    assert payload["exit_code"] == 2
    assert any("missing closeout packet" in item for item in payload["errors"])
