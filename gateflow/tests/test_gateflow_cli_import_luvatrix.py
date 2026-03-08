from __future__ import annotations

import json
from pathlib import Path

from gateflow.cli import main


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _seed_luvatrix_ops(root: Path) -> None:
    _write_json(
        root / "ops" / "planning" / "gantt" / "milestone_schedule.json",
        {
            "milestones": [{"id": "F-046", "task_ids": ["T-4601"], "name": "Migration Tooling"}],
        },
    )
    _write_json(
        root / "ops" / "planning" / "agile" / "tasks_master.json",
        {
            "tasks": [{"id": "T-4601", "milestone_id": "F-046", "depends_on": []}],
            "status_values": ["Intake", "Done"],
            "legacy_status_values": ["Backlog"],
            "schema_version": "1.0.0",
        },
    )
    _write_json(
        root / "ops" / "planning" / "agile" / "tasks_archived.json",
        {
            "tasks": [{"id": "A-H001-01", "milestone_id": "F-001", "status": "Archived"}],
            "schema_version": "1.0.0",
        },
    )
    _write_json(
        root / "ops" / "planning" / "agile" / "boards_registry.json",
        {
            "schema_version": "1.0.0",
            "default_framework_template": "gateflow_v1",
            "framework_templates": {"gateflow_v1": {"description": "GateFlow"}},
            "render_defaults": {"status_columns": ["Intake", "Done"]},
            "board_types": {"milestone": {"default_swimlane": "specialist"}},
            "boards": [{"id": "milestone:F-046", "type": "milestone", "source_filter": {"milestone_id": "F-046"}}],
        },
    )
    _write_json(
        root / "ops" / "planning" / "agile" / "backlog_misc.json",
        {
            "items": [{"id": "B-1", "title": "carryover"}],
            "schema_version": "1.0.0",
            "status_values": ["Open"],
            "bucket_values": ["Carryover"],
        },
    )
    (root / "ops" / "planning" / "closeout").mkdir(parents=True, exist_ok=True)
    (root / "ops" / "planning" / "closeout" / "f-046_closeout.md").write_text("# Objective Summary\n", encoding="utf-8")


def test_import_luvatrix_creates_gateflow_ledgers(tmp_path: Path) -> None:
    _seed_luvatrix_ops(tmp_path)

    assert main(["import-luvatrix", "--path", str(tmp_path)]) == 0
    gateflow = tmp_path / ".gateflow"
    milestones = json.loads((gateflow / "milestones.json").read_text(encoding="utf-8"))
    tasks = json.loads((gateflow / "tasks.json").read_text(encoding="utf-8"))
    boards = json.loads((gateflow / "boards.json").read_text(encoding="utf-8"))
    backlog = json.loads((gateflow / "backlog.json").read_text(encoding="utf-8"))
    config = json.loads((gateflow / "config.json").read_text(encoding="utf-8"))

    assert [row["id"] for row in milestones["items"]] == ["F-046"]
    assert [row["id"] for row in tasks["items"]] == ["A-H001-01", "T-4601"]
    assert [row["id"] for row in boards["items"]] == ["milestone:F-046"]
    assert [row["id"] for row in backlog["items"]] == ["B-1"]
    assert [row["name"] for row in config["frameworks"]] == ["gateflow_v1"]
    assert (gateflow / "closeout" / "f-046_closeout.md").exists()


def test_import_luvatrix_generates_missing_closeout_and_validate_all_passes(tmp_path: Path, capsys) -> None:
    _seed_luvatrix_ops(tmp_path)
    _write_json(
        tmp_path / "ops" / "planning" / "gantt" / "milestone_schedule.json",
        {
            "milestones": [
                {
                    "id": "F-046",
                    "task_ids": ["T-4601"],
                    "status": "Planned",
                    "closeout_criteria": {"metric_id": "f-046-closeout-v1"},
                }
            ],
        },
    )
    # Remove source closeout to force placeholder generation.
    (tmp_path / "ops" / "planning" / "closeout" / "f-046_closeout.md").unlink()

    assert main(["import-luvatrix", "--path", str(tmp_path)]) == 0
    _ = capsys.readouterr()
    assert main(["--root", str(tmp_path), "validate", "all"]) == 0
    assert "validation: PASS (all)" in capsys.readouterr().out


def test_import_luvatrix_check_mode_reports_drift_with_remediation(tmp_path: Path, capsys) -> None:
    _seed_luvatrix_ops(tmp_path)

    rc = main(["import-luvatrix", "--path", str(tmp_path), "--check"])
    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "drifted"
    assert payload["mismatch_count"] > 0
    assert payload["mismatches"][0]["remediation"].startswith("Run `gateflow import-luvatrix --path <repo>`")


def test_import_luvatrix_check_mode_is_clean_after_import(tmp_path: Path, capsys) -> None:
    _seed_luvatrix_ops(tmp_path)
    assert main(["import-luvatrix", "--path", str(tmp_path)]) == 0
    _ = capsys.readouterr()

    rc = main(["import-luvatrix", "--path", str(tmp_path), "--check"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "clean"
    assert payload["mismatch_count"] == 0
