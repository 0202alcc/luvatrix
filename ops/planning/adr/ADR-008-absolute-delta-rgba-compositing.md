# ADR-008: Absolute and Delta RGBA Compositing Contract

- Status: Accepted
- Date: 2026-03-01
- Milestone: U-017
- Task: T-813
- Owner: Runtime/Rendering

## 1) Context

U-017 continuation introduces component-level compositing modes where a component can either:
1. write explicit RGBA values, or
2. apply RGBA deltas over already-composited pixels.

Without a formal contract, behavior may vary across renderer backends, causing non-deterministic visuals and broken test parity.

## 2) Decision

Define two compositing modes for component pixel output:

1. `absolute_rgba`
- Component emits explicit pixel channels in `[0, 255]`.
- Pixel written by normal alpha compositing at its ordered layer position.

2. `delta_rgba`
- Component emits per-channel signed deltas in `[-255, 255]`.
- Delta is applied to the current destination pixel after underlying layers are resolved.

## 3) Normative Pixel Math

Given destination pixel `D = (Dr, Dg, Db, Da)` and component sample `S`:

1. `absolute_rgba`
- Use deterministic alpha-over compositing with integer channel domain.
- Result channel values are rounded by fixed rule (`round-half-up`) and clamped to `[0, 255]`.

2. `delta_rgba`
- For each channel `c in {r,g,b,a}`:
  - `Rc = clamp_0_255(Dc + Delta_c)`
- `Delta_c` must be integer or quantized deterministically to integer before application.

3. Clamp function
- `clamp_0_255(x) = min(255, max(0, x))`

## 4) Deterministic Ordering Constraint

Compositing evaluation order follows ADR-007 ordering exactly:
1. Plane-attached layers by global/local z + stable tiebreak
2. CameraOverlayLayer last

`delta_rgba` is applied at the exact point its component is encountered in this deterministic order.

## 5) Representation Contract

1. `absolute_rgba`
- Source data contract: channels in `[0,255]`.

2. `delta_rgba`
- Source data contract: channels in `[-255,255]`.
- Any out-of-range source must be clamped/validated before blend application.

3. Backend portability
- Backends using float math must quantize deterministically to integer channel space at compositing boundaries.

## 6) Worked Examples

Example A: absolute overwrite tendency
- Destination `D=(100,100,100,255)`
- Source absolute sample `S=(200,50,20,255)`
- Result approximates source at full alpha, final channels clamped `[0,255]`.

Example B: positive delta
- Destination `D=(240,10,20,255)`
- Delta `(+30,+5,-50,0)`
- Result `R=(255,15,0,255)`

Example C: negative alpha delta
- Destination `D=(80,90,100,20)`
- Delta `(0,0,0,-60)`
- Result `R=(80,90,100,0)`

## 7) Validation and Failure Policy

1. Strict mode
- Reject invalid blend mode values.
- Reject non-numeric channels.
- Reject malformed delta payloads.

2. Permissive mode
- Unknown blend mode falls back to `absolute_rgba` with warning.
- Invalid channels are clamped/sanitized deterministically.

## 8) Alternatives Considered

1. Support only absolute compositing.
- Rejected: blocks lightweight post-effect layers and color-manipulation overlays.

2. Allow unconstrained delta ranges beyond `[-255,255]`.
- Rejected: unnecessary and increases portability risk.

3. Use floating-point open-ended color domain.
- Rejected: weak determinism for cross-platform snapshot testing.

## 9) Consequences

Positive:
1. Clear and testable compositing semantics.
2. Deterministic backend behavior with explicit clamp rules.
3. Enables richer visual effects without abandoning matrix integer semantics.

Trade-offs:
1. Additional validation and conversion overhead in runtime/compiler.
2. Requires explicit IR fielding for blend mode and numeric contract.

## 10) Follow-on Constraints for T-816/T-819+

1. T-816 schema must expose `blend_mode` and channel domain constraints.
2. T-819 UI IR v2 must encode compositing mode explicitly per component.
3. Runtime must provide deterministic integer quantization and clamp guarantees.

## 11) Links to Evidence

1. U-017 board: `ops/planning/agile/m008_execution_board.md`
2. Prerequisites: `ADR-006`, `ADR-007`
3. Continuation chain: `T-813 -> T-825`
