#!/usr/bin/env python3
"""Endpoint-style planning data mutator for milestones and tasks.

Examples:
  python ops/planning/api/planning_api.py POST /milestones --body '{"id":"A-021",...}'
  python ops/planning/api/planning_api.py PATCH /tasks/T-1201 --body '{"status":"Prototype Stage 1"}' --apply
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from planning_domain import (
    METHODS,
    ApiError,
    handle_get,
    mutate_resource,
    parse_body,
    split_path,
    validate_cross_refs,
)
from planning_paths import PlanningPathResolver
from planning_renderer import SubprocessPlanningRenderer
from planning_storage import JsonPlanningStorage


def current_git_branch() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Planning endpoint-style mutator.")
    parser.add_argument("method", help="GET|POST|PATCH|DELETE")
    parser.add_argument(
        "path",
        help="Endpoint path like /milestones, /tasks/T-1101, /boards/{id}, /frameworks/{name}, /backlog/{id}",
    )
    parser.add_argument("--body", help="Inline JSON body")
    parser.add_argument("--body-file", help="Path to JSON body file")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry-run)")
    parser.add_argument("--force", action="store_true", help="Allow risky operation on milestone delete")
    parser.add_argument(
        "--force-remove-deps",
        action="store_true",
        help="When deleting task, remove dependency links from active tasks",
    )
    parser.add_argument(
        "--reestimate-cost",
        action="store_true",
        help="Recompute task cost_score from cost_components and apply stage multiplier for task POST/PATCH.",
    )
    parser.add_argument(
        "--force-with-reason",
        help="Explicit override reason for guarded operations (for example backward GateFlow moves).",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root to resolve planning ledger paths from (default: current directory)",
    )
    args = parser.parse_args()

    method = args.method.upper()
    if method not in METHODS:
        raise ApiError(f"unsupported method: {method}")
    resource, ident = split_path(args.path)

    resolver = PlanningPathResolver(args.root)
    paths = resolver.resolve()
    storage = JsonPlanningStorage(paths)
    renderer = SubprocessPlanningRenderer()
    state = storage.load_state()
    body = parse_body(body=args.body, body_file=args.body_file)

    if method == "GET":
        return handle_get(resource, ident, state.schedule, state.tasks_master, state.boards, state.backlog)

    summary = mutate_resource(
        method=method,
        resource=resource,
        ident=ident,
        body=body,
        schedule=state.schedule,
        tasks_master=state.tasks_master,
        tasks_archived=state.tasks_archived,
        boards=state.boards,
        backlog=state.backlog,
        closeout_dir=paths.closeout_dir,
        force=args.force,
        force_remove_deps=args.force_remove_deps,
        reestimate_cost=args.reestimate_cost,
        force_with_reason=args.force_with_reason,
    )

    validate_cross_refs(
        state.schedule,
        state.tasks_master,
        state.tasks_archived,
        state.boards,
        state.backlog,
    )

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"mode: {mode}")
    print(summary)
    if args.apply:
        branch = current_git_branch()
        if branch != "main":
            raise ApiError(
                "planning_api --apply is restricted to main branch only; "
                f"current branch is '{branch}'. Run this write on main, then sync milestone branches."
            )
        storage.write_state(state)
        renderer.regenerate_gantt_artifacts(paths)
        print("write: ok")
        print(f"regenerated: {paths.gantt_md_path}, {paths.gantt_png_path}")
    else:
        print("write: skipped (use --apply)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
