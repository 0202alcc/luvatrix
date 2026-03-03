# Planning API (Local Endpoint-Style)

This provides a standardized, safe mutation path for planning data using:

`METHOD /resource[/id]`

Quick operator reference:

- `ops/planning/api/CHEATSHEET.md`

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

3. Boards
- `GET /boards`
- `GET /boards/{id}`
- `POST /boards`
- `PATCH /boards/{id}`
- `DELETE /boards/{id}`

4. Frameworks
- `GET /frameworks` (default + templates)
- `GET /frameworks/{name}`
- `POST /frameworks/{name}`
- `PATCH /frameworks/{name}`
- `PATCH /frameworks` (set `default_framework_template`)
- `DELETE /frameworks/{name}`

5. Backlog
- `GET /backlog`
- `GET /backlog/{id}`
- `POST /backlog`
- `PATCH /backlog/{id}`
- `DELETE /backlog/{id}`

## Safety guarantees

1. Dry-run by default (`--apply` required to write).
2. Atomic writes to source files.
3. Validates:
- milestone/task id formats
- task status values
- board references exist in `boards_registry.json`
- milestone `task_ids` all resolve in active or archived task ledgers
- task dependency IDs are well-formed (`T-###` style)
- backlog item IDs/status/bucket formats and optional references
4. Prevents unsafe deletes unless force flags are explicit.
5. On successful `--apply`, automatically regenerates:
- `ops/planning/gantt/milestones_gantt.md`
- `ops/planning/gantt/milestones_gantt.png`
6. Task statuses are validated against framework template status columns (GateFlow default) plus legacy compatibility statuses.

## Usage

1. List milestones:
```bash
python ops/planning/api/planning_api.py GET /milestones
```

2. Add task (dry-run):
```bash
python ops/planning/api/planning_api.py POST /tasks \
  --body '{"id":"T-1201","title":"Add X","milestone_id":"A-021","status":"Intake","depends_on":[],"board_refs":["milestone:A-021","team:runtime","specialist:development"]}'
```

3. Apply edit to task:
```bash
python ops/planning/api/planning_api.py PATCH /tasks/T-1201 \
  --body '{"status":"Prototype Stage 1"}' \
  --apply
```

4. Archive task:
```bash
python ops/planning/api/planning_api.py DELETE /tasks/T-1201 --apply
```

5. Show framework templates + default:
```bash
python ops/planning/api/planning_api.py GET /frameworks
```

6. Set default framework to GateFlow:
```bash
python ops/planning/api/planning_api.py PATCH /frameworks \
  --body '{"default_framework_template":"gateflow_v1"}' \
  --apply
```

7. Create a board with GateFlow template:
```bash
python ops/planning/api/planning_api.py POST /boards \
  --body '{"id":"milestone:A-021","title":"A-021 Board","type":"milestone","framework_template":"gateflow_v1","source_filter":{"milestone_id":"A-021"},"discord":{"channel":"#milestone-a-021-board","threads_enabled":true}}' \
  --apply
```

8. Add an unattached carryover ticket to misc backlog:
```bash
python ops/planning/api/planning_api.py POST /backlog \
  --body '{"id":"B-001","title":"Refine old milestone handoff note","status":"Open","bucket":"Carryover","source_milestone_id":"U-017"}' \
  --apply
```
