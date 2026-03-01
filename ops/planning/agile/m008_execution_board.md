# M-008 Execution Board

Milestone: `M-008` Plot + data UX foundations
Epic: `E-801`
Task chain: `T-801 -> T-802 -> T-803 -> T-804 -> T-805` (completed) + `T-806 -> T-807 -> T-808 -> T-809 -> T-810` (scrolling expansion)
Last updated: `2026-03-01`

## Backlog
1. None.

## Ready
1. None.

## In Progress
1. None.

## Review
1. `T-806` Scroll core model (`ScrollState` + clamp math + deterministic offset invariants).
- Evidence: `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_protocol.py tests/test_planes_v2_poc_example.py` (pass).
2. `T-807` Scroll render pipeline (viewport clipping/scissor + translated plane rendering).
- Evidence: `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_protocol.py tests/test_planes_v2_poc_example.py` (pass).
3. `T-808` Unified input/event plumbing for desktop + touch.
- Evidence: `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_protocol.py tests/test_planes_v2_poc_example.py` (pass).
- Notes: Added `ScrollIntent` abstraction path for `scroll` plus touch-compatible event types (`pan`/`swipe`) scaffolding.
4. `T-809` Nested scroll containers + scrollbars/UX affordances.
- Evidence: `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_protocol.py tests/test_planes_v2_poc_example.py` (pass).
- Notes: Added nested viewport scroll remainder bubbling + viewport scrollbars (x/y tracks and thumbs).
5. `T-810` End-to-end arbitrary page/canvas scrolling demos + regression coverage.
- Evidence:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
- `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 8 --fps 60` (pass).
- Demo: `examples/app_protocol/planes_v2_poc` simplified to a single main-plane scrolling surface (no nested/containerized scrolling viewport).

