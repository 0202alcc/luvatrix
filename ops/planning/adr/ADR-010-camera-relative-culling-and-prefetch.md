# ADR-010: Camera-Relative Culling and Prefetch Policy

- Status: Accepted
- Date: 2026-03-01
- Milestone: U-017
- Task: T-815
- Owner: Runtime/Performance

## 1) Context

As plane sizes and component counts grow, rendering full-plane content each frame increases latency and causes visible scroll lag.

U-017 goals require smooth deterministic scrolling while preserving correctness in multi-plane composition.

## 2) Decision

Adopt camera-relative render budgeting with deterministic culling and predictive prefetch:

1. Visible-first rendering
- Render only content intersecting the MatrixBuffer-visible world region.

2. Predictive prefetch margin
- Extend visible region by a deterministic margin based on platform max scroll rate and frame horizon.

3. Dirty-region and optional tile cache
- Re-render only dirty/intersecting regions when possible.
- Optionally cache tile rasters for expensive static regions.

## 3) Normative Culling Model

For each active plane:

1. Compute camera-visible rect in plane/world coordinates: `V`.
2. Compute prefetch margin rect `M` around `V`.
3. Effective render rect is `R = expand(V, M)`.
4. A component is eligible iff its world bounds intersect `R`.
5. Non-eligible components are skipped for draw this frame.

Determinism requirements:
1. Use fixed-point or deterministic rounding for all rect transforms.
2. Use stable component iteration order from ADR-007.
3. Culling predicates must be pure and side-effect free.

## 4) Prefetch Margin Formula

Base policy:
- `margin_x = ceil(max_scroll_px_per_sec_x * horizon_sec)`
- `margin_y = ceil(max_scroll_px_per_sec_y * horizon_sec)`

With minimum floor:
- `margin_x >= min_margin_px`
- `margin_y >= min_margin_px`

Recommended defaults:
1. `horizon_sec = 0.100`
2. `min_margin_px = 32`
3. Platform max scroll rate sourced from capability profile, otherwise deterministic fallback constants.

## 5) Dirty-Region Policy

1. Mark dirty on:
- component state/style changes,
- camera offset changes,
- route/plane activation changes,
- section-cut geometry changes.

2. Dirty region computation:
- union of old and new component/camera affected bounds.

3. Render budget:
- if dirty union area exceeds threshold, fall back to full eligible `R` render for that plane.

## 6) Optional Tile Cache Policy

Tile cache is optional but standardized if enabled:

1. Fixed tile size per backend profile (for example `128x128`).
2. Cache key must include:
- plane id,
- tile coordinates,
- relevant style/version hash,
- compositing mode,
- theme/route state hash.

3. Eviction policy:
- deterministic LRU with hard memory cap.

4. Any cache miss/hit must preserve identical final MatrixBuffer output.

## 7) Interaction with Input Routing

To avoid routing cost spikes:
1. Maintain cull-friendly spatial indexing for hit candidates in `R` when possible.
2. Keep hit-test ordering semantics from ADR-009 unchanged.
3. Do not use heuristic shortcuts that alter deterministic routing outcome.

## 8) Telemetry and Performance Gates

Record per-frame counters:
1. components_total
2. components_culled
3. components_drawn
4. tiles_hit / tiles_miss (if cache enabled)
5. frame_render_ms

Initial acceptance targets (baseline, adjustable by platform profile):
1. Culling effectiveness: `components_culled / components_total >= 0.50` for oversized demo scenes.
2. No regression in deterministic render snapshots.
3. No input routing correctness regressions.

## 9) Alternatives Considered

1. Always render full planes.
- Rejected: unacceptable scaling and scroll lag.

2. Aggressive heuristic culling without deterministic rounding.
- Rejected: visual jitter and snapshot instability risk.

3. Prefetch disabled entirely.
- Rejected: causes visible pop-in during fast scroll.

## 10) Consequences

Positive:
1. Lower per-frame render cost for large scenes.
2. Better scroll smoothness with bounded prefetch.
3. Predictable behavior suitable for CI snapshot tests.

Trade-offs:
1. More runtime bookkeeping complexity.
2. Additional configuration/tuning surface by platform.

## 11) Follow-on Constraints

1. T-816 schema must expose optional performance/culling hints in a deterministic contract.
2. T-819 UI IR v2 must carry world bounds and culling hints.
3. T-823 implementation plan must map these policies to measurable runtime gates.

## 12) Links to Evidence

1. U-017 board: `ops/planning/agile/m008_execution_board.md`
2. Prerequisites: `ADR-006`, `ADR-007`, `ADR-008`, `ADR-009`
3. Continuation chain: `T-815 -> T-825`
