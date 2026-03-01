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
5. Recommended branch naming: `codex/m-<milestone-id-lowercase>-<short-slug>` (example: `codex/m-011-planning-api`).
6. All code and planning changes for that milestone thread must be committed on that milestone branch.
7. Branch command pattern:
   - `git switch main && git pull`
   - `git switch -c codex/m-<id>-<slug>`

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

## Task Reporting System (Mandatory)
1. Task system source files:
   - `ops/planning/agile/tasks_master.json` (active tasks)
   - `ops/planning/agile/tasks_archived.json` (archived tasks)
   - `ops/planning/agile/boards_registry.json` (board definitions and formatting config)
   - `ops/planning/gantt/milestone_schedule.json` (milestones + `task_ids`)
2. Use `ops/planning/api/planning_api.py` for milestone/task CRUD instead of manual JSON edits whenever possible.
3. Every milestone must have a non-empty `task_ids` list.
4. Every milestone `task_id` must exist in active or archived task ledgers.
5. Validate links with:
   - `uv run python ops/planning/agile/validate_milestone_task_links.py`
6. On successful `planning_api.py --apply`, Gantt markdown and PNG are regenerated automatically.

## Agile Board Update Policy
1. Each milestone must have a live execution board file: `ops/planning/agile/m<milestone>_execution_board.md`.
2. Board columns: `Backlog`, `Ready`, `In Progress`, `Review`, `Done`.
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
