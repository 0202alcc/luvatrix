# Planes v2 Planning Payload Pack

Dry-run first, then apply.

## 1) Create milestones (dry-run)
Use files in `milestones/` with:
`uv run python ops/planning/api/planning_api.py POST /milestones --body-file <file>`

## 2) Create milestone boards (dry-run)
Use files in `boards/` with:
`uv run python ops/planning/api/planning_api.py POST /boards --body-file <file>`

## 3) Create tasks in dependency order (dry-run)
Use files in `tasks/` with:
`uv run python ops/planning/api/planning_api.py POST /tasks --body-file <file>`

## 4) Apply in same order on main
Repeat with `--apply`.

## 5) Validate
- `uv run python ops/planning/agile/validate_milestone_task_links.py`
