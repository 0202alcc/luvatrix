# M-008 Execution Board

Milestone: `M-008` Plot + data UX foundations
Epic: `E-801`
Task chain: `T-801 -> T-802 -> T-803 -> T-804 -> T-805`
Last updated: `2026-03-01`

## Backlog
1. None.

## Ready
1. None.

## In Progress
1. None.

## Review
1. `T-801` Sideways/compact x-axis labels for dense long labels.
- Evidence: `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py tests/test_luvatrix_ui_table.py tests/test_plot_app_protocol_example.py` (pass).
2. `T-802` Bar renderer support (`Axes.bar(...)`) with deterministic behavior + non-edge-touching bar padding.
- Evidence: `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py tests/test_luvatrix_ui_table.py tests/test_plot_app_protocol_example.py` (pass).
3. `T-805` Table UI component system (sortable columns, pagination/virtualization, keyboard access, csv/pandas ingestion baseline).
- Evidence: `PYTHONPATH=. uv run pytest tests/test_luvatrix_ui_table.py tests/test_luvatrix_plot.py tests/test_plot_app_protocol_example.py` (pass).
- Demo: `PYTHONPATH=. uv run python examples/m008_plot_data_ux_demo.py` -> `discord/ops/m008_demo_plot_default.png`, `discord/ops/m008_demo_plot_panned.png`, `discord/ops/m008_demo_table.txt`, `discord/ops/m008_demo_positions.csv`, `discord/ops/m008_demo_table.png`.

## Done
1. `T-803` Multi-plot support (minimum 2-panel subplot layout in one figure/frame).
- Accepted in review feedback on `2026-02-28`.
- Evidence: `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py` (pass).
2. `T-804` Scrolling/viewport controls for dense x-domains (pan/viewport APIs; optional zoom).
- Accepted in review feedback on `2026-02-28`.
- Evidence: `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py` (pass).

## Evidence Log
1. `2026-02-28`: Board initialized for `M-008`; `T-801` started.
2. `2026-02-28`: `T-801` moved to `Review` after deterministic x-label layout updates and plot test pass.
3. `2026-02-28`: `T-802` started after `T-801` review handoff.
4. `2026-02-28`: `T-802` moved to `Review` after deterministic bar-render tests passed.
5. `2026-02-28`: `T-803` started after `T-802` review handoff.
6. `2026-02-28`: `T-803` moved to `Review` after subplot compatibility tests passed.
7. `2026-02-28`: `T-804` started after `T-803` review handoff.
8. `2026-02-28`: `T-804` moved to `Review` after viewport clamp/alignment tests passed.
9. `2026-02-28`: `T-805` started after `T-804` review handoff.
10. `2026-02-28`: `T-805` moved to `Review` after table sort/pagination/virtualization/keyboard tests passed.
11. `2026-02-28`: `M-008` runnable demo generated successfully via `examples/m008_plot_data_ux_demo.py`.
12. `2026-02-28`: Existing Discord Gantt scripts smoke check passed:
- `PYTHONPATH=. uv run python discord/scripts/generate_gantt_markdown.py --schedule discord/ops/milestone_schedule.json --out /tmp/m008_smoke_gantt.md`
- `PYTHONPATH=. uv run python discord/scripts/generate_gantt_ascii_detailed.py --schedule discord/ops/milestone_schedule.json --out /tmp/m008_smoke_gantt_detailed.txt`
13. `2026-02-28`: Review feedback received; `T-802` and `T-803` accepted and moved to `Done`.
14. `2026-02-28`: `T-801`, `T-804`, and `T-805` moved back to `In Progress` for requested fixes (angled/italic compact labels, viewport clipping/tick accuracy, csv/pandas table ingestion).
15. `2026-02-28`: `T-801`, `T-804`, and `T-805` returned to `Review` after updated tests and demo regeneration passed.
16. `2026-02-28`: Additional review feedback received; `T-804` accepted and moved to `Done`.
17. `2026-02-28`: `T-802` reopened after bar-edge spacing feedback; moved from `Done` back to active fix scope.
18. `2026-02-28`: Implemented label-to-bar emphasized x ticks, bar edge padding, subplot preferred-aspect auto sizing, and Luvatrix-rendered table PNG demo.
19. `2026-02-28`: `T-802` returned to `Review`; refreshed demo artifacts and reran full M-008 regression test set.
20. `2026-02-28`: Applied follow-up review refinements:
- rotated-label anchor behavior updated so angled labels align to the tick endpoint,
- bar charts now retain tick alignment at each bar by default while label thinning remains deterministic,
- zero-reference x/y lines now render only when `0` is an actual displayed tick value.
21. `2026-02-28`: Added default subplot preferred aspect behavior (`4:3` for line/scatter panels unless explicitly overridden) and deterministic subplot auto-sizing lock.
22. `2026-02-28`: Reworked Luvatrix table demo output from ASCII-rendered text to a structured table-style render (`discord/ops/m008_demo_table.png`) with cell grid/backgrounds and mounted text cells.
23. `2026-02-28`: Verification rerun passed:
- `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py tests/test_luvatrix_ui_table.py tests/test_plot_app_protocol_example.py`
- `PYTHONPATH=. uv run python examples/m008_plot_data_ux_demo.py`
24. `2026-03-01`: Applied review-driven chart readability/layout refinements:
- angled x labels now anchor to tick endpoints (right-anchored rotated text) with extra left gutter protection,
- zero-reference x/y rules now render only when `0` is an actual displayed tick,
- bar plots retain per-bar major ticks by default even when label thinning is active.
25. `2026-03-01`: Added subplot default preferred-aspect handling for line/scatter panels (`4:3`) while preserving explicit per-panel overrides.
26. `2026-03-01`: Updated demo rendering to show Luvatrix-native structured table output (grid/cells/header text) instead of ASCII-only table visuals.
27. `2026-03-01`: Verification rerun passed:
- `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py tests/test_luvatrix_ui_table.py tests/test_plot_app_protocol_example.py`
- `PYTHONPATH=. uv run python examples/m008_plot_data_ux_demo.py`
