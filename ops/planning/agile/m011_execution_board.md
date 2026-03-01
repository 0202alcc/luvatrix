# M-011 Execution Board

Milestone: `M-011` Native Gantt + Agile visualization in Luvatrix
Epic: `E-1101`
Task chain: `T-1101 -> T-1102 -> T-1103 -> T-1104 -> T-1105 -> T-1106`
Last updated: `2026-03-01` (reopened)

## Success Criteria (Mandatory)
1. `M-011` implementations must follow the first-party Luvatrix App Protocol contract (no external UI framework coupling for runtime flows).
2. Contracts must be represented as first-party `luvatrix_ui.planning` types and exported through `luvatrix_ui`.
3. Visualization flows must remain runnable through first-party runtime-compatible outputs (ASCII/Markdown/PNG) with deterministic results.
4. Completion requires explicit App Protocol compliance evidence (schema/renderer/interaction/export/validation behavior proven under first-party workflow commands).

## Acceptance Checks by Task
1. `T-1101`: Schema contract includes milestone/task/dependency/owner fields and strict status validation; tests prove canonical parse/load behavior and first-party type export.
2. `T-1102`: Gantt renderer produces deterministic axis/status/dependency output with collapsed/expanded lanes and remains callable from first-party planning modules.
3. `T-1103`: Agile renderer produces deterministic board columns/swimlanes/blocker views and remains first-party module-only (no third-party UI runtime dependency).
4. `T-1104`: Filtering/zoom/scroll/click-through interactions are deterministic, clamped, and compatible with first-party planning state types.
5. `T-1105`: Export adapters produce ASCII/Markdown/PNG artifacts plus Discord payload manifest from first-party planning models.
6. `T-1106`: Validation suite enforces dependency integrity + render consistency and blocks completion on App Protocol compliance evidence.

## Backlog
1. None.

## Ready
1. None.

## In Progress
1. `T-1101` Define canonical timeline/task schema for Gantt + Agile cards (milestones, tasks, status, deps, owners).
2. `T-1102` Build Luvatrix Gantt renderer (time axis, status colors, dependency lines, collapsed/expanded lanes).
3. `T-1103` Build Luvatrix Agile board renderer (Backlog/Ready/In Progress/Review/Done, swimlanes, blockers).
4. `T-1104` Add interaction layer (filtering, zoom/scroll, click-through from milestone -> task cards).
5. `T-1105` Add export adapters (ASCII/Markdown/PNG) and Discord posting payload compatibility.
6. `T-1106` Add validation suite (render correctness, dependency integrity, snapshot/regression tests).

## Review
1. None.

## Done
1. None.

## Completion Gate
1. Milestone `M-011` is **reopened** and not complete.
2. Completion is blocked pending App Protocol-compliant acceptance checks across `T-1101..T-1106`.

## Evidence Log
1. `2026-02-28`: Board initialized for Phase 1. `T-1101` and `T-1102` moved to `In Progress`.
2. `2026-02-28`: `T-1101` and `T-1102` moved to `Review` after tests and demo generation passed.
3. `2026-02-28`: Existing Discord scripts smoke check passed:
- `uv run python ops/discord/scripts/generate_gantt_markdown.py --schedule ops/planning/gantt/milestone_schedule.json --out /tmp/m011_smoke_gantt.md`
- `uv run python ops/discord/scripts/generate_gantt_ascii_detailed.py --schedule ops/planning/gantt/milestone_schedule.json --out /tmp/m011_smoke_gantt_detailed.txt`
4. `2026-02-28`: `T-1103` moved to `In Progress` to continue M-011 implementation while M-008 progresses in a separate thread.
5. `2026-02-28`: `T-1103` moved to `Review` after agile renderer tests passed.
6. `2026-02-28`: `T-1104` moved to `In Progress`.
7. `2026-02-28`: `T-1104` moved to `Review` after interaction-layer tests passed.
8. `2026-02-28`: `T-1105` moved to `In Progress`.
9. `2026-02-28`: `T-1105` moved to `Review` after exporter tests and demo artifacts passed.
10. `2026-02-28`: `T-1106` moved to `In Progress`.
11. `2026-02-28`: `T-1106` moved to `Review` after validation-suite tests passed.
12. `2026-02-28`: Full M-011 demo rerun passed:
- `uv run python examples/m011_native_gantt_demo.py` -> `ops/discord/ops/m011_native_gantt_demo.txt`, `ops/discord/ops/m011_native_exports/*`.
13. `2026-02-28`: Existing Discord scripts smoke check passed after M-011 updates:
- `uv run python ops/discord/scripts/generate_gantt_markdown.py --schedule ops/planning/gantt/milestone_schedule.json --out /tmp/m011_postchange_gantt.md`
- `uv run python ops/discord/scripts/generate_gantt_ascii_detailed.py --schedule ops/planning/gantt/milestone_schedule.json --out /tmp/m011_postchange_gantt_detailed.txt`
14. `2026-02-28`: Full M-011 suite rerun passed (`20/20`) and demo export rerun passed.
15. `2026-02-28`: `T-1101..T-1106` moved from `Review` to `Done` by request, with milestone completion gate held pending post-merge `M-008` integration validation.
16. `2026-03-01`: Post-merge integration gate passed:
- `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py tests/test_luvatrix_ui_table.py tests/test_plot_app_protocol_example.py tests/test_luvatrix_ui_agile_renderer.py tests/test_luvatrix_ui_planning_interaction.py tests/test_luvatrix_ui_planning_exporters.py tests/test_luvatrix_ui_planning_validation.py tests/test_luvatrix_ui_planning_schema.py tests/test_luvatrix_ui_gantt_renderer.py` (`87 passed`)
- `PYTHONPATH=. uv run python examples/m008_plot_data_ux_demo.py`
- `uv run python examples/m011_native_gantt_demo.py`
- `uv run python ops/discord/scripts/generate_gantt_markdown.py --schedule ops/planning/gantt/milestone_schedule.json --out /tmp/m011_complete_gate_gantt.md`
- `uv run python ops/discord/scripts/generate_gantt_ascii_detailed.py --schedule ops/planning/gantt/milestone_schedule.json --out /tmp/m011_complete_gate_gantt_detailed.txt`
17. `2026-03-01`: Completion gate closed; milestone `M-011` marked complete.
18. `2026-03-01`: Milestone reopened by directive; `T-1101..T-1106` moved back to `In Progress`, completion gate re-enabled.
19. `2026-03-01`: Success criteria updated: first-party App Protocol compliance is mandatory, with explicit acceptance checks added for `T-1101..T-1106`.
20. `2026-03-01`: First-party App Protocol success criteria + `T-1101..T-1106` acceptance checks synchronized into `ops/planning/gantt/milestone_schedule.json` and `ops/planning/gantt/milestones_gantt.md`.
