# U-017 Execution Board

Milestone: `U-017` Plot + data UX foundations
Epic: `E-801`
Task chain: `T-801 -> T-802 -> T-803 -> T-804 -> T-805` (completed) + `T-806 -> T-807 -> T-808 -> T-809 -> T-810` (scrolling expansion) + `T-811 -> T-812 -> T-813 -> T-814 -> T-815 -> T-816 -> T-817 -> T-818 -> T-819 -> T-820 -> T-821 -> T-822 -> T-823 -> T-824 -> T-825` (architecture/spec extension) + `T-826 -> T-827 -> T-828 -> T-829 -> T-830 -> T-831 -> T-832 -> T-833 -> T-834 -> T-835` (scroll performance hardening) + `T-836 -> T-837 -> T-838 -> T-839 -> T-840` (scroll runtime acceleration follow-up)
Last updated: `2026-03-02`

## Backlog
1. `T-837` Pre-rasterized bitmap cache path for stable SVG/text during camera scrolling.
2. `T-838` Frame-paced scroll scheduler (coalesced input to fixed render cadence updates).
3. `T-839` Input ingestion/render decoupling via deterministic intent queue handoff.
4. `T-840` Scroll performance validation pack (latency/jitter budgets + visual artifact regression gates).

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
- Implementation follow-up:
- `luvatrix_ui/planes_protocol.py` now compiles true `planes-v2` payloads (`planes[]`, routes, section-cuts metadata, attachment/blend fields) and preserves `planes-v0` compatibility path.
- `PYTHONPATH=. uv run pytest tests/test_planes_protocol.py tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
12. `T-822` Runtime pipeline design (matrix compositing + overlay + clamp).
- Evidence:
- `docs/ui_ir_v2_runtime_pipeline_design.md` created with frame-stage pipeline design (active-scene resolve, cull/gather, compose, overlay, affordances), section-cut render/input rules, and blend clamp invariants.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
- Implementation follow-up:
- `luvatrix_ui/planes_runtime.py` now applies v2 attachment semantics at runtime (`camera_overlay` dominance, active-plane filtering, plane-manifest position offsets) while preserving scrolling behavior.
- `PYTHONPATH=. uv run pytest tests/test_planes_protocol.py tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
13. `T-823` Performance execution plan (culling/prefetch/invalidation/cache).
- Evidence:
- `docs/ui_ir_v2_performance_execution_plan.md` created with deterministic culling/prefetch formula, dirty-region invalidation policy, cache key/eviction contract, telemetry budgets, and phased rollout model.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
14. `T-824` Demo + verification plan.
- Evidence:
- `docs/ui_ir_v2_demo_verification_plan.md` created with scenario checklist (`D01..D05`), demo artifact expectations, verification command bundle, acceptance criteria, and failure triage playbook.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
15. `T-825` Rollout and compatibility gate plan.
- Evidence:
- `docs/ui_ir_v2_rollout_compatibility_gate_plan.md` created with gate matrix (`G1..G5`), phased rollout (`R0..R4`), rollback controls, and CI release-readiness checklist.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
16. `T-806` Scroll core model (`ScrollState` + clamp math + deterministic offset invariants).
- Evidence: `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_protocol.py tests/test_planes_v2_poc_example.py` (pass).
17. `T-807` Scroll render pipeline (viewport clipping/scissor + translated plane rendering).
- Evidence: `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_protocol.py tests/test_planes_v2_poc_example.py` (pass).
18. `T-808` Unified input/event plumbing for desktop + touch.
- Evidence: `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_protocol.py tests/test_planes_v2_poc_example.py` (pass).
- Notes: Added `ScrollIntent` abstraction path for `scroll` plus touch-compatible event types (`pan`/`swipe`) scaffolding.
19. `T-809` Nested scroll containers + scrollbars/UX affordances.
- Evidence: `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_protocol.py tests/test_planes_v2_poc_example.py` (pass).
- Notes: Added nested viewport scroll remainder bubbling + viewport scrollbars (x/y tracks and thumbs).
20. `T-810` End-to-end arbitrary page/canvas scrolling demos + regression coverage.
- Evidence:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
- `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 8 --fps 60` (pass).
- Demo: `examples/app_protocol/planes_v2_poc` uses full-plane camera scrolling with global bottom/right plane scrollbars indicating current camera position and remaining page extent.
- 2026-03-02 refinement: `planes_v2_poc` now models a web-like vertical page with a mid-page section-cut viewport.
- In this viewport, nested lower-plane content scrolls only when pointer is inside the section cut; outside it, wheel/trackpad scroll applies to the main page camera.
- Verification for refinement:
  - `PYTHONPATH=. uv run pytest tests/test_planes_v2_poc_example.py tests/test_planes_runtime.py` (pass).
  - `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 12 --fps 60` (pass).
