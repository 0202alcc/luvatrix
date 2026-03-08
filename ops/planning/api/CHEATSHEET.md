# Planning Operator Cheatsheet (GateFlow 0.1.0a3)

Quick reference for Luvatrix planning operations.

> Legacy notice: `ops/planning/*` is archived/deprecated. Active planning state is `.gateflow/*`.

## 0) Baseline

1. Wrapper default is pinned to `gateflow==0.1.0a3`.
2. Preferred command path:
- `uvx --from gateflow==0.1.0a3 gateflow --root <repo> ...`
3. Direct published package path:
- `uvx --from gateflow==0.1.0a3 gateflow --root <repo> ...`
4. Verify active version:

```bash
uvx --from gateflow==0.1.0a3 gateflow --version
```

## 1) Initialize + doctor

```bash
uvx --from gateflow==0.1.0a3 gateflow --root . init
uvx --from gateflow==0.1.0a3 gateflow --root . init doctor
```

If doctor reports missing files, stop and repair before write operations.

## 2) Read state

```bash
uvx --from gateflow==0.1.0a3 gateflow --root . api GET /milestones
uvx --from gateflow==0.1.0a3 gateflow --root . api GET /tasks
uvx --from gateflow==0.1.0a3 gateflow --root . api GET /boards
uvx --from gateflow==0.1.0a3 gateflow --root . api GET /frameworks
uvx --from gateflow==0.1.0a3 gateflow --root . api GET /backlog
```

## 3) CRUD (resource/API shim)

```bash
uvx --from gateflow==0.1.0a3 gateflow --root . milestones create --body '{"id":"A-021", ...}'
uvx --from gateflow==0.1.0a3 gateflow --root . tasks create --body '{"id":"T-1201", ...}'
uvx --from gateflow==0.1.0a3 gateflow --root . tasks update T-1201 --body '{"status":"Success Criteria Spec"}'
uvx --from gateflow==0.1.0a3 gateflow --root . boards create --body '{"id":"milestone:A-021", ...}'
```

## 4) Controlled close workflow (required)

Use close commands instead of status-only close edits.

```bash
uvx --from gateflow==0.1.0a3 gateflow --root . close task T-1201 --heads-up "Go: required checks passed on main"
uvx --from gateflow==0.1.0a3 gateflow --root . close milestone A-021 --heads-up "No-Go: missing deterministic replay evidence"
```

On close failure:

```bash
cat .gateflow/closeout/closure_issues.json
```

Include remediation steps from `closure_issues.json` in milestone/task logs.

## 5) Backend + sync workflow (phased adoption)

Observe-only phase:

```bash
uvx --from gateflow==0.1.0a3 gateflow --root . backend status
uvx --from gateflow==0.1.0a3 gateflow --root . sync status
```

Opt-in backend migration:

```bash
uvx --from gateflow==0.1.0a3 gateflow --root . backend migrate --to backend
```

Sync flow:

```bash
uvx --from gateflow==0.1.0a3 gateflow --root . sync from-main
uvx --from gateflow==0.1.0a3 gateflow --root . sync status
uvx --from gateflow==0.1.0a3 gateflow --root . sync apply
```

Protected repos can require sync before writes:

```bash
uvx --from gateflow==0.1.0a3 gateflow --root . config set policy.require_sync_before_write true
```

## 6) Validation + gates

```bash
uvx --from gateflow==0.1.0a3 gateflow --root . validate links
uvx --from gateflow==0.1.0a3 gateflow --root . validate closeout
uvx --from gateflow==0.1.0a3 gateflow --root . validate all
```

## 7) Branch/merge rule

1. Planning writes occur on milestone branch or approved planning branch.
2. Merge to `main` only after Go/No-Go gate evidence is complete.
3. Keep command outputs and evidence links in PR description.
