# AGENTS

Repository-level operating rules for human + AI contributors.

## P-048 Canonicalization Override (Effective 2026-03-08)
1. `.gateflow/*` is the only active planning ledger and source of truth.
2. `ops/planning/*` is deprecated/legacy archive content and must not be used for active planning writes.
3. All planning operations must use standalone GateFlow CLI commands:
   - `uvx --from gateflow==1.0.0 gateflow --root <repo> ...`
4. Legacy compatibility path `ops/planning/api/planning_api.py` is decommissioned for active operations.
5. CI and Go/No-Go gates must resolve from `.gateflow/*` state and `uvx gateflow validate ...` commands only.
6. If any instruction below conflicts with this section, this section takes precedence.

## Read First (Mandatory)
Before planning or editing code, read:
1. `.gateflow/milestones.json`
2. `.gateflow/tasks.json`
3. `.gateflow/boards.json`
4. `.gateflow/config.json`

## Milestone Thread Policy
1. Use one dedicated Codex thread per milestone.
2. Do not mix unrelated milestone implementation work in the same thread.
3. At thread start, restate the target milestone ID and task IDs.
4. At thread start, create or switch to the milestone branch immediately and confirm branch name in the thread.
5. Milestone branch naming is mandatory: `codex/m-<milestone-id-lowercase>` (example: `codex/m-p-026`).
6. All code and planning changes for that milestone thread must be committed on that milestone branch.
7. Branch command pattern:
   - `git switch main && git pull`
   - `git switch -c codex/m-<id-lower>`

## Milestone Branching and Integration Policy
1. Each milestone is implemented first on its own branch.
2. If milestone work depends on changes from another milestone branch, either:
   - merge those prerequisite changes to `main` first so dependent branches can pull from `main`, or
   - pull/cherry-pick the required changes directly from the source milestone branch.
3. Keep dependency flow explicit in PR descriptions and milestone board updates.
4. A milestone is not complete until:
   - all milestone changes are merged to `main`,
   - full intended functionality is present on `main`,
   - all required tests pass.
5. Milestones may be implementation-complete on branch, but they are not release-complete until the `main` integration gate is satisfied.
6. Team rule: milestone completion is recognized only after all milestone thread changes are merged to `main`.

## Task Branch Lifecycle (Required)
1. At milestone start, create the milestone branch from `main`.
2. Every task must use its own task branch, created from the milestone branch (not from `main`).
3. Task branch naming is mandatory:
   - `codex/t-<task-id-lower>-<short-slug>`
4. A task is only eligible for `Done` after GateFlow completion and merge of the task branch back into the milestone branch.
5. Milestone branch is merged into `main` only after milestone Go signal.
6. Do not delete task branches until milestone is fully approved and merged to `main`.
7. If milestone is No-Go:
   - assess failure reasons,
   - reopen/edit existing tasks or create remediation tasks,
   - continue from milestone branch with new/reopened task branches.

## Pull Request Format (Required)
1. Task-level PRs (task branch -> milestone branch):
   - Title: exact task name.
   - Description: one sentence per GateFlow step (`Intake` through `Integration Ready`) describing what happened.
2. Milestone PRs (milestone branch -> `main`):
   - Title: exact milestone name.
   - Description: ordered list of included tasks with one-line description per task outcome.
3. PR descriptions must explicitly note dependencies, evidence links, and any reopen rationale.

## Task Reporting System (Mandatory)
1. Task system source files:
   - `ops/planning/agile/tasks_master.json` (active tasks)
   - `ops/planning/agile/tasks_archived.json` (archived tasks)
   - `ops/planning/agile/backlog_misc.json` (misc backlog: carryover/unscoped/unattached)
   - `ops/planning/agile/boards_registry.json` (board definitions and formatting config)
   - `ops/planning/gantt/milestone_schedule.json` (milestones + `task_ids`)
2. Use standalone `gateflow` command paths for milestone/task CRUD (`uv run gateflow --root <repo> api ...`) instead of manual JSON edits whenever possible.
3. GateFlow runtime version baseline is `gateflow==1.0.0`.
4. Wrapper default command is pinned to `uvx --from gateflow==1.0.0 gateflow`; use `LUVATRIX_GATEFLOW_WRAPPER_CMD` only for explicit overrides.
5. Every milestone must have a `task_ids` list (empty allowed for bootstrap/split states).
6. Milestones should include `descriptions` (`string[]`) to record objective snapshots (especially across reopen cycles).
7. New milestones must include non-empty `success_criteria` and `closeout_criteria` (quantitative Go/No-Go metric contract).
8. New milestones must include non-empty `ci_required_checks` so each milestone branch has an explicit CI profile.
9. For milestones with `closeout_criteria`, add a `closeout_harness` task first before adding other task types.
10. `closeout_harness` task titles should use `[CLOSEOUT HARNESS]` prefix for clear visual separation.
11. Every populated milestone `task_id` must exist in active or archived task ledgers.
12. Tasks should include `notes` (`string | string[]`) for architect/system handoff context and implementation outline details.
13. Validate links with:
   - `uv run python ops/planning/agile/validate_milestone_task_links.py`
