# AGENTS

Repository-level operating rules for human + AI contributors.

## Read First (Mandatory)
Before planning or editing code, read:
1. `ops/planning/gantt/milestone_schedule.json`
2. `ops/planning/gantt/milestones_gantt.md`
3. `ops/planning/agile/agile_board_seed.md`
4. `ops/planning/agile/agile_lineage_and_boards.md`

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
2. Use `ops/planning/api/planning_api.py` for milestone/task CRUD instead of manual JSON edits whenever possible.
3. Every milestone must have a `task_ids` list (empty allowed for bootstrap/split states).
4. Milestones should include `descriptions` (`string[]`) to record objective snapshots (especially across reopen cycles).
5. New milestones must include non-empty `success_criteria` and `closeout_criteria` (quantitative Go/No-Go metric contract).
6. New milestones must include non-empty `ci_required_checks` so each milestone branch has an explicit CI profile.
6. For milestones with `closeout_criteria`, add a `closeout_harness` task first before adding other task types.
7. `closeout_harness` task titles should use `[CLOSEOUT HARNESS]` prefix for clear visual separation.
8. Every populated milestone `task_id` must exist in active or archived task ledgers.
9. Tasks should include `notes` (`string | string[]`) for architect/system handoff context and implementation outline details.
10. Validate links with:
   - `uv run python ops/planning/agile/validate_milestone_task_links.py`
11. On successful `planning_api.py --apply`, Gantt markdown and PNG are regenerated automatically.
12. Agile framework default is `Luvatrix GateFlow (gateflow_v1)` defined in `ops/planning/agile/boards_registry.json`.
13. Milestone IDs use lettered schema: `<1-3 letters>-<3 digits>` where letters map to:
   - `A` app projects, `R` rendering backend, `F` first-party protocols/systems, `U` UI/UX tools, `P` project management, `X` other.
   - Combined IDs are allowed (up to 3 letters) and primary letter goes first.
14. Milestone lifecycle must be tracked via `lifecycle_events` in `milestone_schedule.json` (close/reopen + framework notes).
15. Use the operator command reference for standard actions:
   - `ops/planning/api/CHEATSHEET.md`
16. Cost scoring rubric reference:
   - `ops/planning/agile/gateflow_cost_rubric.md`
17. Closeout criteria rubric reference:
   - `ops/planning/agile/gateflow_guide.md` (`Valid Closeout Criteria Rubric`)
18. Milestone CI profile:
   - `ci_required_checks` must list required commands/check suites for milestone gate and post-merge validation.

## Planning API Usage (Required Flow)
1. Always run API calls in dry-run first (no `--apply`).
2. Re-run with `--apply` only after dry-run output is correct.
3. `planning_api.py --apply` is restricted to `main` only (global source of truth protection).
4. Use API endpoints for planning changes:
   - `/milestones` for milestone create/update/delete
   - `/tasks` for task create/update/archive
   - `/boards` and `/frameworks` for Agile framework/board controls
   - `/backlog` for leftover/unattached tickets
5. Do not manually edit planning JSON files unless API cannot express the needed operation.
6. After planning changes, run:
   - `uv run python ops/planning/agile/validate_milestone_task_links.py`
7. GateFlow transition rules are API-enforced:
   - no stage skipping,
   - backward moves require `--force-with-reason`,
   - WIP limits enforced per milestone from `ops/planning/agile/boards_registry.json` (`wip_limits`), with API-safe defaults/fallbacks if config is missing.

## Planning Sync SOP (Across Branches)
1. `main:/ops/planning/*` is the only canonical planning source of truth.
2. Milestone branches may run planning API in dry-run mode for checks/previews.
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
   - `uv run python ops/planning/api/planning_api.py PATCH /tasks/<task_id> --body '{...}' --reestimate-cost`
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
3. Any merge or pull request activity across threads requires explicit human permission.
4. Any merge or pull request activity from or to `main` requires explicit human permission.
5. If unsure whether an operation crosses thread boundaries or affects `main`, stop and ask a human before proceeding.
