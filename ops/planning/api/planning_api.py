#!/usr/bin/env python3
"""Endpoint-style planning data mutator for milestones and tasks.

Examples:
  python ops/planning/api/planning_api.py POST /milestones --body '{"id":"M-012",...}'
  python ops/planning/api/planning_api.py PATCH /tasks/T-1201 --body '{"status":"In Progress"}' --apply
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path("ops/planning")
SCHEDULE_PATH = ROOT / "gantt/milestone_schedule.json"
TASKS_MASTER_PATH = ROOT / "agile/tasks_master.json"
TASKS_ARCHIVED_PATH = ROOT / "agile/tasks_archived.json"
BOARDS_PATH = ROOT / "agile/boards_registry.json"
GANTT_MD_PATH = ROOT / "gantt/milestones_gantt.md"
GANTT_PNG_PATH = ROOT / "gantt/milestones_gantt.png"
GANTT_DETAILED_MD_PATH = ROOT / "gantt/milestones_gantt_detailed.md"

METHODS = {"GET", "POST", "PATCH", "DELETE"}
ALLOWED_MILESTONE_STATUS = {"Planned", "In Progress", "Complete", "Blocked"}
ALLOWED_TASK_STATUS = {"Backlog", "Ready", "In Progress", "Review", "Done", "Blocked"}
MILESTONE_ID_RE = re.compile(r"^[HM]-\d{3}$")
TASK_ID_RE = re.compile(r"^(T|A-H)\-\d{3,4}(?:-\d{2})?$")


class ApiError(RuntimeError):
    pass


def regenerate_gantt_artifacts() -> None:
    commands = [
        [
            sys.executable,
            "ops/discord/scripts/generate_gantt_markdown.py",
            "--schedule",
            str(SCHEDULE_PATH),
            "--out",
            str(GANTT_MD_PATH),
        ],
        [
            sys.executable,
            "ops/discord/scripts/generate_gantt_png.py",
            "--schedule",
            str(SCHEDULE_PATH),
            "--out",
            str(GANTT_PNG_PATH),
        ],
        [
            sys.executable,
            "ops/discord/scripts/generate_gantt_ascii_detailed.py",
            "--schedule",
            str(SCHEDULE_PATH),
            "--out",
            str(GANTT_DETAILED_MD_PATH),
        ],
    ]
    for cmd in commands:
        subprocess.run(cmd, check=True, cwd=Path.cwd())


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def parse_body(args: argparse.Namespace) -> dict[str, Any]:
    if args.body and args.body_file:
        raise ApiError("pass either --body or --body-file, not both")
    if args.body:
        return json.loads(args.body)
    if args.body_file:
        return json.loads(Path(args.body_file).read_text(encoding="utf-8"))
    return {}


def index_by_id(rows: list[dict[str, Any]], key: str = "id") -> dict[str, dict[str, Any]]:
    return {row[key]: row for row in rows}


def split_path(path: str) -> tuple[str, str | None]:
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        raise ApiError("path must not be empty")
    if parts[0] not in {"milestones", "tasks"}:
        raise ApiError("path must start with /milestones or /tasks")
    ident = parts[1] if len(parts) > 1 else None
    if len(parts) > 2:
        raise ApiError("path supports at most one identifier segment")
    return parts[0], ident


def validate_board_refs(task: dict[str, Any], board_ids: set[str]) -> None:
    refs = task.get("board_refs", [])
    if not isinstance(refs, list):
        raise ApiError(f"task {task.get('id')} board_refs must be a list")
    for ref in refs:
        if ref not in board_ids:
            raise ApiError(f"task {task.get('id')} references unknown board_ref '{ref}'")


def validate_milestone_task_links(
    schedule: dict[str, Any], tasks_master: dict[str, Any], tasks_archived: dict[str, Any]
) -> None:
    active = index_by_id(tasks_master.get("tasks", []))
    archived = index_by_id(tasks_archived.get("tasks", []))

    for milestone in schedule.get("milestones", []):
        mid = milestone.get("id", "<unknown>")
        task_ids = milestone.get("task_ids")
        if not isinstance(task_ids, list) or not task_ids:
            raise ApiError(f"{mid}: missing non-empty task_ids")
        for tid in task_ids:
            if tid in active:
                if active[tid].get("milestone_id") != mid:
                    raise ApiError(
                        f"{mid}: task {tid} belongs to {active[tid].get('milestone_id')} in tasks_master"
                    )
                continue
            if tid in archived:
                if archived[tid].get("milestone_id") != mid:
                    raise ApiError(
                        f"{mid}: task {tid} belongs to {archived[tid].get('milestone_id')} in tasks_archived"
                    )
                continue
            raise ApiError(f"{mid}: task {tid} missing in tasks_master and tasks_archived")


def validate_cross_refs(
    schedule: dict[str, Any], tasks_master: dict[str, Any], tasks_archived: dict[str, Any], boards: dict[str, Any]
) -> None:
    milestones = index_by_id(schedule.get("milestones", []))
    board_ids = {b["id"] for b in boards.get("boards", [])}
    active = index_by_id(tasks_master.get("tasks", []))
    archived = index_by_id(tasks_archived.get("tasks", []))
    all_task_ids = set(active) | set(archived)

    for mid in milestones:
        if not MILESTONE_ID_RE.match(mid):
            raise ApiError(f"invalid milestone id format: {mid}")

    for task in tasks_master.get("tasks", []):
        tid = task.get("id", "")
        if not TASK_ID_RE.match(tid):
            raise ApiError(f"invalid task id format: {tid}")
        if task.get("milestone_id") not in milestones:
            raise ApiError(f"task {tid} references unknown milestone_id {task.get('milestone_id')}")
        if task.get("status") not in ALLOWED_TASK_STATUS:
            raise ApiError(f"task {tid} has invalid status {task.get('status')}")
        validate_board_refs(task, board_ids)
        deps = task.get("depends_on", [])
        if not isinstance(deps, list):
            raise ApiError(f"task {tid} depends_on must be a list")
        for dep in deps:
            if dep not in all_task_ids:
                raise ApiError(f"task {tid} depends_on missing task id {dep}")

    validate_milestone_task_links(schedule, tasks_master, tasks_archived)


def create_milestone(schedule: dict[str, Any], body: dict[str, Any], task_ids_all: set[str]) -> str:
    required = {"id", "name", "emoji", "start_week", "end_week", "status", "task_ids"}
    missing = sorted(required - set(body))
    if missing:
        raise ApiError(f"POST /milestones missing fields: {', '.join(missing)}")
    mid = body["id"]
    if not MILESTONE_ID_RE.match(mid):
        raise ApiError("milestone id must match H-### or M-###")
    milestones = schedule.get("milestones", [])
    if any(m["id"] == mid for m in milestones):
        raise ApiError(f"milestone already exists: {mid}")
    if body["status"] not in ALLOWED_MILESTONE_STATUS:
        raise ApiError(f"invalid milestone status: {body['status']}")
    if not isinstance(body["task_ids"], list) or not body["task_ids"]:
        raise ApiError("milestone task_ids must be a non-empty list")
    for tid in body["task_ids"]:
        if tid not in task_ids_all:
            raise ApiError(f"milestone task_id not found in task ledgers: {tid}")
    milestones.append(body)
    return f"created milestone {mid}"


def patch_milestone(schedule: dict[str, Any], milestone_id: str, body: dict[str, Any], task_ids_all: set[str]) -> str:
    milestones = index_by_id(schedule.get("milestones", []))
    if milestone_id not in milestones:
        raise ApiError(f"milestone not found: {milestone_id}")
    if "id" in body and body["id"] != milestone_id:
        raise ApiError("milestone id is immutable")
    row = milestones[milestone_id]
    for k, v in body.items():
        row[k] = v
    if row.get("status") not in ALLOWED_MILESTONE_STATUS:
        raise ApiError(f"invalid milestone status: {row.get('status')}")
    if not isinstance(row.get("task_ids"), list) or not row["task_ids"]:
        raise ApiError("milestone task_ids must be non-empty")
    for tid in row["task_ids"]:
        if tid not in task_ids_all:
            raise ApiError(f"milestone task_id not found in task ledgers: {tid}")
    return f"updated milestone {milestone_id}"


def delete_milestone(
    schedule: dict[str, Any], tasks_master: dict[str, Any], milestone_id: str, force: bool
) -> str:
    milestones = schedule.get("milestones", [])
    found = next((m for m in milestones if m["id"] == milestone_id), None)
    if not found:
        raise ApiError(f"milestone not found: {milestone_id}")
    active_linked = [t["id"] for t in tasks_master.get("tasks", []) if t.get("milestone_id") == milestone_id]
    if active_linked and not force:
        raise ApiError(
            f"milestone {milestone_id} has active tasks: {', '.join(active_linked)}; "
            "delete tasks first or use --force"
        )
    schedule["milestones"] = [m for m in milestones if m["id"] != milestone_id]
    return f"deleted milestone {milestone_id}"


def create_task(
    tasks_master: dict[str, Any],
    schedule: dict[str, Any],
    boards: dict[str, Any],
    body: dict[str, Any],
    all_task_ids: set[str],
) -> str:
    required = {"id", "title", "milestone_id", "status", "depends_on", "board_refs"}
    missing = sorted(required - set(body))
    if missing:
        raise ApiError(f"POST /tasks missing fields: {', '.join(missing)}")
    tid = body["id"]
    if tid in all_task_ids:
        raise ApiError(f"task id already exists: {tid}")
    if not TASK_ID_RE.match(tid):
        raise ApiError("invalid task id format")
    milestone_ids = {m["id"] for m in schedule.get("milestones", [])}
    if body["milestone_id"] not in milestone_ids:
        raise ApiError(f"unknown milestone_id: {body['milestone_id']}")
    if body["status"] not in ALLOWED_TASK_STATUS:
        raise ApiError(f"invalid task status: {body['status']}")
    board_ids = {b["id"] for b in boards.get("boards", [])}
    validate_board_refs(body, board_ids)
    deps = body.get("depends_on", [])
    if not isinstance(deps, list):
        raise ApiError("depends_on must be a list")
    for dep in deps:
        if dep not in all_task_ids:
            raise ApiError(f"unknown dependency task id: {dep}")

    tasks_master.setdefault("tasks", []).append(body)
    # Maintain milestone task index contract.
    milestone = next(m for m in schedule["milestones"] if m["id"] == body["milestone_id"])
    if tid not in milestone["task_ids"]:
        milestone["task_ids"].append(tid)
    return f"created task {tid}"


def patch_task(
    tasks_master: dict[str, Any],
    schedule: dict[str, Any],
    boards: dict[str, Any],
    task_id: str,
    body: dict[str, Any],
    all_task_ids: set[str],
) -> str:
    rows = index_by_id(tasks_master.get("tasks", []))
    if task_id not in rows:
        raise ApiError(f"task not found in tasks_master: {task_id}")
    if "id" in body and body["id"] != task_id:
        raise ApiError("task id is immutable")

    row = rows[task_id]
    old_mid = row.get("milestone_id")
    for k, v in body.items():
        row[k] = v

    milestone_ids = {m["id"] for m in schedule.get("milestones", [])}
    if row.get("milestone_id") not in milestone_ids:
        raise ApiError(f"unknown milestone_id: {row.get('milestone_id')}")
    if row.get("status") not in ALLOWED_TASK_STATUS:
        raise ApiError(f"invalid task status: {row.get('status')}")
    board_ids = {b["id"] for b in boards.get("boards", [])}
    validate_board_refs(row, board_ids)
    if not isinstance(row.get("depends_on", []), list):
        raise ApiError("depends_on must be a list")
    for dep in row.get("depends_on", []):
        if dep not in all_task_ids:
            raise ApiError(f"unknown dependency task id: {dep}")

    # If milestone changed, move index link.
    new_mid = row["milestone_id"]
    if new_mid != old_mid:
        old_m = next(m for m in schedule["milestones"] if m["id"] == old_mid)
        old_m["task_ids"] = [tid for tid in old_m["task_ids"] if tid != task_id]
        if not old_m["task_ids"]:
            raise ApiError(f"cannot move last task out of milestone {old_mid}; add replacement first")
        new_m = next(m for m in schedule["milestones"] if m["id"] == new_mid)
        if task_id not in new_m["task_ids"]:
            new_m["task_ids"].append(task_id)
    return f"updated task {task_id}"


def delete_task(
    tasks_master: dict[str, Any],
    tasks_archived: dict[str, Any],
    task_id: str,
    force_remove_deps: bool,
) -> str:
    active = tasks_master.get("tasks", [])
    row = next((t for t in active if t["id"] == task_id), None)
    if row is None:
        raise ApiError(f"task not found in tasks_master: {task_id}")

    dependents = [t["id"] for t in active if task_id in t.get("depends_on", [])]
    if dependents and not force_remove_deps:
        raise ApiError(
            f"task {task_id} is depended on by: {', '.join(dependents)}; "
            "use --force-remove-deps to remove those references"
        )
    if force_remove_deps:
        for t in active:
            if task_id in t.get("depends_on", []):
                t["depends_on"] = [d for d in t["depends_on"] if d != task_id]

    active.remove(row)
    archived_row = copy.deepcopy(row)
    archived_row["status"] = "Archived"
    archived_row["archived_on"] = dt.date.today().isoformat()
    tasks_archived.setdefault("tasks", []).append(archived_row)
    return f"archived task {task_id}"


def handle_get(resource: str, ident: str | None, schedule: dict[str, Any], tasks_master: dict[str, Any]) -> int:
    if resource == "milestones":
        if ident is None:
            print(json.dumps(schedule.get("milestones", []), indent=2))
            return 0
        row = next((m for m in schedule.get("milestones", []) if m["id"] == ident), None)
        if row is None:
            raise ApiError(f"milestone not found: {ident}")
        print(json.dumps(row, indent=2))
        return 0

    if ident is None:
        print(json.dumps(tasks_master.get("tasks", []), indent=2))
        return 0
    row = next((t for t in tasks_master.get("tasks", []) if t["id"] == ident), None)
    if row is None:
        raise ApiError(f"task not found in tasks_master: {ident}")
    print(json.dumps(row, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Planning endpoint-style mutator.")
    parser.add_argument("method", help="GET|POST|PATCH|DELETE")
    parser.add_argument("path", help="Endpoint path like /milestones or /tasks/T-1101")
    parser.add_argument("--body", help="Inline JSON body")
    parser.add_argument("--body-file", help="Path to JSON body file")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry-run)")
    parser.add_argument("--force", action="store_true", help="Allow risky operation on milestone delete")
    parser.add_argument(
        "--force-remove-deps",
        action="store_true",
        help="When deleting task, remove dependency links from active tasks",
    )
    args = parser.parse_args()

    method = args.method.upper()
    if method not in METHODS:
        raise ApiError(f"unsupported method: {method}")
    resource, ident = split_path(args.path)

    schedule = load_json(SCHEDULE_PATH)
    tasks_master = load_json(TASKS_MASTER_PATH)
    tasks_archived = load_json(TASKS_ARCHIVED_PATH)
    boards = load_json(BOARDS_PATH)
    body = parse_body(args)

    if method == "GET":
        return handle_get(resource, ident, schedule, tasks_master)

    all_task_ids = {
        t["id"] for t in tasks_master.get("tasks", [])
    } | {t["id"] for t in tasks_archived.get("tasks", [])}

    summary = ""
    if resource == "milestones":
        if method == "POST":
            if ident is not None:
                raise ApiError("POST /milestones must not include id in path")
            summary = create_milestone(schedule, body, all_task_ids)
        elif method == "PATCH":
            if ident is None:
                raise ApiError("PATCH /milestones/{id} requires id in path")
            summary = patch_milestone(schedule, ident, body, all_task_ids)
        elif method == "DELETE":
            if ident is None:
                raise ApiError("DELETE /milestones/{id} requires id in path")
            summary = delete_milestone(schedule, tasks_master, ident, force=args.force)
        else:
            raise ApiError(f"unsupported method for milestones: {method}")
    else:
        if method == "POST":
            if ident is not None:
                raise ApiError("POST /tasks must not include id in path")
            summary = create_task(tasks_master, schedule, boards, body, all_task_ids)
        elif method == "PATCH":
            if ident is None:
                raise ApiError("PATCH /tasks/{id} requires id in path")
            summary = patch_task(tasks_master, schedule, boards, ident, body, all_task_ids)
        elif method == "DELETE":
            if ident is None:
                raise ApiError("DELETE /tasks/{id} requires id in path")
            summary = delete_task(tasks_master, tasks_archived, ident, args.force_remove_deps)
        else:
            raise ApiError(f"unsupported method for tasks: {method}")

    validate_cross_refs(schedule, tasks_master, tasks_archived, boards)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"mode: {mode}")
    print(summary)
    if args.apply:
        write_json(SCHEDULE_PATH, schedule)
        write_json(TASKS_MASTER_PATH, tasks_master)
        write_json(TASKS_ARCHIVED_PATH, tasks_archived)
        regenerate_gantt_artifacts()
        print("write: ok")
        print(f"regenerated: {GANTT_MD_PATH}, {GANTT_PNG_PATH}, {GANTT_DETAILED_MD_PATH}")
    else:
        print("write: skipped (use --apply)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
