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
- note: `task_ids` may be omitted or empty at milestone creation; attach tasks later or stage in backlog.

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
3. `--apply` writes are restricted to `main` branch only (`main:/ops/planning/*` is canonical source of truth).
3. Validates:
- milestone/task id formats
- task status values
- board references exist in `boards_registry.json`
- milestone `task_ids` (if populated) all resolve in active or archived task ledgers
- task dependency IDs are well-formed (`T-###` style)
- backlog item IDs/status/bucket formats and optional references
4. Prevents unsafe deletes unless force flags are explicit.
5. On successful `--apply`, automatically regenerates:
- `ops/planning/gantt/milestones_gantt.md`
- `ops/planning/gantt/milestones_gantt.png`
6. Task statuses are validated against framework template status columns (GateFlow default) plus legacy compatibility statuses.
7. Optional task cost model is supported (`gateflow_cost_v1`) with:
- `cost_components` (`0..100` each)
- `cost_confidence` (`0..1`)
- derived fields (`cost_score`, `cost_bucket`, `stage_multiplier_applied`) via `--reestimate-cost`
8. `Done` transition guard requires task payload to include:
- `actuals` numeric fields: `input_tokens`, `output_tokens`, `wall_time_sec`, `tool_calls`, `reopen_count`
- `done_gate` boolean fields all `true`: `success_criteria_met`, `safety_tests_passed`, `implementation_tests_passed`, `edge_case_tests_passed`, `merged_to_main`, `required_checks_passed_on_main`
9. GateFlow transition guard:
- no stage skipping
- backward stage moves require `--force-with-reason`
10. WIP limits are enforced per milestone:
- `Prototype Stage 1` + `Prototype Stage 2+` combined <= 2
- `Verification Review` <= 1
11. Milestone cannot be set to `Complete` without closeout packet:
- `ops/planning/closeout/<milestone-id-lower>_closeout.md`
- required sections validated by `validate_closeout_packet.py`

## Planning Sync SOP

1. Run planning API in dry-run mode on milestone branches when needed.
2. Execute all planning writes (`--apply`) on `main`.
3. After applying planning updates on `main`, sync milestone branches from `main`.
4. Detect branch planning drift:
```bash
uv run python ops/planning/api/check_planning_drift.py --fetch
```
5. Auto-sync planning from `origin/main` on milestone branch (conflict-safe flow):
```bash
bash ops/planning/api/sync_planning_from_main.sh
```
6. Sync script behavior:
- exits on `main`
- exits if local `ops/planning` edits exist
- restores `ops/planning` from `origin/main` and commits sync delta

## Failure Reopen Utility

Use this to handle post-merge check failures on previously `Done` tasks:

```bash
python ops/planning/api/reopen_on_ci_failure.py \
  --task-id T-2404 \
  --check-id ci-12345 \
  --summary "p95 transfer latency regression over threshold" \
  --apply
```

Behavior:
1. task moves `Done -> Verification Review`
2. `actuals.reopen_count` increments
3. incident entry is added to `backlog_misc.json`
4. if milestone was `Complete`, it is auto-reopened to `In Progress`

## Telemetry Backfill

If historical tasks are missing `cost_*` and `Done` telemetry fields:

```bash
python ops/planning/api/backfill_task_telemetry.py --include-done-telemetry --apply
```

Notes:
1. Run on `main` only.
2. Cost fields are marked estimated for later replacement with measured values.

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

4. Re-estimate task cost from rubric components:
```bash
python ops/planning/api/planning_api.py PATCH /tasks/T-1201 \
  --body '{"status":"Prototype Stage 1","cost_components":{"context_load":50,"reasoning_depth":60,"code_edit_surface":40,"validation_scope":55,"iteration_risk":45},"cost_confidence":0.72}' \
  --reestimate-cost \
  --apply
```

5. Archive task:
```bash
python ops/planning/api/planning_api.py DELETE /tasks/T-1201 --apply
```

6. Show framework templates + default:
```bash
python ops/planning/api/planning_api.py GET /frameworks
```

7. Set default framework to GateFlow:
```bash
python ops/planning/api/planning_api.py PATCH /frameworks \
  --body '{"default_framework_template":"gateflow_v1"}' \
  --apply
```

8. Create a board with GateFlow template:
```bash
python ops/planning/api/planning_api.py POST /boards \
  --body '{"id":"milestone:A-021","title":"A-021 Board","type":"milestone","framework_template":"gateflow_v1","source_filter":{"milestone_id":"A-021"},"discord":{"channel":"#milestone-a-021-board","threads_enabled":true}}' \
  --apply
```

9. Add an unattached carryover ticket to misc backlog:
```bash
python ops/planning/api/planning_api.py POST /backlog \
  --body '{"id":"B-001","title":"Refine old milestone handoff note","status":"Open","bucket":"Carryover","source_milestone_id":"U-017"}' \
  --apply
```

10. Move task to `Done` with required telemetry:
```bash
python ops/planning/api/planning_api.py PATCH /tasks/T-1201 \
  --body '{"status":"Done","actuals":{"input_tokens":1800,"output_tokens":2400,"wall_time_sec":920,"tool_calls":14,"reopen_count":1},"done_gate":{"success_criteria_met":true,"safety_tests_passed":true,"implementation_tests_passed":true,"edge_case_tests_passed":true,"merged_to_main":true,"required_checks_passed_on_main":true}}' \
  --apply
```
