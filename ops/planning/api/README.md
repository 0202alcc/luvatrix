# Planning API (Local Endpoint-Style)

This provides a standardized, safe mutation path for planning data using:

`METHOD /resource[/id]`

## Milestone Thread Rule

1. At the beginning of each milestone thread, create/switch to a dedicated milestone branch.
2. Keep milestone changes on that branch until human-approved integration/merge steps.
3. Milestone completion is recognized only after milestone thread changes are merged to `main`.

## Endpoints

1. Milestones
- `GET /milestones`
- `GET /milestones/{id}`
- `POST /milestones`
- `PATCH /milestones/{id}`
- `DELETE /milestones/{id}` (`--force` required if active tasks still linked)

2. Tasks
- `GET /tasks`
- `GET /tasks/{id}`
- `POST /tasks`
- `PATCH /tasks/{id}`
- `DELETE /tasks/{id}` (archives task in `tasks_archived.json`)

## Safety guarantees

1. Dry-run by default (`--apply` required to write).
2. Atomic writes to source files.
3. Validates:
- milestone/task id formats
- task status values
- board references exist in `boards_registry.json`
- milestone `task_ids` all resolve in active or archived task ledgers
- task dependency references resolve
4. Prevents unsafe deletes unless force flags are explicit.
5. On successful `--apply`, automatically regenerates:
- `ops/planning/gantt/milestones_gantt.md`
- `ops/planning/gantt/milestones_gantt_detailed.md`
- `ops/planning/gantt/milestones_gantt.png`

## Usage

1. List milestones:
```bash
python ops/planning/api/planning_api.py GET /milestones
```

2. Add task (dry-run):
```bash
python ops/planning/api/planning_api.py POST /tasks \
  --body '{"id":"T-1201","title":"Add X","milestone_id":"M-012","status":"Backlog","depends_on":[],"board_refs":["milestone:M-012","team:runtime","specialist:development"]}'
```

3. Apply edit to task:
```bash
python ops/planning/api/planning_api.py PATCH /tasks/T-1201 \
  --body '{"status":"In Progress"}' \
  --apply
```

4. Archive task:
```bash
python ops/planning/api/planning_api.py DELETE /tasks/T-1201 --apply
```
