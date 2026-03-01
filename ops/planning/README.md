# Planning Data

This directory is the canonical home for project planning artifacts that are
not Discord-specific.

## Structure

1. `gantt/`
- `milestone_schedule.json` (source-of-truth timeline data)
- `milestones_gantt.md` (consolidated generated markdown: chart + milestone detail sections)
- `milestones_gantt_detailed.md` (generated detailed ASCII chart)
- `milestones_gantt.png` (generated visual chart)

2. `agile/`
- `tasks_master.json` (canonical task source-of-truth across all boards)
- `tasks_archived.json` (archived historical task ledger for completed milestones)
- `boards_registry.json` (board definitions + formatting/rendering config)
- `validate_milestone_task_links.py` (ensures each gantt milestone task exists in active or archived ledger)
- `README.md` (data contract + update workflow)
- `agile_board_seed.md` (cross-milestone epic/task seeds)
- `agile_lineage_and_boards.md` (historical lineage + milestone boards)
- `m008_execution_board.md`, `m011_execution_board.md`, ... (live milestone boards)

3. `api/`
- `planning_api.py` (standardized endpoint-style CRUD for milestones/tasks with safety checks)
- `README.md` (endpoint contract + examples)

## Operating Workflow

1. Start milestone work in a dedicated milestone thread and dedicated milestone branch.
2. Use `ops/planning/api/planning_api.py` to add/update milestone and task records.
3. Keep `milestone_schedule.json.task_ids` aligned with task IDs in active/archived ledgers.
4. Run integrity checks:
   - `uv run python ops/planning/agile/validate_milestone_task_links.py`
5. Milestone completion is only recognized after all milestone thread changes are merged to `main` and required tests pass on `main`.
