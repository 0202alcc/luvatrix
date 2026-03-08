from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from gateflow.io import read_json, write_json
from gateflow.scaffold import scaffold_workspace


@dataclass(frozen=True)
class ImportResult:
    root: Path
    milestone_count: int
    task_count: int
    board_count: int
    backlog_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "milestones": self.milestone_count,
            "tasks": self.task_count,
            "boards": self.board_count,
            "backlog_items": self.backlog_count,
        }


def import_luvatrix(path: Path) -> ImportResult:
    root = path.resolve()
    scaffold_workspace(root=root, profile="minimal")
    stamped = date.today().isoformat()

    milestones_payload = read_json(root / "ops" / "planning" / "gantt" / "milestone_schedule.json")
    tasks_payload = read_json(root / "ops" / "planning" / "agile" / "tasks_master.json")
    boards_payload = read_json(root / "ops" / "planning" / "agile" / "boards_registry.json")
    backlog_payload = read_json(root / "ops" / "planning" / "agile" / "backlog_misc.json")

    milestones = list(milestones_payload.get("milestones", []))
    tasks = list(tasks_payload.get("tasks", []))
    boards = list(boards_payload.get("boards", []))
    backlog_items = list(backlog_payload.get("items", []))

    gateflow_dir = root / ".gateflow"
    write_json(
        gateflow_dir / "milestones.json",
        {
            "items": milestones,
            "updated_at": stamped,
            "version": "gateflow_v1",
        },
    )
    write_json(
        gateflow_dir / "tasks.json",
        {
            "items": tasks,
            "updated_at": stamped,
            "version": "gateflow_v1",
        },
    )
    write_json(
        gateflow_dir / "boards.json",
        {
            "items": boards,
            "updated_at": stamped,
            "version": "gateflow_v1",
        },
    )
    write_json(
        gateflow_dir / "backlog.json",
        {
            "items": backlog_items,
            "updated_at": stamped,
            "version": "gateflow_v1",
        },
    )

    config_path = gateflow_dir / "config.json"
    config = read_json(config_path)
    config["updated_at"] = stamped
    config["source"] = {
        "kind": "luvatrix_ops_planning",
        "path": str(root / "ops" / "planning"),
    }
    write_json(config_path, config)

    return ImportResult(
        root=root,
        milestone_count=len(milestones),
        task_count=len(tasks),
        board_count=len(boards),
        backlog_count=len(backlog_items),
    )
