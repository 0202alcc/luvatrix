# UI IR v2 Native Hot-Path Extraction Plan (T-834)

Status: Proposed
Milestone: M-008
Task: T-834
Date: 2026-03-02

## Goal
Define deterministic extraction boundaries for optional native acceleration (C/Rust) in the Planes v2 runtime so high-frequency scroll + compose paths can be offloaded without changing protocol semantics.

## Non-Goals
- No protocol/schema changes in this task.
- No immediate C/Rust build integration in this task.
- No behavior changes to rendering order, hit-test semantics, or event routing.

## Candidate Native Hot Paths
1. Dirty-rect compose kernels
- Inputs: RGBA frame, rect list, rect payloads.
- Output: updated RGBA frame with clamped channel math.
- Why native: memory-copy heavy contiguous loops.

2. Spatial hit-index build/query
- Inputs: component bounds, cell size, point query.
- Output: deterministic candidate id list in z-resolved order.
- Why native: repeated bucket assignment + lookup on dense scenes.

3. Layout transform pass
- Inputs: component transform state, plane/camera offsets.
- Output: resolved positions/bounds cache records.
- Why native: predictable arithmetic over large arrays.

4. Scrollbar geometry pass
- Inputs: viewport size/content size/scroll offsets.
- Output: track/thumb rects.
- Why native: small but frequent arithmetic called per frame.

## Boundary Contract
Native modules must be pure functions over explicit buffers/struct arrays:
- No hidden global state.
- Stable ordering of outputs.
- Deterministic tie-breaking preserved from Python contracts.
- Input/output schema versioned independently from Planes schema.

## ABI/API Shape
Phase 1 target: Python C-ABI extension boundary with opaque handles avoided.
- `compose_dirty(frame, rects, patches) -> frame`
- `build_hit_index(bounds, cell_px) -> index_blob`
- `query_hit_index(index_blob, x, y) -> candidate_ids`
- `resolve_layout(transforms, plane_scroll, active_planes) -> resolved_layout`

Equivalent Rust FFI surface can mirror the same schema.

## Determinism Rules
- Same inputs must produce bit-identical outputs on supported platforms.
- Float handling normalized via explicit rounding points where Python currently rounds.
- Output arrays sorted by deterministic keys before returning to Python.
- Clamp rules remain identical to existing RGBA channel contracts.

## Rollout Plan
1. Mirror mode
- Run native and Python paths side-by-side in tests and compare outputs.

2. Feature-flagged opt-in
- `LUVATRIX_NATIVE_HOTPATHS=1` enables native path per module.

3. Progressive enablement
- Start with dirty-compose and hit-index.
- Add layout pass once parity thresholds are stable.

4. Fallback on mismatch
- Any parity mismatch auto-falls back to Python path and emits telemetry.

## Verification Strategy
- Snapshot parity tests against Python baseline for representative scenes.
- Event-sequence determinism replay (`scroll/pan/swipe` traces).
- Frame-time and jitter telemetry comparison before/after toggle.

## Risks
- Cross-platform floating-point drift.
- ABI maintenance burden.
- Build complexity for local/dev CI environments.

## Mitigations
- Keep boundary minimal and data-oriented.
- Require strict parity gates before default-on.
- Maintain Python fallback as first-class runtime path.

## Exit Criteria
- Documented stable ABI for first extracted module.
- Parity test harness merged and green.
- Performance delta demonstrates meaningful p95 improvement without behavioral regressions.
