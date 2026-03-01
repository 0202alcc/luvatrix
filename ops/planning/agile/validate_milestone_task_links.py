#!/usr/bin/env python3
"""Validate that every milestone task_id exists in tasks_master or archived tasks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate gantt milestone task links against active and archived task ledgers."
        )
    )
    parser.add_argument(
        "--schedule",
        default="ops/planning/gantt/milestone_schedule.json",
    )
    parser.add_argument(
        "--tasks-master",
        default="ops/planning/agile/tasks_master.json",
    )
    parser.add_argument(
        "--tasks-archived",
        default="ops/planning/agile/tasks_archived.json",
    )
    args = parser.parse_args()

    schedule = load_json(Path(args.schedule))
    tasks_master = load_json(Path(args.tasks_master))
    tasks_archived = load_json(Path(args.tasks_archived))

    active_ids = {task["id"] for task in tasks_master.get("tasks", [])}
    archived_ids = {task["id"] for task in tasks_archived.get("tasks", [])}
    known_ids = active_ids | archived_ids

    errors: list[str] = []

    for milestone in schedule.get("milestones", []):
        milestone_id = milestone.get("id", "<unknown>")
        task_ids = milestone.get("task_ids")
        if not isinstance(task_ids, list) or not task_ids:
            errors.append(f"{milestone_id}: missing non-empty task_ids list")
            continue

        for task_id in task_ids:
            if task_id not in known_ids:
                errors.append(
                    f"{milestone_id}: task_id '{task_id}' not found in tasks_master or tasks_archived"
                )
                continue

            if task_id in active_ids:
                task = next(
                    t for t in tasks_master.get("tasks", []) if t.get("id") == task_id
                )
                if task.get("milestone_id") != milestone_id:
                    errors.append(
                        f"{milestone_id}: task_id '{task_id}' belongs to milestone '{task.get('milestone_id')}' in tasks_master"
                    )
            elif task_id in archived_ids:
                task = next(
                    t for t in tasks_archived.get("tasks", []) if t.get("id") == task_id
                )
                if task.get("milestone_id") != milestone_id:
                    errors.append(
                        f"{milestone_id}: archived task_id '{task_id}' belongs to milestone '{task.get('milestone_id')}'"
                    )

    if errors:
        print("validation: FAIL")
        for err in errors:
            print(f"- {err}")
        return 1

    print("validation: PASS")
    print(
        f"checked {len(schedule.get('milestones', []))} milestones against "
        f"{len(active_ids)} active + {len(archived_ids)} archived tasks"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
