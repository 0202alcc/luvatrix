# ADR-007: Plane Composition Model (Global Plane Z + Local Component Z + Overlay Dominance)

- Status: Accepted
- Date: 2026-03-01
- Milestone: M-008
- Task: T-812
- Owner: Runtime/Protocol

## 1) Context

M-008 continuation requires a formal composition model for multi-plane rendering, input routing, and scroll layering.

Without an explicit model, runtime behavior can drift across schema, UI IR, and renderer implementations.

`ADR-006` already fixed terminology (`MatrixBuffer`, `CameraOverlayLayer`). This ADR defines how planes and components compose into final MatrixBuffer output.

## 2) Decision

Adopt a two-level ordering model:

1. Global ordering across planes
- Every Plane has `plane_global_z`.
- Higher `plane_global_z` renders above lower `plane_global_z`.

2. Local ordering inside a plane
- Every component has `component_local_z`.
- Higher `component_local_z` renders above lower `component_local_z` within that same plane.

3. Overlay dominance
- `CameraOverlayLayer` is rendered after all Plane content.
- Any component attached to `camera_overlay` renders above all Plane-attached components regardless of z values.

## 3) Normative Render Order

Render order key is deterministic and stable:

1. `attachment_kind` (`plane` before `camera_overlay`)
2. `plane_global_z` (ascending)
3. `component_local_z` (ascending)
4. stable tiebreaker (`component_id` lexical)

This yields deterministic draw results across repeated runs.

## 4) Input and Hit-Test Order

Hit-testing is the reverse of render order (top-most first), with section-cut rules from the routing ADR applied afterward:

1. `camera_overlay` components first (highest visual precedence)
2. Plane components by descending `plane_global_z`
3. Within each plane, descending `component_local_z`
4. Stable tiebreaker by reverse lexical `component_id` to preserve determinism

## 5) Plane Relative Positioning

A Plane may be positioned relative to another Plane using explicit anchor + offset metadata.

Required invariants:
1. Relative transforms are resolved before draw/hit ordering.
2. Relative transforms do not alter ordering keys.
3. Cyclic parent references are invalid and must fail validation in strict mode.

## 6) Section-Cut Composition Contract

Section cuts create transparent portals in an upper plane that expose lower plane content.

Rules:
1. A cut region in Plane A removes A's visual occupancy in that region.
2. Underlying planes remain renderable and interactive through the cut.
3. Input in cut regions routes to the next eligible lower layer, not the cut owner.

## 7) Worked Draw-Order Examples

Example A:
- Plane `index` (`plane_global_z=10`) with component `button` (`component_local_z=100`)
- Plane `plot` (`plane_global_z=5`) with component `line` (`component_local_z=999`)

Result:
- `button` still renders above `line` because plane precedence is global-first.

Example B:
- Plane `index` component `button` (`component_local_z=100`)
- `camera_overlay` component `hud_hint` (`component_local_z=-1000`)

Result:
- `hud_hint` renders above `button` because overlay dominance overrides plane-local z.

## 8) Alternatives Considered

1. Single flat global z for all components.
- Rejected: loses clean plane semantics and complicates routing/cuts.

2. Ignore overlay dominance and compare overlay z numerically with planes.
- Rejected: breaks top-layer UX expectations and increases ambiguity.

3. Per-plane independent compositors with no shared ordering contract.
- Rejected: non-deterministic cross-plane behavior and weak testability.

## 9) Consequences

Positive:
1. Deterministic, testable layering behavior.
2. Clear separation between world content and fixed UI overlay.
3. Strong foundation for section-cut and multi-scroll layer routing.

Trade-offs:
1. Additional schema/IR fields and validation complexity.
2. Existing assumptions around local-only z ordering must be migrated.

## 10) Follow-on Constraints for T-813+

1. T-813 blend rules must preserve this ordering before compositing.
2. T-816 schema must represent `plane_global_z`, `component_local_z`, `attachment_kind`.
3. T-819 UI IR v2 must emit stable order keys exactly matching this ADR.

## 11) Links to Evidence

1. M-008 board: `ops/planning/agile/m008_execution_board.md`
2. Terminology prerequisite: `ops/planning/adr/ADR-006-matrixbuffer-cameraoverlay-terminology.md`
3. Continuation chain: `T-812 -> T-825`
