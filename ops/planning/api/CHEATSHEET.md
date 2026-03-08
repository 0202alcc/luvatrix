# Planning Operator Cheatsheet (GateFlow 0.1.0a3)

Quick reference for Luvatrix planning operations.

## 0) Baseline

1. Wrapper default is pinned to `gateflow==0.1.0a3`.
2. Preferred command path:
- `uv run gateflow --root <repo> ...`
3. Direct published package path:
- `uvx --from gateflow==0.1.0a3 gateflow --root <repo> ...`
4. Verify active version:

```bash
uv run gateflow --version
```

## 1) Initialize + doctor

```bash
uv run gateflow --root . init
uv run gateflow --root . init doctor
```

If doctor reports missing files, stop and repair before write operations.

## 2) Read state

```bash
uv run gateflow --root . api GET /milestones
uv run gateflow --root . api GET /tasks
uv run gateflow --root . api GET /boards
uv run gateflow --root . api GET /frameworks
uv run gateflow --root . api GET /backlog
```

## 3) CRUD (resource/API shim)

```bash
uv run gateflow --root . milestones create --body '{"id":"A-021", ...}'
uv run gateflow --root . tasks create --body '{"id":"T-1201", ...}'
uv run gateflow --root . tasks update T-1201 --body '{"status":"Success Criteria Spec"}'
uv run gateflow --root . boards create --body '{"id":"milestone:A-021", ...}'
```

Legacy fallback (deprecated, compatibility only):

```bash
uv run python ops/planning/api/planning_api.py GET /milestones
```

## 4) Controlled close workflow (required)

Use close commands instead of status-only close edits.

```bash
uv run gateflow --root . close task T-1201 --heads-up "Go: required checks passed on main"
uv run gateflow --root . close milestone A-021 --heads-up "No-Go: missing deterministic replay evidence"
```

On close failure:

```bash
cat .gateflow/closeout/closure_issues.json
```

Include remediation steps from `closure_issues.json` in milestone/task logs.

## 5) Backend + sync workflow (phased adoption)

Observe-only phase:

```bash
uv run gateflow --root . backend status
uv run gateflow --root . sync status
```

Opt-in backend migration:

```bash
uv run gateflow --root . backend migrate --to backend
```

Sync flow:

```bash
uv run gateflow --root . sync from-main
uv run gateflow --root . sync status
uv run gateflow --root . sync apply
```

Protected repos can require sync before writes:

```bash
uv run gateflow --root . config set policy.require_sync_before_write true
```

## 6) Validation + gates

```bash
uv run gateflow --root . validate all
uv run python ops/planning/agile/validate_milestone_task_links.py
uv run python ops/planning/api/validate_closeout_packet.py --milestone-id <ID>
```

## 7) Branch/merge rule

1. Planning writes occur on milestone branch or approved planning branch.
2. Merge to `main` only after Go/No-Go gate evidence is complete.
3. Keep command outputs and evidence links in PR description.
