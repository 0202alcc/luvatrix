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
    closeout_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "milestones": self.milestone_count,
            "tasks": self.task_count,
            "boards": self.board_count,
            "backlog_items": self.backlog_count,
            "closeout_packets": self.closeout_count,
        }


def import_luvatrix(path: Path) -> ImportResult:
    root = path.resolve()
    scaffold_workspace(root=root, profile="minimal")
    stamped = date.today().isoformat()

    milestones_payload = read_json(root / "ops" / "planning" / "gantt" / "milestone_schedule.json")
    tasks_payload = read_json(root / "ops" / "planning" / "agile" / "tasks_master.json")
    archived_tasks_payload = read_json(root / "ops" / "planning" / "agile" / "tasks_archived.json")
    boards_payload = read_json(root / "ops" / "planning" / "agile" / "boards_registry.json")
    backlog_payload = read_json(root / "ops" / "planning" / "agile" / "backlog_misc.json")

    milestones = list(milestones_payload.get("milestones", []))
    tasks = _merge_tasks(
        active=list(tasks_payload.get("tasks", [])),
        archived=list(archived_tasks_payload.get("tasks", [])),
    )
    boards = list(boards_payload.get("boards", []))
    backlog_items = list(backlog_payload.get("items", []))
    closeout_count = _copy_closeout_packets(root)

    gateflow_dir = root / ".gateflow"
    write_json(
        gateflow_dir / "milestones.json",
        {
            "items": milestones,
            "title": milestones_payload.get("title"),
            "baseline_start_date": milestones_payload.get("baseline_start_date"),
            "milestone_id_schema": milestones_payload.get("milestone_id_schema"),
            "updated_at": stamped,
            "version": "gateflow_v1",
        },
    )
    write_json(
        gateflow_dir / "tasks.json",
        {
            "items": tasks,
            "schema_version": tasks_payload.get("schema_version"),
            "status_values": tasks_payload.get("status_values"),
            "legacy_status_values": tasks_payload.get("legacy_status_values"),
            "updated_at": stamped,
            "version": "gateflow_v1",
        },
    )
    write_json(
        gateflow_dir / "boards.json",
        {
            "items": boards,
            "schema_version": boards_payload.get("schema_version"),
            "default_framework_template": boards_payload.get("default_framework_template"),
            "framework_templates": boards_payload.get("framework_templates"),
            "render_defaults": boards_payload.get("render_defaults"),
            "board_types": boards_payload.get("board_types"),
            "updated_at": stamped,
            "version": "gateflow_v1",
        },
    )
    write_json(
        gateflow_dir / "backlog.json",
        {
            "items": backlog_items,
            "schema_version": backlog_payload.get("schema_version"),
            "status_values": backlog_payload.get("status_values"),
            "bucket_values": backlog_payload.get("bucket_values"),
            "updated_at": stamped,
            "version": "gateflow_v1",
        },
    )

    config_path = gateflow_dir / "config.json"
    config = read_json(config_path)
    frameworks = []
    for name in sorted((boards_payload.get("framework_templates") or {}).keys()):
        template = dict((boards_payload.get("framework_templates") or {}).get(name) or {})
        template["name"] = name
        frameworks.append(template)
    config["updated_at"] = stamped
    config["source"] = {
        "kind": "luvatrix_ops_planning",
        "path": str(root / "ops" / "planning"),
    }
    config["defaults"] = {
        "framework": str(boards_payload.get("default_framework_template", "gateflow_v1")),
        "warning_mode": str(config.get("defaults", {}).get("warning_mode", "warn")),
    }
    config["frameworks"] = frameworks
    config["render_defaults"] = boards_payload.get("render_defaults", {})
    config["board_types"] = boards_payload.get("board_types", {})
    write_json(config_path, config)

    return ImportResult(
        root=root,
        milestone_count=len(milestones),
        task_count=len(tasks),
        board_count=len(boards),
        backlog_count=len(backlog_items),
        closeout_count=closeout_count,
    )


def _merge_tasks(*, active: list[dict[str, Any]], archived: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for task in archived:
        task_id = str(task.get("id", "")).strip()
        if task_id:
            merged[task_id] = dict(task)
    for task in active:
        task_id = str(task.get("id", "")).strip()
        if task_id:
            merged[task_id] = dict(task)
    return [merged[key] for key in sorted(merged.keys())]


def _copy_closeout_packets(root: Path) -> int:
    src_dir = root / "ops" / "planning" / "closeout"
    dst_dir = root / ".gateflow" / "closeout"
    dst_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    if not src_dir.exists():
        return count
    for path in sorted(src_dir.glob("*_closeout.md")):
        dst_path = dst_dir / path.name
        dst_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        count += 1
    return count