14. On successful planning writes (`gateflow api ...` or legacy `planning_api.py --apply`), Gantt markdown and PNG are regenerated automatically.
15. Agile framework default is `Luvatrix GateFlow (gateflow_v1)` defined in `ops/planning/agile/boards_registry.json`.
16. Milestone IDs use lettered schema: `<1-3 letters>-<3 digits>` where letters map to:
   - `A` app projects, `R` rendering backend, `F` first-party protocols/systems, `U` UI/UX tools, `P` project management, `X` other.
   - Combined IDs are allowed (up to 3 letters) and primary letter goes first.
17. Milestone lifecycle must be tracked via `lifecycle_events` in `milestone_schedule.json` (close/reopen + framework notes).
18. Use the operator command reference for standard actions:
   - `ops/planning/api/CHEATSHEET.md`
19. Cost scoring rubric reference:
   - `ops/planning/agile/gateflow_cost_rubric.md`
20. Closeout criteria rubric reference:
   - `ops/planning/agile/gateflow_guide.md` (`Valid Closeout Criteria Rubric`)
21. Milestone CI profile:
   - `ci_required_checks` must list required commands/check suites for milestone gate and post-merge validation.

## Planning Command Usage (Required Flow)
1. Primary command path is standalone `gateflow` (for example: `uv run gateflow --root <repo> api GET /milestones`).
2. For first-time repo setup, run:
   - `uv run gateflow init`
   - `uv run gateflow init doctor`
3. Prefer controlled close flows over raw status-only closures:
   - `uv run gateflow close task <id> --heads-up "<Go/No-Go note>"`
   - `uv run gateflow close milestone <id> --heads-up "<Go/No-Go note>"`
4. If a close command fails, review `.gateflow/closeout/closure_issues.json` and include remediation in task/milestone logs.
5. Backend/sync runbook commands:
   - `uv run gateflow backend status`
   - `uv run gateflow backend migrate --to backend` (opt-in)
   - `uv run gateflow sync from-main`
   - `uv run gateflow sync status`
   - `uv run gateflow sync apply`
6. For protected flows, set `policy.require_sync_before_write=true` before write operations.
7. Use legacy `planning_api.py` for dry-run/write-guard workflows that still require `--apply` semantics.
8. `planning_api.py --apply` is restricted to `main` only (global source of truth protection).
9. Use API endpoints for planning changes:
   - `/milestones` for milestone create/update/delete
   - `/tasks` for task create/update/archive
   - `/boards` and `/frameworks` for Agile framework/board controls
   - `/backlog` for leftover/unattached tickets
10. Do not manually edit planning JSON files unless API cannot express the needed operation.
11. After planning changes, run:
   - `uv run python ops/planning/agile/validate_milestone_task_links.py`
12. GateFlow transition rules are API-enforced:
   - no stage skipping,
   - backward moves require `--force-with-reason`,
   - WIP limits enforced per milestone from `ops/planning/agile/boards_registry.json` (`wip_limits`), with API-safe defaults/fallbacks if config is missing.

## Planning Sync SOP (Across Branches)
1. `main:/ops/planning/*` is the only canonical planning source of truth.
2. Milestone branches may run standalone `gateflow` reads and legacy planning API dry-run mode for checks/previews.
3. All planning writes (`--apply`) must be executed on `main`.
4. Workflow:
   - perform implementation on milestone branch,
   - switch to `main` and apply planning state updates via API,
   - switch back and rebase/pull `main` into milestone branch.
5. Do not keep long-lived planning deltas on milestone branches.
6. Before milestone branch merge/review, run drift check:
   - `uv run python ops/planning/api/check_planning_drift.py --fetch`
7. If drift is reported and there are no local planning edits to keep, auto-sync:
   - `bash ops/planning/api/sync_planning_from_main.sh`
8. Sync script safety rules:
   - refuses to run on `main`,
   - refuses if `ops/planning` has local edits,
   - commits a planning-only sync when changes are applied.

## Milestone Closeout Packet (Required to Mark Complete)
1. Milestone cannot transition to `Complete` without:
   - `ops/planning/closeout/<milestone-id-lower>_closeout.md`
2. Required section headings:
   - `Objective Summary`
   - `Task Final States`
   - `Evidence`
   - `Determinism`
   - `Protocol Compatibility`
   - `Modularity`
   - `Residual Risks`
3. Validate with:
   - `uv run python ops/planning/api/validate_closeout_packet.py --milestone-id <ID>`

## Post-Merge Failure Protocol
1. If post-merge checks fail for a `Done` task:
   - reopen task to `Verification Review`,
   - increment `actuals.reopen_count`,
   - create backlog incident record.
2. If milestone PR merges to `main` but milestone-level CI checks fail:
   - reopen milestone to `In Progress`,
   - reopen failed tasks to `Verification Review`,
   - add remediation tasks and incident entries,
   - re-run `ci_required_checks` before requesting new Go.
