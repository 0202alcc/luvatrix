# Planning Operator Cheatsheet

Fast command reference for milestone/task/board/backlog operations.

## 0) Safe defaults

1. Dry-run first (no `--apply`).
2. Re-run with `--apply` once output looks correct.
3. API `--apply` auto-regenerates:
- `ops/planning/gantt/milestones_gantt.md`
- `ops/planning/gantt/milestones_gantt.png`

## 1) Milestone IDs

Format: `<1-3 letters>-<3 digits>` (examples: `A-021`, `FR-004`, `APU-020`)

Letter taxonomy:

1. `A` app projects
2. `R` rendering backend
3. `F` first-party protocol/system
4. `U` UI/UX native tooling
5. `P` project management
6. `X` uncategorized/other

## 2) Read state

```bash
uv run python ops/planning/api/planning_api.py GET /milestones
uv run python ops/planning/api/planning_api.py GET /tasks
uv run python ops/planning/api/planning_api.py GET /boards
uv run python ops/planning/api/planning_api.py GET /frameworks
uv run python ops/planning/api/planning_api.py GET /backlog
```

## 3) Create milestone + board (GateFlow)

```bash
uv run python ops/planning/api/planning_api.py POST /milestones \
  --body '{"id":"A-021","emoji":"🧩","name":"Example app project","start_week":13,"end_week":16,"status":"Planned","task_ids":["T-1201"],"lifecycle_events":[{"date":"2026-03-03","event":"active","framework":"gateflow_v1","note":"opened"}]}'
```

```bash
uv run python ops/planning/api/planning_api.py POST /boards \
  --body '{"id":"milestone:A-021","title":"A-021 Example app project","type":"milestone","framework_template":"gateflow_v1","source_filter":{"milestone_id":"A-021"},"discord":{"channel":"#milestone-a-021-board","threads_enabled":true}}'
```

Apply:

```bash
uv run python ops/planning/api/planning_api.py POST /milestones --body-file /tmp/new_milestone.json --apply
uv run python ops/planning/api/planning_api.py POST /boards --body-file /tmp/new_board.json --apply
```

## 4) Create/update task (GateFlow statuses)

Create:

```bash
uv run python ops/planning/api/planning_api.py POST /tasks \
  --body '{"id":"T-1201","title":"Define success criteria","milestone_id":"A-021","status":"Intake","depends_on":[],"board_refs":["milestone:A-021","team:protocol","specialist:pm"]}'
```

Move status:

```bash
uv run python ops/planning/api/planning_api.py PATCH /tasks/T-1201 \
  --body '{"status":"Success Criteria Spec"}'
```

Apply:

```bash
uv run python ops/planning/api/planning_api.py PATCH /tasks/T-1201 \
  --body '{"status":"Prototype Stage 1"}' \
  --apply
```

## 5) Close/reopen milestone lifecycle

Update milestone status:

```bash
uv run python ops/planning/api/planning_api.py PATCH /milestones/A-021 \
  --body '{"status":"Complete"}'
```

Update lifecycle events in milestone payload:

```bash
uv run python ops/planning/api/planning_api.py PATCH /milestones/A-021 \
  --body '{"lifecycle_events":[{"date":"2026-03-03","event":"closed","framework":"gateflow_v1","note":"sprint complete"},{"date":"2026-03-10","event":"reopened","framework":"gateflow_v1","note":"new sprint started"}]}' \
  --apply
```

## 6) Framework controls

Show framework templates:

```bash
uv run python ops/planning/api/planning_api.py GET /frameworks
```

Set default template:

```bash
uv run python ops/planning/api/planning_api.py PATCH /frameworks \
  --body '{"default_framework_template":"gateflow_v1"}' \
  --apply
```

## 7) Misc backlog (leftovers/unattached)

Create backlog item:

```bash
uv run python ops/planning/api/planning_api.py POST /backlog \
  --body '{"id":"B-001","title":"Carry over unresolved perf probe","status":"Open","bucket":"Carryover","source_milestone_id":"U-017","task_ref":"T-836"}'
```

Update backlog item:

```bash
uv run python ops/planning/api/planning_api.py PATCH /backlog/B-001 \
  --body '{"status":"Triaged","bucket":"Backfill"}'
```

Close backlog item:

```bash
uv run python ops/planning/api/planning_api.py PATCH /backlog/B-001 \
  --body '{"status":"Closed"}' \
  --apply
```

## 8) Validation

```bash
uv run python ops/planning/agile/validate_milestone_task_links.py
```

## 9) Completion rule

Milestone is considered complete only when:

1. milestone thread changes are merged to `main`
2. required checks pass on `main`