- Follow-up optimization pass:
- added deterministic camera-region culling + prefetch margin handling and SVG markup caching in `luvatrix_ui/planes_runtime.py`,
- added regression coverage for offscreen culling and cache reuse in `tests/test_planes_runtime.py`,
- verified behavior parity with:
  - `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass),
  - `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 8 --fps 60` (pass).
- v2 schema/runtime path follow-up:
- `examples/app_protocol/planes_v2_poc/plane.json` migrated to `planes-v2` shape (`planes[]`, routes, per-component attachment declarations),
- runtime smoke and tests confirm `planes_v2_poc` compiles through `ir_version=planes-v2` while keeping visual behavior.
- Foundation rebuild follow-up (`2026-03-02`):
  - rebuilt demo from scratch as requested: `index` plane sized `100vw x 300vh`, top-to-bottom dark-blue→white gradient background, centered square section-cut viewport scaffold.
  - added assets: `assets/index_plane_gradient.svg`, `assets/underlay_content.svg`, `assets/section_cut_frame.svg`.
  - updated example metadata expectation in `tests/test_planes_v2_poc_example.py`.
  - verification:
    - `PYTHONPATH=. uv run pytest tests/test_planes_v2_poc_example.py tests/test_planes_runtime.py` (pass).
    - `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 12 --fps 60` (pass).
- Centering correction follow-up (`2026-03-02`):
  - section-cut placement now computed at init using exact matrix geometry so the square is centered against full `100vw x 300vh` plane bounds.
  - added explicit regression test: `test_section_cut_is_centered_against_100vw_by_300vh_plane`.
  - verification:
    - `PYTHONPATH=. uv run pytest tests/test_planes_v2_poc_example.py tests/test_planes_runtime.py` (pass).
    - `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 12 --fps 60` (pass).
- Visual fidelity correction follow-up (`2026-03-02`):
  - replaced unsupported SVG `linearGradient` background with deterministic stepped-band gradient (`assets/index_plane_gradient.svg`) to ensure visible dark-blue→white transition at runtime.
  - pixel-snapped section-cut square geometry (`x/y/side`) to remove seam artifacts caused by sub-pixel cutout boundaries.
  - verification:
    - `PYTHONPATH=. uv run pytest tests/test_planes_v2_poc_example.py tests/test_planes_runtime.py` (pass).
    - `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 12 --fps 60` (pass).
- Hole + blend refinement follow-up (`2026-03-02`):
  - section cut now reveals a plain white underlay surface (`assets/underlay_content.svg`) so it reads as a true square hole.
  - gradient smoothness improved by increasing vertical band density and color interpolation steps in `assets/index_plane_gradient.svg`.
  - verification:
    - `PYTHONPATH=. uv run pytest tests/test_planes_v2_poc_example.py tests/test_planes_runtime.py` (pass).
    - `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 12 --fps 60` (pass).
- Programmatic gradient follow-up (`2026-03-02`):
  - gradient now generated at app init from code (`app_main.py`) using per-pixel color interpolation against actual runtime matrix geometry.
  - generated asset `assets/index_plane_gradient_runtime.svg` is bound to `index_gradient_bg` before compile for smooth blending.
  - added regression test: `test_runtime_gradient_asset_is_generated_and_bound`.
  - verification:
    - `PYTHONPATH=. uv run pytest tests/test_planes_v2_poc_example.py tests/test_planes_runtime.py` (pass).
    - `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 12 --fps 60` (pass).
- Plane simplification follow-up (`2026-03-02`):
  - removed dedicated `underlay` plane from `planes_v2_poc`.
  - set `index` plane `plane_global_z` to `0`.
  - retained section-cut viewport behavior by attaching `underlay_content` to `index` and keeping `content_ref` wiring.
  - verification:
    - `PYTHONPATH=. uv run pytest tests/test_planes_v2_poc_example.py tests/test_planes_runtime.py` (pass).
    - `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 12 --fps 60` (pass).
- Component simplification follow-up (`2026-03-02`):
  - removed dedicated `underlay_content` component from demo scene graph.
  - rewired `section_cut.props.content_ref` to reuse `index_gradient_bg` directly.
  - verification:
    - `PYTHONPATH=. uv run pytest tests/test_planes_v2_poc_example.py tests/test_planes_runtime.py` (pass).
    - `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 12 --fps 60` (pass).
21. `T-826` Frame-time instrumentation pack (input/hit-test/scroll-update/cull/mount/raster/present + counters).
- Evidence:
- `luvatrix_ui/planes_runtime.py` now records per-frame timing buckets (`input`, `hit_test`, `scroll_update`, `cull`, `mount`, `raster`, `present`, `frame_total`) plus frame counters (`events_polled`, `events_processed`, `scroll_events`, `hit_test_calls`) in `state["perf"]`.
- `tests/test_planes_runtime.py` adds metrics contract coverage for stage keys and non-negative timing/counter values.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
22. `T-827` HDI scroll event coalescing + phase/momentum propagation contract.
- Evidence:
- `luvatrix_ui/planes_runtime.py` now coalesces per-frame `scroll`/`pan`/`swipe` events into one intent update and one `on_scroll` dispatch while preserving aggregated deltas.
- Coalesced payloads now carry `coalesced_count` and phase metadata (`phase`, `momentum_phase`) through to handlers; perf counters include `scroll_events_coalesced`.
- `luvatrix_core/platform/macos/hdi_source.py` now emits native scroll metadata (`phase`, `momentum_phase`, `precise`) for protocol consumers.
- `tests/test_planes_runtime.py` adds coalescing + metadata propagation coverage (`2 events -> 1 handler call` with summed deltas).
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
23. `T-828` Retained mount graph (incremental node updates, reduced per-frame object churn).
- Evidence:
- `luvatrix_ui/planes_runtime.py` now uses a retained mount cache for text/svg nodes and reuses previously-built component objects when render keys are unchanged.
- Runtime perf counters expose `retained_components_reused` and `retained_components_new` to quantify churn reduction.
- `tests/test_planes_runtime.py` adds identity reuse coverage for unchanged consecutive frames.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
24. `T-829` Standardized CameraOverlay scrollbar primitives (no per-frame ad-hoc SVG generation).
- Evidence:
- `luvatrix_ui/planes_runtime.py` now mounts both page and viewport scrollbars through a shared camera-overlay primitive helper (`_mount_camera_overlay_scrollbar_pair`) with standardized visual tokens/markup.
- Scrollbar markup strings are prebuilt once per app lifecycle and reused (`self._scrollbar_markups`) instead of being generated ad hoc per mount path.
- Runtime perf counters include `camera_overlay_scrollbar_primitives` for mounted primitive visibility.
- `tests/test_planes_runtime.py` validates primitive counter presence alongside scrollbar mount IDs.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
25. `T-830` True dirty-region compose path (partial redraw + unchanged-region reuse).
- Evidence:
- `luvatrix_core/core/app_runtime.py` now accepts normalized `dirty_rects` per UI frame and emits `ReplaceRect` write ops for partial present; full-frame rewrite remains the fallback.
- `luvatrix_ui/planes_runtime.py` now computes deterministic dirty regions, emits `compose_mode` telemetry (`full_frame` / `partial_dirty` / `idle_skip`), and skips compose work entirely when nothing changed.
- `tests/test_planes_runtime.py` adds idle-skip and partial-dirty regression coverage; fake context updated for dirty-rect frame API.
- `tests/test_planes_v2_poc_example.py` updated for idle-skip-compatible revision assertion semantics.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
26. `T-831` Hit-test acceleration index (spatial partitioning).
- Evidence:
- `luvatrix_ui/planes_runtime.py` now builds and reuses a deterministic spatial hit-test bucket index (cell-based partitioning) keyed by camera/viewport scroll state and active planes.
- Event dispatch now uses bucket-filtered candidates for both direct hit target selection and viewport stack resolution, with index refresh on post-scroll retargeting.
- Runtime perf counters now expose `hit_test_candidates_checked` and `hit_test_spatial_buckets`.
- `tests/test_planes_runtime.py` validates new counter visibility in the frame instrumentation contract.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
27. `T-832` Transform/layout cache invalidation model (recompute-on-change only).
- Evidence:
- `luvatrix_ui/planes_runtime.py` now caches resolved component transforms and interaction bounds with deterministic cache keys and signature-based invalidation.
- Layout cache invalidation is triggered only when required state changes (`plane_scroll`, active planes), otherwise cached layout/transform values are reused.
- Runtime perf counters now expose `layout_cache_hits` and `layout_cache_misses`.
- `tests/test_planes_runtime.py` validates layout cache counter visibility via runtime perf contract assertions.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
28. `T-833` Renderer batch optimization pass (state-change minimization and draw grouping).
- Evidence:
- `luvatrix_ui/planes_runtime.py` now stages non-viewport drawables through a deterministic batch mount pass with contiguous grouping by draw-state key.
- Batch telemetry is exposed via `renderer_batch_groups` and `renderer_batch_state_switches` perf counters.
- Existing render ordering remains stable (no cross-z reordering), while mount-path branch churn is reduced through grouped execution.
- `tests/test_planes_runtime.py` instrumentation assertions include renderer batch perf fields.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
29. `T-834` Native hot-path extraction plan (optional C/Rust acceleration boundaries).
- Evidence:
- `docs/ui_ir_v2_native_hot_path_extraction_plan.md` created with extraction boundaries for dirty-compose, hit-index, layout transform, and scrollbar geometry hot loops.
- Plan defines deterministic ABI contract, parity rollout strategy, fallback model, and exit criteria for native acceleration enablement.
- `README.md` documentation index updated to include the new plan doc.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py` (pass).
30. `T-835` CI performance gate pack (p95 frame-time/jitter budgets + deterministic perf smoke).
- Evidence:
- Added `ops/ci/m008_perf_gate.py` deterministic perf smoke script with two-pass replay parity checks plus p95/jitter budget enforcement.
- Added `tests/test_m008_perf_gate.py` for perf-gate contract coverage.
- Added `.github/workflows/m008-perf-gate.yml` CI workflow gate for runtime tests + perf smoke budgets.
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py tests/test_m008_perf_gate.py` (pass).
- `PYTHONPATH=. uv run python ops/ci/m008_perf_gate.py --samples 60 --budget-p95-ms 40 --budget-jitter-ms 25` (pass).
31. `T-836` Shift-blit camera scroll compose path (translate previous frame + redraw exposed strips).
- Evidence:
- `luvatrix_core/core/window_matrix.py` now supports `ShiftFrame` write op for deterministic matrix translation with fill color.
- `luvatrix_core/core/app_runtime.py` now accepts `scroll_shift` hints and emits `ShiftFrame + ReplaceRect` batches on dirty-frame finalize.
- `luvatrix_ui/planes_runtime.py` now emits corrected scroll-direction strip dirty rects and shift hints for plane-scroll translation.
- Added/updated coverage:
  - `tests/test_window_matrix_protocol.py` (`ShiftFrame` semantics),
  - `tests/test_app_runtime.py` (shift+patch UI finalize path),
  - `tests/test_planes_runtime.py` (partial-dirty + scroll-shift hint contract),
  - `ops/ci/m008_perf_gate.py` context signature update.
- `PYTHONPATH=. uv run pytest tests/test_window_matrix_protocol.py tests/test_app_runtime.py tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py tests/test_m008_perf_gate.py` (pass).
- `PYTHONPATH=. uv run python ops/ci/m008_perf_gate.py --samples 60 --budget-p95-ms 40 --budget-jitter-ms 25` (pass).

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
1. `2026-02-28`: Board initialized for `U-017`; `T-801` started.
2. `2026-02-28`: `T-801` moved to `Review` after deterministic x-label layout updates and plot test pass.
3. `2026-02-28`: `T-802` started after `T-801` review handoff.
4. `2026-02-28`: `T-802` moved to `Review` after deterministic bar-render tests passed.
5. `2026-02-28`: `T-803` started after `T-802` review handoff.
6. `2026-02-28`: `T-803` moved to `Review` after subplot compatibility tests passed.
7. `2026-02-28`: `T-804` started after `T-803` review handoff.
8. `2026-02-28`: `T-804` moved to `Review` after viewport clamp/alignment tests passed.
9. `2026-02-28`: `T-805` started after `T-804` review handoff.
10. `2026-02-28`: `T-805` moved to `Review` after table sort/pagination/virtualization/keyboard tests passed.
11. `2026-02-28`: `U-017` runnable demo generated successfully via `examples/m008_plot_data_ux_demo.py`.
12. `2026-02-28`: Existing Discord Gantt scripts smoke check passed:
- `PYTHONPATH=. uv run python ops/discord/scripts/generate_gantt_markdown.py --schedule ops/planning/gantt/milestone_schedule.json --out /tmp/m008_smoke_gantt.md`
- `PYTHONPATH=. uv run python ops/discord/scripts/generate_gantt_ascii_detailed.py --schedule ops/planning/gantt/milestone_schedule.json --out /tmp/m008_smoke_gantt_detailed.txt`
13. `2026-02-28`: Review feedback received; `T-802` and `T-803` accepted and moved to `Done`.
14. `2026-02-28`: `T-801`, `T-804`, and `T-805` moved back to `In Progress` for requested fixes (angled/italic compact labels, viewport clipping/tick accuracy, csv/pandas table ingestion).
15. `2026-02-28`: `T-801`, `T-804`, and `T-805` returned to `Review` after updated tests and demo regeneration passed.
16. `2026-02-28`: Additional review feedback received; `T-804` accepted and moved to `Done`.
17. `2026-02-28`: `T-802` reopened after bar-edge spacing feedback; moved from `Done` back to active fix scope.
18. `2026-02-28`: Implemented label-to-bar emphasized x ticks, bar edge padding, subplot preferred-aspect auto sizing, and Luvatrix-rendered table PNG demo.
19. `2026-02-28`: `T-802` returned to `Review`; refreshed demo artifacts and reran full U-017 regression test set.
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
31. `2026-03-01`: Added strict preferred plot-area aspect control and updated the `U-017` demo to an `AB / C` mosaic with horizontal bar support (`Axes.barh(...)`).
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
53. `2026-03-01`: `U-017` marked complete. Dependency note: `APU-020` depends on `U-017` only; dependency is now satisfied.
54. `2026-03-01`: `U-017` reopened for full arbitrary page/canvas scrolling scope expansion.
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
142. `2026-03-01`: `T-824` started (`Backlog` -> `In Progress`) for demo + verification planning.
143. `2026-03-01`: Created `docs/ui_ir_v2_demo_verification_plan.md` with:
- required command bundle for runtime + demo smoke checks,
- scenario checklist (`D01..D05`) and acceptance criteria,
- failure triage and release-review deliverable packaging guidance.
144. `2026-03-01`: Updated root README documentation index to include `docs/ui_ir_v2_demo_verification_plan.md`.
145. `2026-03-01`: Verification rerun passed and `T-824` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
146. `2026-03-01`: `T-825` started (`Backlog` -> `In Progress`) for rollout/compatibility gate planning.
147. `2026-03-01`: Created `docs/ui_ir_v2_rollout_compatibility_gate_plan.md` with:
- phased rollout model (`R0..R4`) and compatibility gate matrix (`G1..G5`),
- rollback triggers/switches and CI command requirements,
- release-readiness checklist and audit-trail requirements.
148. `2026-03-01`: Updated root README documentation index to include `docs/ui_ir_v2_rollout_compatibility_gate_plan.md`.
149. `2026-03-01`: Verification rerun passed and `T-825` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
150. `2026-03-01`: `T-810` follow-up optimization pass implemented for `planes_v2_poc` runtime performance parity:
- deterministic camera-space culling with configurable prefetch margins,
- per-path SVG markup caching to avoid repeated disk reads each frame.
151. `2026-03-01`: Added regression tests in `tests/test_planes_runtime.py` for offscreen culling and cache reuse; verification passed:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
- `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 8 --fps 60`
152. `2026-03-01`: Implemented full `planes-v2` compiler/runtime schema path:
- `luvatrix_ui/planes_protocol.py` now supports v2 compile/validation (`planes[]`, route activation, attachment semantics, deterministic v2 ordering metadata) while preserving v0 path.
- `luvatrix_ui/ui_ir.py` extended with v2 page/plane/section/component fields (`active_plane_ids`, `plane_manifest`, `attachment_kind`, `blend_mode`, etc.).
153. `2026-03-01`: Runtime semantics aligned to v2:
- `luvatrix_ui/planes_runtime.py` respects `camera_overlay` attachment behavior, active-plane filtering, and plane-manifest positional offsets.
- `examples/app_protocol/planes_v2_poc/plane.json` migrated to native v2 payload.
154. `2026-03-01`: Added/updated regression coverage and verification passed:
- `PYTHONPATH=. uv run pytest tests/test_planes_protocol.py tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
- `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 8 --fps 60`
155. `2026-03-01`: Performance hardening chain approved and added in strict order: `T-826 -> T-827 -> T-828 -> T-829 -> T-830 -> T-831 -> T-832 -> T-833 -> T-834 -> T-835`.
156. `2026-03-01`: `T-826` started (`Backlog` -> `In Progress`) for frame-time instrumentation across runtime stages.
157. `2026-03-01`: Implemented runtime perf stage instrumentation in `luvatrix_ui/planes_runtime.py`:
- per-frame stage timings for `input/hit_test/scroll_update/cull/mount/raster/present/frame_total`,
- per-frame counters for events and hit-test usage.
158. `2026-03-01`: Added regression coverage in `tests/test_planes_runtime.py` for instrumentation contract (required stage keys and non-negative values).
159. `2026-03-01`: Verification rerun passed and `T-826` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
160. `2026-03-01`: `T-827` started (`Backlog` -> `In Progress`) for HDI scroll coalescing + phase/momentum propagation.
161. `2026-03-01`: Implemented per-frame scroll coalescing in `luvatrix_ui/planes_runtime.py`:
- aggregates `scroll`/`pan`/`swipe` events into one deterministic intent update and one `on_scroll` dispatch per frame,
- propagates metadata (`phase`, `momentum_phase`, `coalesced_count`) and adds `scroll_events_coalesced` perf counter.
162. `2026-03-01`: Added macOS source metadata for scroll protocol payloads in `luvatrix_core/platform/macos/hdi_source.py` (`phase`, `momentum_phase`, `precise`) and added regression coverage in `tests/test_planes_runtime.py`.
163. `2026-03-01`: Verification rerun passed and `T-827` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
164. `2026-03-01`: `T-828` started (`Backlog` -> `In Progress`) for retained mount graph implementation.
165. `2026-03-01`: Implemented retained mount cache in `luvatrix_ui/planes_runtime.py`:
- added deterministic mount keys for text/svg nodes,
- reused component objects across unchanged frames,
- exposed churn counters (`retained_components_reused`, `retained_components_new`) in perf metrics.
166. `2026-03-01`: Added regression coverage in `tests/test_planes_runtime.py` for unchanged-frame mount object identity reuse.
167. `2026-03-01`: Verification rerun passed and `T-828` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
168. `2026-03-01`: `T-829` started (`Backlog` -> `In Progress`) for standardized camera-overlay scrollbar primitive implementation.
169. `2026-03-01`: Replaced ad-hoc scrollbar mount code in `luvatrix_ui/planes_runtime.py` with a shared primitive helper and prebuilt markup token set for page + viewport scrollbars.
170. `2026-03-01`: Added regression assertion in `tests/test_planes_runtime.py` for `camera_overlay_scrollbar_primitives` metric visibility.
171. `2026-03-01`: Verification rerun passed and `T-829` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
172. `2026-03-02`: `T-830` started (`Backlog` -> `In Progress`) for true dirty-region compose path (partial redraw + unchanged-region reuse).
173. `2026-03-02`: Implemented dirty-region compose plumbing:
- `luvatrix_core/core/app_runtime.py` now supports normalized per-frame `dirty_rects` and emits `ReplaceRect` operations for partial present.
- `luvatrix_ui/planes_runtime.py` now computes deterministic dirty rectangles, supports compose idle-skip, and records compose-mode / dirty-area telemetry.
174. `2026-03-02`: Verification rerun passed and `T-830` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
175. `2026-03-02`: `T-831` started (`Backlog` -> `In Progress`) for hit-test acceleration index implementation.
176. `2026-03-02`: Implemented spatial partition hit-test path in `luvatrix_ui/planes_runtime.py`:
- deterministic cell-bucket index keyed by scroll/active-plane signature,
- bucket-scoped candidate checks for event hit testing and viewport stack resolution,
- perf counters for candidate checks and spatial bucket count.
177. `2026-03-02`: Verification rerun passed and `T-831` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
178. `2026-03-02`: `T-832` started (`Backlog` -> `In Progress`) for transform/layout cache invalidation implementation.
179. `2026-03-02`: Added deterministic layout cache in `luvatrix_ui/planes_runtime.py`:
- resolved-position and interaction-bounds caches with stable keys,
- explicit invalidation on layout signature changes (`plane_scroll`, active planes),
- perf telemetry counters (`layout_cache_hits`, `layout_cache_misses`).
180. `2026-03-02`: Verification rerun passed and `T-832` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
181. `2026-03-02`: `T-833` started (`Backlog` -> `In Progress`) for renderer batch optimization pass.
182. `2026-03-02`: Implemented deterministic contiguous draw batching in `luvatrix_ui/planes_runtime.py` for non-viewport primitives with batch-state telemetry (`renderer_batch_groups`, `renderer_batch_state_switches`).
183. `2026-03-02`: Verification rerun passed and `T-833` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
184. `2026-03-02`: `T-834` started (`Backlog` -> `In Progress`) for native hot-path extraction planning.
185. `2026-03-02`: Added `docs/ui_ir_v2_native_hot_path_extraction_plan.md` and linked it in `README.md` with deterministic ABI boundaries, parity gates, and rollout/fallback strategy.
186. `2026-03-02`: Verification rerun passed and `T-834` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py`
187. `2026-03-02`: `T-835` started (`Backlog` -> `In Progress`) for CI perf gate pack implementation.
188. `2026-03-02`: Added performance-gate artifacts:
- `ops/ci/m008_perf_gate.py` deterministic two-pass perf smoke with p95/jitter budget checks,
- `tests/test_m008_perf_gate.py` perf-gate contract test,
- `.github/workflows/m008-perf-gate.yml` CI gate workflow.
189. `2026-03-02`: Verification rerun passed and `T-835` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py tests/test_m008_perf_gate.py`
- `PYTHONPATH=. uv run python ops/ci/m008_perf_gate.py --samples 60 --budget-p95-ms 40 --budget-jitter-ms 25`
190. `2026-03-02`: Added follow-up scroll acceleration chain in strict order: `T-836 -> T-837 -> T-838 -> T-839 -> T-840`.
191. `2026-03-02`: `T-836` started (`Backlog` -> `In Progress`) for shift-blit camera scroll compose.
192. `2026-03-02`: Implemented shift-blit compose path:
- added `ShiftFrame` operation in `WindowMatrix`,
- wired `AppContext.begin_ui_frame(..., scroll_shift=...)` and shift+patch finalize path,
- restored and corrected scroll-direction dirty strip mapping in `planes_runtime`.
193. `2026-03-02`: Verification rerun passed and `T-836` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_window_matrix_protocol.py tests/test_app_runtime.py tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py tests/test_m008_perf_gate.py`
- `PYTHONPATH=. uv run python ops/ci/m008_perf_gate.py --samples 60 --budget-p95-ms 40 --budget-jitter-ms 25`
194. `2026-03-02`: Reviewer-requested `planes_v2_poc` interaction-model rework started; `T-810` moved from `Review` to `In Progress` to enforce web-like main-page scrolling plus section-cut nested scrolling.
195. `2026-03-02`: Reworked `examples/app_protocol/planes_v2_poc/plane.json` into a single-page vertical scroll surface with a mid-page viewport section cut backed by lower-plane content (`detail_canvas` -> `section_cut_content.svg`).
196. `2026-03-02`: Updated `tests/test_planes_v2_poc_example.py` metadata assertions for renamed demo (`Planes v2 Web Scroll + Section Cut Demo`).
197. `2026-03-02`: Verification rerun passed and `T-810` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_v2_poc_example.py tests/test_planes_runtime.py`
- `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 12 --fps 60`
198. `2026-03-02`: Reviewer requested ground-up foundation reset for demo shape; `T-810` moved from `Review` to `In Progress`.
199. `2026-03-02`: Rebuilt `planes_v2_poc` foundation with single `index` page plane (`100vw x 300vh`), gradient background (`dark blue -> white`), and centered square section cut scaffold.
200. `2026-03-02`: Verification rerun passed and `T-810` moved from `In Progress` to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_v2_poc_example.py tests/test_planes_runtime.py`
- `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 12 --fps 60`
201. `2026-03-02`: Reviewer clarified section-cut must be centered against full plane bounds (`100vw x 300vh`); `T-810` moved from `Review` to `In Progress` for exact geometry correction.
202. `2026-03-02`: Implemented deterministic init-time centering pass in `examples/app_protocol/planes_v2_poc/app_main.py`:
- computes `plane_h = 3 * window_h`,
- computes square side from viewport height baseline,
- applies centered `x/y` and equal `width/height` to `section_cut` and `section_cut_frame`.
203. `2026-03-02`: Added centering regression test in `tests/test_planes_v2_poc_example.py`.
204. `2026-03-02`: Verification rerun passed and `T-810` moved from `In Progress` back to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_v2_poc_example.py tests/test_planes_runtime.py`
- `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 12 --fps 60`
205. `2026-03-02`: Reviewer reported seam artifact around centered square and missing gradient rendering; `T-810` moved from `Review` to `In Progress` for visual fidelity correction.
206. `2026-03-02`: Implemented visual corrections:
- replaced unsupported gradient primitive with stepped solid-band gradient asset,
- snapped section-cut geometry to integer pixels to avoid cutout seam lines.
207. `2026-03-02`: Verification rerun passed and `T-810` moved from `In Progress` back to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_v2_poc_example.py tests/test_planes_runtime.py`
- `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 12 --fps 60`
208. `2026-03-02`: Reviewer requested true hole behavior in section cut and smoother gradient blend; `T-810` moved from `Review` to `In Progress`.
209. `2026-03-02`: Updated visual assets:
- `assets/underlay_content.svg` changed to solid white fill for hole readability,
- `assets/index_plane_gradient.svg` refined to denser stepped blend.
210. `2026-03-02`: Verification rerun passed and `T-810` moved from `In Progress` back to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_v2_poc_example.py tests/test_planes_runtime.py`
- `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 12 --fps 60`
211. `2026-03-02`: Reviewer requested explanation of lower-plane behavior and smoother blend path; `T-810` moved from `Review` to `In Progress` for gradient-programmability update.
212. `2026-03-02`: Implemented runtime-generated gradient path in `examples/app_protocol/planes_v2_poc/app_main.py` and added binding regression coverage in `tests/test_planes_v2_poc_example.py`.
213. `2026-03-02`: Verification rerun passed and `T-810` moved from `In Progress` back to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_v2_poc_example.py tests/test_planes_runtime.py`
- `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 12 --fps 60`
214. `2026-03-02`: Reviewer requested removing underlay plane and setting `index` z-order baseline; `T-810` moved from `Review` to `In Progress`.
215. `2026-03-02`: Simplified scene graph to single plane (`index`, `plane_global_z=0`) and removed `underlay` plane from active route list.
216. `2026-03-02`: Verification rerun passed and `T-810` moved from `In Progress` back to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_v2_poc_example.py tests/test_planes_runtime.py`
- `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 12 --fps 60`
217. `2026-03-02`: Reviewer requested removing dedicated cutout-fill component; `T-810` moved from `Review` to `In Progress`.
218. `2026-03-02`: Simplified viewport source model by removing `underlay_content` and referencing `index_gradient_bg` directly from `section_cut`.
219. `2026-03-02`: Verification rerun passed and `T-810` moved from `In Progress` back to `Review`:
- `PYTHONPATH=. uv run pytest tests/test_planes_v2_poc_example.py tests/test_planes_runtime.py`
- `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 12 --fps 60`
