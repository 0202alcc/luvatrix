# ADR-009: Input Routing and Scroll Targeting for Multi-Plane Composition

- Status: Accepted
- Date: 2026-03-01
- Milestone: M-008
- Task: T-814
- Owner: Runtime/Input

## 1) Context

With multi-plane composition and section-cut portals, input routing must remain deterministic across:
1. camera-overlay controls,
2. top-plane components,
3. cut-through regions exposing lower planes,
4. nested scrollable layers.

Without explicit routing rules, behavior can vary frame-to-frame and across platforms.

## 2) Decision

Adopt deterministic input routing in two phases:

1. Hit target resolution phase
- Determine top-most eligible interaction target at pointer/touch coordinates.

2. Gesture routing phase
- Bind and route ongoing pointer/scroll gesture to a deterministic target policy.

## 3) Normative Hit-Test Priority

Evaluate in this fixed order:

1. `camera_overlay` components (highest precedence)
2. Plane-attached components by descending `plane_global_z`
3. Within each plane, descending `component_local_z`
4. Stable tie-break: reverse lexical `component_id`

If no component hit is found, event is unhandled unless default plane-scroll fallback applies.

## 4) Section-Cut Pass-Through Rules

For any point inside an active section-cut region in Plane A:

1. Plane A is treated as non-occluding at that point.
2. Hit-test continues to underlying planes in normal priority order.
3. Plane A cannot capture pointer/scroll for that point unless it has an explicit cut-overlay attachment (future extension).

This guarantees that cut regions behave as transparent interaction portals.

## 5) Scroll Target Selection

On `scroll`/`pan`/`swipe` start/update:

1. Resolve candidate stack at event point using hit priority and cut pass-through.
2. Select first target that is scroll-capable and not at hard clamp for intended direction.
3. If selected target consumes only part of delta, remainder bubbles to next eligible lower target.
4. If no eligible target consumes remainder, apply plane-level camera scroll fallback (if enabled).

## 6) Gesture Capture and Stability

1. Pointer press/drag gestures may capture to initial resolved target until release/cancel.
2. Scroll wheel/trackpad updates are re-evaluated per event (location-based), but use same deterministic candidate ordering.
3. Capture cancellation events must release target deterministically.

## 7) Mobile-Ready Semantics

For touch inputs (`pan`, `swipe`):

1. Use same candidate resolution and remainder bubbling as wheel scroll.
2. Keep delta polarity consistent with platform-native direction mapping.
3. Reserve future extension points for inertial fling while preserving deterministic clamp boundaries.

## 8) Failure and Fallback Policy

Strict mode:
1. Invalid cut region references fail validation.
2. Invalid event payload coordinate types fail event handling for that event only.

Permissive mode:
1. Invalid cut region references are ignored with warning.
2. Malformed payload fields coerce to zero where safe; otherwise event ignored.

## 9) Alternatives Considered

1. First-hit-wins with no remainder bubbling.
- Rejected: breaks nested independent scrolling layers.

2. Global active-scroll target sticky for all future events.
- Rejected: makes overlapping/cut-region interactions feel incorrect.

3. Non-deterministic heuristic routing by component type.
- Rejected: hard to test and reason about.

## 10) Consequences

Positive:
1. Predictable behavior for multi-layer scroll interactions.
2. Section-cut model remains both visually and interactively coherent.
3. Strong baseline for desktop and mobile parity.

Trade-offs:
1. More routing state and validation complexity.
2. Additional per-event candidate evaluation cost (mitigated via culling/indexing in T-815+).

## 11) Follow-on Constraints

1. T-815 must incorporate routing cost into culling/perf budget.
2. T-816 schema must encode section-cut ownership and target plane references.
3. T-819 UI IR v2 must expose cut metadata and deterministic hit-test keys.

## 12) Links to Evidence

1. M-008 board: `ops/planning/agile/m008_execution_board.md`
2. Prerequisites: `ADR-006`, `ADR-007`, `ADR-008`
3. Continuation chain: `T-814 -> T-825`
