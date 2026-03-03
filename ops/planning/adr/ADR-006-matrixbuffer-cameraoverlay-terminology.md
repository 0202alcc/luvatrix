# ADR-006: MatrixBuffer and Camera Overlay Terminology

- Status: Accepted
- Date: 2026-03-01
- Milestone: U-017
- Task: T-811
- Owner: Runtime/Protocol

## 1) Context

The current Planes and runtime conversations use the term "camera" in two different ways:
1. As the visible output window that users actually see each frame.
2. As a conceptual top-most layer for pinned UI controls (title bars, HUD, persistent controls).

Using one word for both concepts causes implementation ambiguity in schema fields, UI IR contracts, runtime code, and documentation.

U-017 expansion work (`T-811 -> T-825`) requires strict naming stability before schema and IR evolution.

## 2) Decision

Adopt the following canonical terminology:

1. `MatrixBuffer`
- Definition: Final visible RGBA output surface for each frame.
- Meaning: The concrete app window pixel buffer users see.
- Constraint: Any statement about "what is on screen" references MatrixBuffer.

2. `CameraOverlayLayer`
- Definition: Logical top-most attachment layer for components pinned to MatrixBuffer coordinates.
- Meaning: Overlay components are not part of world-plane scrolling.
- Constraint: Overlay components always render above all Plane-attached components.

3. `Plane`
- Definition: A 2D component space (potentially larger than MatrixBuffer) that can scroll relative to MatrixBuffer.
- Meaning: Plane components are world-attached and can move through camera/scroll transforms.

4. `Component`
- Definition: Renderable/interactable UI element attached either to a Plane or CameraOverlayLayer.

## 3) Naming Rules (Normative)

1. Do not use ambiguous `camera` as a standalone schema field for output semantics.
2. Runtime state representing user-visible output position must use `plane_scroll` / plane-space naming.
3. Fields for pinned top-level UI must use `camera_overlay` / `overlay` naming.
4. Documentation must use `MatrixBuffer` when describing visible output.
5. In code comments and specs, "camera" may be used informally only when paired with the formal term (for example: "plane camera over MatrixBuffer").

## 4) Rendering and Ordering Implications

1. MatrixBuffer is the final composition target.
2. Plane-attached components render into MatrixBuffer according to global plane ordering + local component ordering.
3. CameraOverlayLayer components render after all planes.
4. Any future blend/compositing mode must preserve final MatrixBuffer channel clamp boundaries.

## 5) Alternatives Considered

1. Keep "camera" for both concepts.
- Rejected: too ambiguous for schema, UI IR, and runtime implementation.

2. Rename output to "ViewportOutput" while keeping a camera layer.
- Rejected: introduces another term for the same concrete target already understood as MatrixBuffer.

3. Use "HUD" instead of CameraOverlayLayer.
- Rejected: "HUD" is too game-centric and less explicit for protocol contracts.

## 6) Consequences

Positive:
1. Clear separation between visible output target and overlay attachment semantics.
2. Reduced ambiguity in schema vNext and UI IR v2 field design.
3. Better compatibility with deterministic testing and documentation.

Trade-offs:
1. Existing informal "camera" language in docs may need cleanup over time.
2. Some legacy fields/comments may require migration notes.

## 7) Follow-on Work

1. T-812 must use this terminology in the composition model ADR.
2. T-816 and T-819 must reflect `MatrixBuffer` and `CameraOverlayLayer` naming in schema/IR contracts.
3. Any compatibility aliases must be explicitly marked deprecated in spec text.

## 8) Links to Evidence

1. U-017 board: `ops/planning/agile/m008_execution_board.md`
2. Working scrolling baseline commit: `83d1a2f`
3. Approved strict chain: `T-811 -> T-825`