3. Use:
   - `uv run python ops/planning/api/reopen_on_ci_failure.py --task-id <T-ID> --check-id <CHECK-ID> --summary \"<short reason>\" --apply`

## GateFlow Workflow (Default)
1. Default columns:
   - `Intake`
   - `Success Criteria Spec`
   - `Safety Tests Spec`
   - `Implementation Tests Spec`
   - `Edge Case Tests Spec`
   - `Prototype Stage 1`
   - `Prototype Stage 2+`
   - `Verification Review`
   - `Integration Ready`
   - `Done`
   - `Blocked`
2. A single ticket moves across these columns; do not create one ticket per column by default.
3. Gate rules:
   - ticket cannot enter `Prototype Stage 1` until spec/test columns are complete,
   - ticket cannot enter `Done` until merged to `main` with required checks passing on `main`.
4. Use the planning API for framework/board edits:
   - `GET /frameworks`
   - `PATCH /frameworks` (set default framework)
   - `GET|POST|PATCH|DELETE /boards[/id]`

## GateFlow Cost Scoring (Recommended, Near-Required)
1. Add optional cost fields on tasks at intake:
   - `cost_components` (`context_load`, `reasoning_depth`, `code_edit_surface`, `validation_scope`, `iteration_risk`)
   - `cost_confidence` (`0..1`)
2. Re-estimate before build stages using API:
   - `uv run python ops/planning/api/planning_api.py PATCH /tasks/<task_id> --body '{...}' --reestimate-cost` (legacy compatibility path)
3. API auto-derives:
   - `cost_score` (`0..100`)
   - `cost_bucket` (`S|M|L|XL|XXL`)
   - `stage_multiplier_applied`
   - `cost_basis_version=gateflow_cost_v1`
4. Gate policy:
   - `XL/XXL` tasks should be split before entering `Prototype Stage 1`.
   - if `cost_confidence < 0.35`, refine specs before prototype stages.
5. On `Blocked` transitions, confidence is reduced automatically by API (`-0.15` floor at `0.0`).

## GateFlow Completion Telemetry (Required for Done Transition)
1. When moving a task into `Done`, include `actuals`:
   - `input_tokens` (number, `>= 0`)
   - `output_tokens` (number, `>= 0`)
   - `wall_time_sec` (number, `>= 0`)
   - `tool_calls` (number, `>= 0`)
   - `reopen_count` (number, `>= 0`)
2. When moving a task into `Done`, include `done_gate` checklist with all values `true`:
   - `success_criteria_met`
   - `safety_tests_passed`
   - `implementation_tests_passed`
   - `edge_case_tests_passed`
   - `merged_to_main`
   - `required_checks_passed_on_main`
3. API enforces this only when a task transitions into `Done` (historical done tasks are not retroactively blocked).

## Agile Board Update Policy
1. Each milestone must have a live execution board file: `ops/planning/agile/m<milestone>_execution_board.md`.
2. Board columns default to GateFlow (`Intake` -> `...` -> `Integration Ready` -> `Done`, plus `Blocked`) unless a board explicitly sets another framework template.
3. Move task cards as status changes during work.
4. Keep board status changes in the same commit where task state changes.
5. Do not mark `Done` without linked test evidence.

## Python Tooling Policy (uv)
1. Use `uv` commands for Python workflows.
2. Preferred commands:
   - `uv sync`
   - `uv run pytest ...`
   - `uv run python ...`
3. Do not use bare `python` or `pip` unless blocked by environment constraints.
4. If blocked, document the reason and fallback command used.

## Execution Autonomy and Permission Boundaries
1. In a dedicated milestone thread, agents may run `uv` commands without asking for additional permission.
2. In that same milestone thread, agents may run local `git` workflow commands without asking (for example: `git status`, `git add`, `git commit`, branch-local history checks).
3. Default policy: any merge or pull request activity across threads requires explicit human permission.
4. Default policy: any merge or pull request activity from or to `main` requires explicit human permission.
5. Autonomous exception (one-shot milestone execution):
   - If the user explicitly instructs the agent to execute a milestone end-to-end without permission prompts in that thread, the agent is authorized for that thread to:
   - create task PRs from `codex/t-*` -> milestone branch,
   - merge task PRs into the milestone branch after checks pass,
   - create milestone PR from milestone branch -> `main`,
   - merge milestone PR to `main` after Go/No-Go is `GO` and required checks pass.
6. Autonomous exception boundaries:
   - Only applies to milestone/task branches and milestone IDs explicitly named in that thread.
   - Does not authorize unrelated cross-thread merges or repo-wide refactors outside milestone scope.
   - If scope is ambiguous, stop and ask for clarification.
7. GitHub CLI/network fallback:
   - If `gh` commands fail in sandbox with API connectivity errors (for example `api.github.com` unreachable), retry using escalated execution instead of asking the user to run commands manually.
   - Record the final PR URL (or the exact blocking error) in the task/milestone log.
8. If unsure whether an operation crosses thread boundaries or affects out-of-scope work, stop and ask a human before proceeding.
