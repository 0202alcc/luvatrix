# UI IR v2 Performance Execution Plan (T-823)

Status: Draft plan (2026-03-01)
Milestone: M-008
Task: T-823

## 1) Purpose

Define the execution strategy for performance-sensitive runtime behavior under `planes-v2`, with deterministic culling, prefetch margining, invalidation policy, and cache boundaries.

## 2) Performance Goals

1. Keep frame composition deterministic under heavy component counts.
2. Avoid rendering components that cannot influence the current camera-visible frame.
3. Bound scroll hitching by prefetching near-camera content.
4. Preserve correctness first; optimizations must not change visual or input semantics.

## 3) Optimization Layers

Layer A. Visibility culling
1. Compute camera-visible bounds for each active plane.
2. Expand by prefetch margins (horizontal/vertical).
3. Cull components with no intersection against expanded bounds.

Layer B. Dirty-region invalidation
1. Recompose only regions affected by:
- scroll offset changes,
- component state mutation,
- route/plane activation changes.
2. Maintain deterministic region merge strategy (sorted union by x/y origin).

Layer C. Command/tile caching
1. Cache deterministic raster outputs for stable components (optional by policy).
2. Cache keys include:
- component content hash,
- style hash,
- transform/scale state,
- blend mode.
3. Invalidate cache entries on any key change.

Layer D. Prefetch scheduling
1. Predict near-future visible region from velocity and platform max scroll rate.
2. Prepare command buffers for next likely frame.
3. Do not prefetch beyond deterministic memory ceilings.

## 4) Deterministic Prefetch Margin Formula

Given:
1. `v_max_x`, `v_max_y` = platform max scroll rate (pixels/frame)
2. `k_prefetch_frames` = fixed horizon (integer)
3. `m_base_x`, `m_base_y` = static safety margins

Formula:
1. `margin_x = m_base_x + (v_max_x * k_prefetch_frames)`
2. `margin_y = m_base_y + (v_max_y * k_prefetch_frames)`

All constants must be fixed per platform profile and emitted in diagnostics.

## 5) Invalidation Rules

1. Scroll-only update:
- invalidate newly exposed strips only.
2. Local component update:
- invalidate component previous bounds union new bounds.
3. Plane transform/position update:
- invalidate entire affected plane viewport.
4. Route switch:
- invalidate full frame.

## 6) Cache Policy

1. Default policy: command-cache enabled, tile-cache optional.
2. Eviction: deterministic LRU with stable tie-break by cache key lexical order.
3. Memory guardrails:
- cap cache bytes by profile,
- disable tile-cache first when limit reached,
- preserve command-cache correctness path.

## 7) Telemetry and Budgets

Per-frame required metrics:
1. `components_total`
2. `components_culled`
3. `commands_emitted`
4. `cache_hit_ratio`
5. `invalidated_pixels`
6. `compose_time_ms`
7. `prefetch_time_ms`

Gate thresholds (initial proposal):
1. p95 `compose_time_ms` within target profile budget.
2. culling ratio improves with off-camera-heavy scenes.
3. no deterministic output drift with cache on/off.

## 8) Validation Strategy

1. Determinism checks:
- run same fixture twice with same inputs; assert identical output hash and metrics order.
2. Performance checks:
- compare baseline (no cache/prefetch) vs optimized path.
3. Correctness checks:
- verify snapshot parity between optimization modes.

## 9) Rollout Strategy

1. Phase 1: ship metrics-only mode (optimizations disabled, counters enabled).
2. Phase 2: enable culling + invalidation.
3. Phase 3: enable command-cache.
4. Phase 4: optional tile-cache + prefetch on supported profiles.

Each phase is gated by T-825 compatibility and determinism checks.

## 10) Risks and Mitigations

1. Risk: stale cache artifacts.
- Mitigation: strict cache key contracts + invalidation-on-uncertainty fallback.

2. Risk: prefetch memory growth.
- Mitigation: profile ceilings + deterministic eviction.

3. Risk: hidden nondeterminism from timing races.
- Mitigation: single-threaded deterministic compose path by default; parallel paths behind explicit deterministic merge rules.

## 11) Evidence

1. `ops/planning/adr/ADR-010-camera-relative-culling-and-prefetch.md`
2. `docs/ui_ir_v2_runtime_pipeline_design.md`
3. `docs/ui_ir_v2_validation_plan.md`
4. `ops/planning/agile/m008_execution_board.md`
