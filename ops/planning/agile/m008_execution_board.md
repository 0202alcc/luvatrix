# M-008 Execution Board

Milestone: `M-008` Plot + data UX foundations
Epic: `E-801`
Task chain: `T-801 -> T-802 -> T-803 -> T-804 -> T-805` (completed) + `T-806 -> T-807 -> T-808 -> T-809 -> T-810` (scrolling expansion) + `T-811 -> T-812 -> T-813 -> T-814 -> T-815 -> T-816 -> T-817 -> T-818 -> T-819 -> T-820 -> T-821 -> T-822 -> T-823 -> T-824 -> T-825` (architecture/spec extension)
Last updated: `2026-03-01`

## Backlog
1. `T-824` Demo + verification plan.
2. `T-825` Rollout and compatibility gate plan.

## Ready
1. None.

## In Progress
1. None.

## Review
1. `T-811` Terminology ADR (`MatrixBuffer` output vs `CameraOverlayLayer` concept).
- Evidence:
- `ops/planning/adr/ADR-006-matrixbuffer-cameraoverlay-terminology.md` created (Accepted).
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
2. `T-812` Composition model ADR.
- Evidence:
- `ops/planning/adr/ADR-007-plane-composition-model.md` created (Accepted).
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
3. `T-813` Compositing ADR (`absolute_rgba` / `delta_rgba` + clamp contract).
- Evidence:
- `ops/planning/adr/ADR-008-absolute-delta-rgba-compositing.md` created (Accepted).
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
4. `T-814` Input/scroll routing ADR (section-cut pass-through + nested targeting).
- Evidence:
- `ops/planning/adr/ADR-009-input-routing-and-scroll-targeting.md` created (Accepted).
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
5. `T-815` Camera-relative culling/prefetch ADR.
- Evidence:
- `ops/planning/adr/ADR-010-camera-relative-culling-and-prefetch.md` created (Accepted).
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
6. `T-816` Planes schema vNext spec update.
- Evidence:
- `docs/planes_protocol_vnext.md` created with multi-plane schema additions (`planes[]`, `attachment_kind`, `attach_to`, `component_local_z`, `blend_mode`, `section_cuts[]`, optional `routes[]`) and explicit v0->vNext compatibility mapping.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
7. `T-817` App protocol capability/version update.
- Evidence:
- `docs/app_protocol_v2_superset_spec.md` updated with `[planes]` capability/version signaling (`schema_version`, schema bounds, required/optional features).
- `docs/app_protocol_compatibility_policy.md` updated with Planes schema compatibility policy and migration examples for protocol v2 apps.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
8. `T-818` UI IR gap assessment.
- Evidence:
- `docs/ui_ir_v2_gap_assessment.md` created with ready/partial/missing capability matrix, recommended IR v2 field set, and explicit go/no-go decision.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
9. `T-819` UI IR v2 field contract.
- Evidence:
- `docs/ui_ir_v2_field_contract.md` created with normative v2 page/plane/cut/component fields, deterministic ordering keys, strict/permissive rules, and v0->v2 mapping.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
10. `T-820` IR validation plan + snapshot matrix.
- Evidence:
- `docs/ui_ir_v2_validation_plan.md` created with strict/permissive scenario matrix (`S01..S18`), snapshot determinism rules, CI execution bundle, and compatibility gate criteria.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
11. `T-821` Compiler upgrade design (schema vNext -> IR v2).
- Evidence:
- `docs/ui_ir_v2_compiler_upgrade_design.md` created with parse/normalize/validate/emit pipeline stages, strict/permissive behavior, deterministic diagnostics/order-key contract, and v0->v2 compatibility-lift policy.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
12. `T-822` Runtime pipeline design (matrix compositing + overlay + clamp).
- Evidence:
- `docs/ui_ir_v2_runtime_pipeline_design.md` created with frame-stage pipeline design (active-scene resolve, cull/gather, compose, overlay, affordances), section-cut render/input rules, and blend clamp invariants.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
13. `T-823` Performance execution plan (culling/prefetch/invalidation/cache).
- Evidence:
- `docs/ui_ir_v2_performance_execution_plan.md` created with deterministic culling/prefetch formula, dirty-region invalidation policy, cache key/eviction contract, telemetry budgets, and phased rollout model.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
14. `T-806` Scroll core model (`ScrollState` + clamp math + deterministic offset invariants).
- Evidence: `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_protocol.py tests/test_planes_v2_poc_example.py` (pass).
15. `T-807` Scroll render pipeline (viewport clipping/scissor + translated plane rendering).
- Evidence: `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_protocol.py tests/test_planes_v2_poc_example.py` (pass).
16. `T-808` Unified input/event plumbing for desktop + touch.
- Evidence: `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_protocol.py tests/test_planes_v2_poc_example.py` (pass).
- Notes: Added `ScrollIntent` abstraction path for `scroll` plus touch-compatible event types (`pan`/`swipe`) scaffolding.
17. `T-809` Nested scroll containers + scrollbars/UX affordances.
- Evidence: `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_protocol.py tests/test_planes_v2_poc_example.py` (pass).
- Notes: Added nested viewport scroll remainder bubbling + viewport scrollbars (x/y tracks and thumbs).
18. `T-810` End-to-end arbitrary page/canvas scrolling demos + regression coverage.
- Evidence:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
- `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 8 --fps 60` (pass).
- Demo: `examples/app_protocol/planes_v2_poc` uses full-plane camera scrolling with global bottom/right plane scrollbars indicating current camera position and remaining page extent.

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
82. `2026-03-01`: Reviewer requested true full-page camera model (no inner scroll container); `T-810` moved from `Review` back to `In Progress`.
83. `2026-03-01`: Implemented plane-level camera scrolling fallback in runtime:
- wheel/trackpad scroll now applies to whole plane when no viewport consumes the event,
- non-fixed components render/hit-test through camera offset; `camera_fixed` components stay pinned to screen UI.
84. `2026-03-01`: Rewrote `planes_v2_poc` to camera-over-plane demonstration:
- removed scrollable viewport container from demo,
- added out-of-bounds world components directly in `plane.json` for right/bottom exploration by scroll.
85. `2026-03-01`: Verification rerun passed and `T-810` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
- `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 8 --fps 60`
86. `2026-03-01`: Reviewer-requested usability enhancement started; `T-810` moved from `Review` to `In Progress` to add global page scroll position UI.
87. `2026-03-01`: Added plane-level scrollbars in runtime (bottom + right) for non-viewport page camera scrolling, including thumb sizing/position based on total scrollable extent.
88. `2026-03-01`: Added regression assertions for global plane scrollbar mounts in `tests/test_planes_runtime.py`.
89. `2026-03-01`: Verification rerun passed and `T-810` moved from `In Progress` back to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
- `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 8 --fps 60`
90. `2026-03-01`: Approved strict architecture/spec chain for continuation work: `T-811 -> T-825` (terminology ADR, schema/protocol/UI-IR readiness, compiler/runtime/perf/rollout planning).
91. `2026-03-01`: `T-811` moved from newly approved chain to `In Progress`; `T-812..T-825` placed in `Backlog` in strict dependency order.
92. `2026-03-01`: Created terminology ADR `ops/planning/adr/ADR-006-matrixbuffer-cameraoverlay-terminology.md` with accepted naming contract (`MatrixBuffer` output and `CameraOverlayLayer` overlay concept).
93. `2026-03-01`: Updated ADR index with `ADR-006` entry for discoverability in `ops/discord/artifacts/adr_index.md`.
94. `2026-03-01`: Verification rerun passed and `T-811` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
95. `2026-03-01`: `T-812` started (`Backlog` -> `In Progress`) for composition model ADR definition.
96. `2026-03-01`: Created composition ADR `ops/planning/adr/ADR-007-plane-composition-model.md`:
- global `plane_global_z` ordering,
- local `component_local_z` ordering,
- `CameraOverlayLayer` dominance over all plane-attached content,
- deterministic draw and hit-test ordering contracts with worked examples.
97. `2026-03-01`: Updated ADR index with `ADR-007` entry for composition model traceability.
98. `2026-03-01`: Verification rerun passed and `T-812` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
99. `2026-03-01`: `T-813` started (`Backlog` -> `In Progress`) for absolute/delta RGBA compositing contract.
100. `2026-03-01`: Created compositing ADR `ops/planning/adr/ADR-008-absolute-delta-rgba-compositing.md`:
- `absolute_rgba` and `delta_rgba` mode contracts,
- deterministic ordering interaction with ADR-007,
- explicit clamp policy to keep final MatrixBuffer channels within `[0,255]`.
101. `2026-03-01`: Updated ADR index with `ADR-008` entry for compositing model traceability.
102. `2026-03-01`: Verification rerun passed and `T-813` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
103. `2026-03-01`: `T-814` started (`Backlog` -> `In Progress`) for input/scroll routing ADR.
104. `2026-03-01`: Created routing ADR `ops/planning/adr/ADR-009-input-routing-and-scroll-targeting.md`:
- deterministic hit-test priority across overlay and planes,
- section-cut interaction pass-through contract,
- nested scroll target selection with remainder bubbling and plane-scroll fallback.
105. `2026-03-01`: Updated ADR index with `ADR-009` entry for routing traceability.
106. `2026-03-01`: Verification rerun passed and `T-814` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
107. `2026-03-01`: `T-815` started (`Backlog` -> `In Progress`) for camera-relative culling and prefetch ADR.
108. `2026-03-01`: Created performance ADR `ops/planning/adr/ADR-010-camera-relative-culling-and-prefetch.md`:
- camera-visible region culling model,
- deterministic predictive margin formula based on platform max scroll rate,
- dirty-region and optional tile-cache policy with performance telemetry gates.
109. `2026-03-01`: Updated ADR index with `ADR-010` entry for performance policy traceability.
110. `2026-03-01`: Verification rerun passed and `T-815` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
111. `2026-03-01`: `T-816` started (`Backlog` -> `In Progress`) for Planes schema vNext spec update.
112. `2026-03-01`: Created schema vNext spec `docs/planes_protocol_vnext.md` with:
- top-level `planes[]` contract replacing single-plane-only shape,
- explicit component attachment fields (`attachment_kind`, `attach_to`),
- local/global ordering fields (`component_local_z`, `plane_global_z`),
- compositing declaration (`blend_mode`) and section-cut schema (`section_cuts[]`),
- explicit backward compatibility mapping (`v0 -> vNext`).
113. `2026-03-01`: Updated root README documentation index to include `docs/planes_protocol_vnext.md`.
114. `2026-03-01`: Verification rerun passed and `T-816` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
115. `2026-03-01`: `T-817` started (`Backlog` -> `In Progress`) for App Protocol capability/version update.
116. `2026-03-01`: Updated App Protocol specs for Planes vNext capability signaling:
- `docs/app_protocol_v2_superset_spec.md` adds optional `[planes]` table (`schema_version`, `min_schema_version`, `max_schema_version`, `required_features`, `optional_features`),
- `docs/app_protocol_compatibility_policy.md` adds Planes schema compatibility policy and migration guidance.
117. `2026-03-01`: Verification rerun passed and `T-817` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
118. `2026-03-01`: `T-818` started (`Backlog` -> `In Progress`) for UI IR readiness/gap assessment.
119. `2026-03-01`: Created `docs/ui_ir_v2_gap_assessment.md`:
- capability matrix (`Ready`/`Partial`/`Missing`) against vNext requirements,
- explicit minimum IR v2 field set proposal,
- go/no-go recommendation (no-go until `T-819` and `T-820` gates complete).
120. `2026-03-01`: Updated root README documentation index to include `docs/ui_ir_v2_gap_assessment.md`.
121. `2026-03-01`: Verification rerun passed and `T-818` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
122. `2026-03-01`: `T-819` started (`Backlog` -> `In Progress`) for UI IR v2 field contract definition.
123. `2026-03-01`: Created `docs/ui_ir_v2_field_contract.md` with:
- normative `planes-v2` page/plane/section-cut/component field contracts,
- deterministic ordering-key contract and compositing field rules,
- strict/permissive validation behavior and v0->v2 compatibility mapping.
124. `2026-03-01`: Updated root README documentation index to include `docs/ui_ir_v2_field_contract.md`.
125. `2026-03-01`: Verification rerun passed and `T-819` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
126. `2026-03-01`: `T-820` started (`Backlog` -> `In Progress`) for UI IR validation/snapshot matrix planning.
127. `2026-03-01`: Created `docs/ui_ir_v2_validation_plan.md` with:
- strict/permissive scenario matrix (`S01..S18`) across schema/compiler/runtime paths,
- deterministic snapshot rules and golden artifact policy,
- compatibility gate criteria and CI command bundle for rollout.
128. `2026-03-01`: Updated root README documentation index to include `docs/ui_ir_v2_validation_plan.md`.
129. `2026-03-01`: Verification rerun passed and `T-820` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
130. `2026-03-01`: `T-821` started (`Backlog` -> `In Progress`) for compiler upgrade design (schema vNext -> UI IR v2).
131. `2026-03-01`: Created `docs/ui_ir_v2_compiler_upgrade_design.md` with:
- deterministic parse/normalize/validate/emit pipeline stages,
- strict/permissive compiler behavior and diagnostics contract,
- stable order-key construction and v0->v2 compatibility-lift design.
132. `2026-03-01`: Updated root README documentation index to include `docs/ui_ir_v2_compiler_upgrade_design.md`.
133. `2026-03-01`: Verification rerun passed and `T-821` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
134. `2026-03-01`: `T-822` started (`Backlog` -> `In Progress`) for runtime pipeline design (matrix compositing + overlay + clamp).
135. `2026-03-01`: Created `docs/ui_ir_v2_runtime_pipeline_design.md` with:
- deterministic frame-stage compose pipeline (`resolve -> cull/gather -> compose -> overlay -> affordances -> emit`),
- section-cut render/input routing contract,
- `absolute_rgba` / `delta_rgba` blend + clamp semantics and telemetry hooks.
136. `2026-03-01`: Updated root README documentation index to include `docs/ui_ir_v2_runtime_pipeline_design.md`.
137. `2026-03-01`: Verification rerun passed and `T-822` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
138. `2026-03-01`: `T-823` started (`Backlog` -> `In Progress`) for performance execution planning (culling/prefetch/invalidation/cache).
139. `2026-03-01`: Created `docs/ui_ir_v2_performance_execution_plan.md` with:
- deterministic prefetch margin formula and dirty-region invalidation rules,
- cache key/eviction policy and memory guardrails,
- telemetry budgets and staged enablement strategy.
140. `2026-03-01`: Updated root README documentation index to include `docs/ui_ir_v2_performance_execution_plan.md`.
141. `2026-03-01`: Verification rerun passed and `T-823` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
