# F-027 CI Profile and Post-Merge Failure Procedure

Status: Frozen for milestone F-027

## Required CI Checks

The milestone gate requires all checks listed in milestone `F-027` `ci_required_checks`:

1. `uv run python ops/planning/agile/validate_milestone_task_links.py`
2. `uv run pytest tests -k "planes_v2_spec or planes_v2_contract" -q`
3. `uv run --with pytest pytest tests -k "planes_v2 and (debug_screenshot or debug_recording or debug_overlay or debug_replay or debug_frame_step or debug_bundle)" -q`
4. `PYTHONPATH=. uv run python ops/ci/r040_macos_debug_menu_functional_smoke.py`

## Milestone Branch Gate

Before milestone close:

1. Task-level branches must be merged into `codex/m-f-027`.
2. All four required CI checks must pass with retained command output evidence.
3. `uvx gateflow --root /Users/aleccandidato/Projects/luvatrix validate links` must pass.
4. `uvx gateflow --root /Users/aleccandidato/Projects/luvatrix validate closeout` must pass.

## Post-Merge Failure Procedure

If milestone PR merges to `main` and any required checks fail:

1. Reopen milestone `F-027` to `In Progress`.
2. Reopen impacted tasks to `Verification Review`.
3. Increment `actuals.reopen_count` for each reopened task.
4. Add remediation tasks and incident entries for each failing check.
5. Re-run all required checks and reissue Go/No-Go decision.

Required command for task reopen workflow:

1. `uv run python ops/planning/api/reopen_on_ci_failure.py --task-id <T-ID> --check-id <CHECK-ID> --summary "<short reason>" --apply`

## Determinism and Compatibility Boundaries

1. Reopen actions must preserve canonical basis alias semantics (`x/y/z` and `i_hat/j_hat/k_hat`) and not relax determinism rules.
2. No CI failure remediation may bypass the coordinate-placement determinism blockers.
3. Any temporary mitigation must be reversible and documented in closeout evidence.
