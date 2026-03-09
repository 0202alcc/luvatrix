# GateFlow 1.0.0 Rollout and Backend Adoption

## Scope

This repository is upgraded to GateFlow `1.0.0` and uses the backend-capable workflow with explicit sync-before-write policy.

Baseline command:

```bash
uvx --from gateflow==1.0.0 gateflow --root . <command>
```

Wrapper default:

```bash
uv run gateflow --root . <command>
```

## Version and Initialization

```bash
uvx --from gateflow==1.0.0 gateflow --version
uvx --from gateflow==1.0.0 gateflow --root . init doctor
```

Expected:
- version reports `1.0.0`
- doctor reports `ok: true`

## Canonical Validation Gates

```bash
uvx --from gateflow==1.0.0 gateflow --root . validate links
uvx --from gateflow==1.0.0 gateflow --root . validate closeout
uvx --from gateflow==1.0.0 gateflow --root . validate all
```

## Backend Migration and Rollback

Migrate to backend mode:

```bash
uvx --from gateflow==1.0.0 gateflow --root . backend status
uvx --from gateflow==1.0.0 gateflow --root . backend migrate --to backend
uvx --from gateflow==1.0.0 gateflow --root . backend status
```

Rollback path (must remain supported):

```bash
uvx --from gateflow==1.0.0 gateflow --root . backend migrate --to file
uvx --from gateflow==1.0.0 gateflow --root . backend status
```

Roundtrip parity check (file -> backend -> file) should be captured in migration evidence artifacts before final signoff.

## Sync-First Branch Policy

Enable branch standardization policy:

```bash
uvx --from gateflow==1.0.0 gateflow --root . config set policy.require_sync_before_write true
```

Required write preflight:

```bash
uvx --from gateflow==1.0.0 gateflow --root . sync from-main
uvx --from gateflow==1.0.0 gateflow --root . sync status
uvx --from gateflow==1.0.0 gateflow --root . sync apply
```

When drift exists, writes fail with `POLICY_SYNC_REQUIRED` until sync remediation is completed.

## Close Workflow (Go/No-Go)

Use controlled close commands, not raw status edits:

```bash
uvx --from gateflow==1.0.0 gateflow --root . close task <task-id> --heads-up "<Go/No-Go note>"
uvx --from gateflow==1.0.0 gateflow --root . close milestone <milestone-id> --heads-up "<Go/No-Go note>"
```

If close fails, inspect:

```bash
cat .gateflow/closeout/closure_issues.json
```

Note: if the command fails before close validation (for example due to sync policy), resolve sync first, then retry close.

## CI Requirements

Pull requests to `main` must run planning checks including:

1. pinned version check (`gateflow --version` = `1.0.0`)
2. clean sync status (`gateflow sync status`)
3. validation pack (`gateflow validate all`)

## Adoption Phases

1. Observe-only
- run `backend status`, `sync status`, `validate all`.

2. Optional backend
- run `backend migrate --to backend` on candidate repos.

3. Standard backend
- keep `policy.require_sync_before_write=true`.
- enforce sync + validate gates in CI.

## Recovery Procedure

If backend migration introduces operational issues:

1. `gateflow backend migrate --to file`
2. `gateflow validate all`
3. run milestone CI checks
4. log incident and attach migration evidence artifacts