## Done
1. `T-803` Multi-plot support (minimum 2-panel subplot layout in one figure/frame).
- Accepted in review feedback on `2026-02-28`.
- Evidence: `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py` (pass).
2. `T-804` Scrolling/viewport controls for dense x-domains (pan/viewport APIs; optional zoom).
- Accepted in review feedback on `2026-02-28`.
- Evidence: `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py` (pass).
3. `T-801` Sideways/compact x-axis labels for dense long labels.
- Accepted in review feedback on `2026-03-01`.
- Evidence: `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py tests/test_luvatrix_ui_table.py tests/test_plot_app_protocol_example.py` (pass).
4. `T-802` Bar renderer support (`Axes.bar(...)`) with deterministic behavior + non-edge-touching bar padding.
- Accepted in review feedback on `2026-03-01`.
- Evidence: `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py tests/test_luvatrix_ui_table.py tests/test_plot_app_protocol_example.py` (pass).
5. `T-805` Table UI component system (sortable columns, pagination/virtualization, keyboard access, csv/pandas ingestion baseline).
- Accepted in review feedback on `2026-03-01`.
- Evidence: `PYTHONPATH=. uv run pytest tests/test_luvatrix_ui_table.py tests/test_luvatrix_plot.py tests/test_plot_app_protocol_example.py` (pass).
- Demo: `PYTHONPATH=. uv run python examples/m008_plot_data_ux_demo.py` -> `ops/discord/ops/m008_demo_plot_default.png`, `ops/discord/ops/m008_demo_plot_panned.png`, `ops/discord/ops/m008_demo_table.txt`, `ops/discord/ops/m008_demo_positions.csv`, `ops/discord/ops/m008_demo_table.png`.

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
- `PYTHONPATH=. uv run python ops/discord/scripts/generate_gantt_markdown.py --schedule ops/planning/gantt/milestone_schedule.json --out /tmp/m008_smoke_gantt.md`
- `PYTHONPATH=. uv run python ops/discord/scripts/generate_gantt_ascii_detailed.py --schedule ops/planning/gantt/milestone_schedule.json --out /tmp/m008_smoke_gantt_detailed.txt`
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
22. `2026-02-28`: Reworked Luvatrix table demo output from ASCII-rendered text to a structured table-style render (`ops/discord/ops/m008_demo_table.png`) with cell grid/backgrounds and mounted text cells.
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
28. `2026-03-01`: Per review feedback, `T-801`, `T-802`, and `T-805` were moved from `Review` to `In Progress` for label-anchor, bar tick/reference-line, aspect/size, and Luvatrix table visual-output fixes.
29. `2026-03-01`: After test+demo verification passed, `T-801`, `T-802`, and `T-805` were moved back to `Review` pending acceptance.
30. `2026-03-01`: New feedback cycle started; `T-801`, `T-802`, and `T-805` moved from `Review` to `In Progress` for:
- per-bar solid x-grid/tick density enforcement,
- x=0 reference-line gating based on displayed x-rule values only,
- table row-selector positioning refinements.
31. `2026-03-01`: Added strict preferred plot-area aspect control and updated the `M-008` demo to an `AB / C` mosaic with horizontal bar support (`Axes.barh(...)`).
32. `2026-03-01`: Verification rerun passed:
- `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py tests/test_luvatrix_ui_table.py tests/test_plot_app_protocol_example.py`
- `PYTHONPATH=. uv run python examples/m008_plot_data_ux_demo.py`
33. `2026-03-01`: `T-801`, `T-802`, and `T-805` moved back to `Review` pending acceptance after latest fixes and demo refresh.
34. `2026-03-01`: Next feedback cycle started; `T-801` and `T-802` moved from `Review` to `In Progress` for per-bar major tick/grid density restoration and chart-A parity with chart-C bar presentation.
35. `2026-03-01`: Refined viewport panel framing with stronger right-side panel space while preserving strict `4:3` plot-area aspect on the viewport chart.
36. `2026-03-01`: Verification rerun passed and demos refreshed:
- `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py tests/test_luvatrix_ui_table.py tests/test_plot_app_protocol_example.py`
- `PYTHONPATH=. uv run python examples/m008_plot_data_ux_demo.py`
37. `2026-03-01`: `T-801` and `T-802` moved back to `Review`; `T-805` remains in `Review`.
38. `2026-03-01`: Follow-up feedback cycle started; `T-801` and `T-802` moved from `Review` to `In Progress` for four-side framing reserves (top/right/bottom/left) to ensure consistent panel breathing room, including chart-B right-side spacing.
39. `2026-03-01`: Verification rerun passed and demos refreshed:
- `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py tests/test_luvatrix_ui_table.py tests/test_plot_app_protocol_example.py`
- `PYTHONPATH=. uv run python examples/m008_plot_data_ux_demo.py`
40. `2026-03-01`: `T-801` and `T-802` moved back to `Review`; `T-805` remains in `Review` pending final acceptance pass.
41. `2026-03-01`: Final polish cycle started; `T-801` and `T-805` moved from `Review` to `In Progress` for chart-A x-title visibility and table selector symbol refinement.
42. `2026-03-01`: Updated plot gutter clamping to preserve additional bottom headroom for dense rotated x labels so x-axis titles remain visible.
43. `2026-03-01`: Table demo selector glyph changed from open arrow to closed arrow (`▶`) for row focus.
44. `2026-03-01`: Verification rerun passed and demos refreshed:
- `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py tests/test_luvatrix_ui_table.py tests/test_plot_app_protocol_example.py`
- `PYTHONPATH=. uv run python examples/m008_plot_data_ux_demo.py`
45. `2026-03-01`: `T-801` and `T-805` moved back to `Review`; `T-802` remains in `Review`.
46. `2026-03-01`: Table selector marker updated from font glyph to custom SVG triangle to avoid font fallback artifacts in Comic Mono.
47. `2026-03-01`: Verification rerun passed and demo artifacts refreshed:
- `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py tests/test_luvatrix_ui_table.py tests/test_plot_app_protocol_example.py`
- `PYTHONPATH=. uv run python examples/m008_plot_data_ux_demo.py`
48. `2026-03-01`: Table focus indicator refined to a larger in-cell custom SVG arrow for clearer active-row visibility; non-selected row text color darkened for stronger focus contrast.
49. `2026-03-01`: Verification rerun passed and demos refreshed:
- `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py tests/test_luvatrix_ui_table.py tests/test_plot_app_protocol_example.py`
- `PYTHONPATH=. uv run python examples/m008_plot_data_ux_demo.py`
50. `2026-03-01`: Per reviewer request, table focus marker reverted to plain open caret (`>`) for maximum font compatibility and predictable visibility.
51. `2026-03-01`: Verification rerun passed and demo artifacts refreshed:
- `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py tests/test_luvatrix_ui_table.py tests/test_plot_app_protocol_example.py`
- `PYTHONPATH=. uv run python examples/m008_plot_data_ux_demo.py`
52. `2026-03-01`: Final acceptance received for `T-801`, `T-802`, and `T-805`; moved from `Review` to `Done`.
53. `2026-03-01`: `M-008` marked complete. Dependency note: `M-011` depends on `M-008` only; dependency is now satisfied.
54. `2026-03-01`: `M-008` reopened for full arbitrary page/canvas scrolling scope expansion.
55. `2026-03-01`: Added scrolling expansion task breakdown `T-806..T-810`.
56. `2026-03-01`: Aligned implementation model to Planes "camera over canvas" semantics with mobile-ready touch swipe/fling input in task scope (`T-808`).
57. `2026-03-01`: `T-806` moved from `Backlog` to `In Progress`; implementation started on Planes viewport scroll-state/camera offset core.
58. `2026-03-01`: Implemented viewport camera scroll state in `planes_runtime` with deterministic clamp math against content-vs-viewport bounds (`T-806`).
59. `2026-03-01`: Implemented viewport content translation render path with clipping mask composition and content-ref suppression from base draw pass (`T-807`).
60. `2026-03-01`: Added unified scroll intent plumbing in runtime (`ScrollIntent`), mapping desktop scroll plus touch-compatible `pan/swipe` deltas to viewport offsets (`T-808` scaffold).
61. `2026-03-01`: Upgraded `examples/app_protocol/planes_v2_poc` into an arbitrary scrolling showcase (large plane canvas + viewport camera + reset control).
62. `2026-03-01`: Verification passed:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_protocol.py tests/test_planes_v2_poc_example.py`
- `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py tests/test_luvatrix_ui_table.py tests/test_plot_app_protocol_example.py tests/test_planes_runtime.py tests/test_planes_protocol.py tests/test_planes_v2_poc_example.py`
63. `2026-03-01`: `T-806`, `T-807`, and `T-808` moved from `In Progress` to `Review`.
64. `2026-03-01`: `T-809` moved from `Backlog` to `In Progress`; implementing nested scroll bubbling and scrollbar affordances.
65. `2026-03-01`: Added nested viewport scroll remainder bubbling (deepest-first with deterministic remainder propagation).
66. `2026-03-01`: Added viewport scrollbar overlays (x/y track + thumb) for overflow visibility and position feedback.
67. `2026-03-01`: `T-810` moved from `Backlog` to `In Progress`; expanded end-to-end showcase/regression coverage for arbitrary plane scrolling.
68. `2026-03-01`: Verification passed:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_protocol.py tests/test_planes_v2_poc_example.py`
- `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py tests/test_luvatrix_ui_table.py tests/test_plot_app_protocol_example.py tests/test_planes_runtime.py tests/test_planes_protocol.py tests/test_planes_v2_poc_example.py`
69. `2026-03-01`: `T-809` and `T-810` moved from `In Progress` to `Review`.
70. `2026-03-01`: Reviewer feedback on `planes_v2_poc` showcase quality; `T-809` and `T-810` moved back to `In Progress` for visual/layout refinement.
71. `2026-03-01`: Refined `planes_v2_poc` demo visuals/layout for readability:
- replaced unsupported/fragile SVG defs/pattern styling with renderer-safe primitives,
- centered and framed viewport window,
- removed overlapping dual-button layout in favor of single reset control.
72. `2026-03-01`: Verification rerun passed:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_protocol.py tests/test_planes_v2_poc_example.py`
- `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 8 --fps 60`
73. `2026-03-01`: `T-809` and `T-810` moved from `In Progress` back to `Review`.
74. `2026-03-01`: Fixed interactive scrolling capability gate in `planes_v2_poc` by adding `hdi.trackpad` optional capability (macOS scroll events emit as trackpad device).
75. `2026-03-01`: Verification rerun passed:
- `PYTHONPATH=. uv run pytest tests/test_planes_v2_poc_example.py tests/test_planes_runtime.py`
76. `2026-03-01`: Adjusted viewport scroll input polarity to match system-native wheel/trackpad direction expectations.
77. `2026-03-01`: Verification rerun passed:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
78. `2026-03-01`: Reviewer requested reset to checkpoint `fb3cdb7`; `T-810` moved from `Review` back to `In Progress` for a ground-up simplification pass.
79. `2026-03-01`: Started simplified `planes_v2_poc` direction: single main-plane scroll surface only (removed nested/containerized scrolling section from demo layout).
80. `2026-03-01`: Simplified demo implementation completed:
- resized to one near full-page viewport camera (`content_viewport`) with no framed nested/inset viewport,
- refreshed scroll canvas art with deterministic grid/text landmarks for obvious movement cues.
81. `2026-03-01`: Verification rerun passed and `T-810` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
- `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 8 --fps 60`
