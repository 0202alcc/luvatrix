#!/usr/bin/env python3
"""Reopen a Done task when post-merge CI fails and record an incident backlog item."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path("ops/planning")
SCHEDULE_PATH = ROOT / "gantt/milestone_schedule.json"
TASKS_MASTER_PATH = ROOT / "agile/tasks_master.json"
BACKLOG_PATH = ROOT / "agile/backlog_misc.json"
GANTT_MD_PATH = ROOT / "gantt/milestones_gantt.md"
GANTT_PNG_PATH = ROOT / "gantt/milestones_gantt.png"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def current_git_branch() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def regenerate_gantt_artifacts() -> None:
    commands = [
        [
            "python",
            "ops/discord/scripts/generate_gantt_markdown.py",
            "--schedule",
            str(SCHEDULE_PATH),
            "--out",
            str(GANTT_MD_PATH),
        ],
        [
            "python",
            "ops/discord/scripts/generate_gantt_png.py",
            "--schedule",
            str(SCHEDULE_PATH),
            "--out",
            str(GANTT_PNG_PATH),
        ],
    ]
    for cmd in commands:
        subprocess.run(cmd, check=True, cwd=Path.cwd())


def next_backlog_id(backlog: dict[str, Any]) -> str:
    existing = []
    for item in backlog.get("items", []):
        bid = str(item.get("id", ""))
        if bid.startswith("B-"):
            try:
                existing.append(int(bid.split("-")[1]))
            except ValueError:
                continue
    n = (max(existing) + 1) if existing else 1
    return f"B-{n:03d}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Reopen task on CI failure and create incident backlog item.")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--check-id", required=True, help="CI check/run identifier")
    parser.add_argument("--summary", required=True, help="Short failure summary")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    schedule = load_json(SCHEDULE_PATH)
    tasks_master = load_json(TASKS_MASTER_PATH)
    backlog = load_json(BACKLOG_PATH)

    rows = {t["id"]: t for t in tasks_master.get("tasks", [])}
    if args.task_id not in rows:
        raise SystemExit(f"error: task not found: {args.task_id}")
    task = rows[args.task_id]
    old_status = task.get("status")
    if old_status != "Done":
        raise SystemExit(f"error: task {args.task_id} is not Done (current status={old_status})")

    task["status"] = "Verification Review"
    task["post_merge_failure"] = {
        "check_id": args.check_id,
        "summary": args.summary,
        "detected_on": dt.date.today().isoformat(),
    }
    actuals = task.get("actuals")
    if isinstance(actuals, dict):
        actuals["reopen_count"] = int(actuals.get("reopen_count", 0)) + 1

    milestone_id = task.get("milestone_id")
    milestones = {m["id"]: m for m in schedule.get("milestones", [])}
    milestone = milestones.get(milestone_id)
    if milestone and milestone.get("status") == "Complete":
        milestone["status"] = "In Progress"
        milestone.setdefault("lifecycle_events", []).append(
            {
                "date": dt.date.today().isoformat(),
                "event": "reopened",
                "framework": "gateflow_v1",
                "note": f"auto-reopened due to CI failure for task {args.task_id} ({args.check_id})",
            }
        )

    incident_id = next_backlog_id(backlog)
    incident = {
        "id": incident_id,
        "title": f"CI failure incident for {args.task_id}: {args.summary}",
        "status": "Open",
        "bucket": "Carryover",
        "source_milestone_id": milestone_id,
        "task_ref": args.task_id,
        "incident": {
            "check_id": args.check_id,
            "opened_on": dt.date.today().isoformat(),
            "owner": "control_tower",
            "sla": "24h",
        },
    }
    backlog.setdefault("items", []).append(incident)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"mode: {mode}")
    print(f"reopened task: {args.task_id} (Done -> Verification Review)")
    print(f"created backlog incident: {incident_id}")

    if not args.apply:
        print("write: skipped (use --apply)")
        return 0

    branch = current_git_branch()
    if branch != "main":
        print(f"error: --apply is restricted to main branch (current={branch})")
        return 2

    write_json(SCHEDULE_PATH, schedule)
    write_json(TASKS_MASTER_PATH, tasks_master)
    write_json(BACKLOG_PATH, backlog)
    regenerate_gantt_artifacts()
    print("write: ok")
    print(f"regenerated: {GANTT_MD_PATH}, {GANTT_PNG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
