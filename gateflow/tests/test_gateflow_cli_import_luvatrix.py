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
        },
    )
    _write_json(
        root / "ops" / "planning" / "agile" / "boards_registry.json",
        {
            "boards": [{"id": "milestone:F-046", "type": "milestone", "source_filter": {"milestone_id": "F-046"}}],
        },
    )
    _write_json(
        root / "ops" / "planning" / "agile" / "backlog_misc.json",
        {
            "items": [{"id": "B-1", "title": "carryover"}],
        },
    )


def test_import_luvatrix_creates_gateflow_ledgers(tmp_path: Path) -> None:
    _seed_luvatrix_ops(tmp_path)

    assert main(["import-luvatrix", "--path", str(tmp_path)]) == 0
    gateflow = tmp_path / ".gateflow"
    milestones = json.loads((gateflow / "milestones.json").read_text(encoding="utf-8"))
    tasks = json.loads((gateflow / "tasks.json").read_text(encoding="utf-8"))
    boards = json.loads((gateflow / "boards.json").read_text(encoding="utf-8"))
    backlog = json.loads((gateflow / "backlog.json").read_text(encoding="utf-8"))

    assert [row["id"] for row in milestones["items"]] == ["F-046"]
    assert [row["id"] for row in tasks["items"]] == ["T-4601"]
    assert [row["id"] for row in boards["items"]] == ["milestone:F-046"]
    assert [row["id"] for row in backlog["items"]] == ["B-1"]
