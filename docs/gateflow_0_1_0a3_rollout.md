# GateFlow 0.1.0a3 Rollout Plan

## Scope

Migrate Luvatrix planning operations to GateFlow `0.1.0a3` lifecycle features while preserving deterministic, offline/local-first behavior.

## Before/After Command Examples

### Version + init

Before:

```bash
uvx --from gateflow gateflow --version
```

After:

```bash
uv run gateflow --version
uv run gateflow --root . init
uv run gateflow --root . init doctor
```

### Closing work

Before:

```bash
uv run gateflow --root . tasks update T-1201 --body '{"status":"Done"}'
```

After:

```bash
uv run gateflow --root . close task T-1201 --heads-up "Go: required checks passed on main"
uv run gateflow --root . close milestone A-021 --heads-up "No-Go: missing deterministic replay evidence"
```

### Failed close handling

```bash
cat .gateflow/closeout/closure_issues.json
```

## Backend/Sync Adoption Phases

1. Observe-only
- `uv run gateflow --root . backend status`
- `uv run gateflow --root . sync status`
- keep current write flow unchanged.

2. Optional backend
- `uv run gateflow --root . backend migrate --to backend` on selected repos.
- monitor close flows and sync drift behavior.

3. Default backend
- enforce sync-before-write:
  - `uv run gateflow --root . config set policy.require_sync_before_write true`
- standardize:
  - `sync from-main -> sync status -> sync apply` before write windows.

## Validation Gates

```bash
uv run gateflow --root . validate all
uv run python ops/planning/agile/validate_milestone_task_links.py
uv run python ops/planning/api/validate_closeout_packet.py --milestone-id <ID>
```

## Adoption Risks

1. Command drift across local/CI environments
- Mitigation: pinned wrapper + CI `gateflow --version` checks.

2. Close flows fail due missing evidence payloads
- Mitigation: parse `.gateflow/closeout/closure_issues.json` and require remediation notes in PR/task logs.

3. Sync policy friction on legacy repos
- Mitigation: phased enablement, observe-only first, then opt-in migration.
