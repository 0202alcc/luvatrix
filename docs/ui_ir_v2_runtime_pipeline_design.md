# UI IR v2 Runtime Pipeline Design (T-822)

Status: Draft design (2026-03-01)
Milestone: M-008
Task: T-822

## 1) Purpose

Define the deterministic runtime pipeline for consuming `planes-v2` IR and producing the final `MatrixBuffer` frame, including plane composition order, camera overlay precedence, and `absolute_rgba` / `delta_rgba` clamping rules.

## 2) Runtime Inputs

1. `UIIRPage` (`ir_version=planes-v2`)
2. Active route and active plane set
3. Camera state:
- page camera offset
- viewport camera offsets
4. Frame timing + input events

## 3) Frame Pipeline

Stage 1. Resolve active scene graph
1. Resolve active planes from route/page state.
2. Resolve section-cut pass-through map for hit-test/render masking.
3. Build deterministic render list from component `stable_order_key`.

Stage 2. Compute camera-visible regions
1. Build visible region for each plane from:
- page camera viewport
- nested viewport surfaces
2. Expand by prefetch margin policy (from ADR-010).

Stage 3. Cull and gather draw commands
1. Skip components with no intersection against visible region.
2. Keep deterministic gather order even when culled.
3. Emit plane-local draw command buffers plus overlay command buffer.

Stage 4. Compose plane-attached content into `MatrixBuffer`
1. Start from cleared frame background.
2. Apply plane command buffers in ascending `(plane_global_z, component_local_z, mount_order, component_id)`.
3. For each command:
- `absolute_rgba`: overwrite destination pixels directly.
- `delta_rgba`: add channel deltas then clamp each channel to `[0,255]`.

Stage 5. Apply `CameraOverlayLayer`
1. Draw overlay commands after all plane content.
2. Overlay always wins visually regardless of local z values on planes.
3. Overlay uses same blend/clamp contract per component `blend_mode`.

Stage 6. Attach runtime affordances
1. Add viewport or page scrollbars based on active overflow surfaces.
2. Keep affordances deterministic and camera-relative.
3. Preserve `camera_fixed` semantics for controls pinned to screen space.

Stage 7. Emit final `MatrixBuffer`
1. Return final RGBA255 tensor.
2. Record deterministic diagnostics/perf counters for telemetry.

## 4) Section-Cut Render and Input Rules

Render:
1. Owner plane does not draw pixels inside cut regions.
2. Target plane content fills exposed region based on global z order.

Input:
1. Hit-test overlay first.
2. For plane content, deepest visible candidate by reverse draw order wins.
3. Section cuts transfer interaction ownership to visible target plane.

## 5) Determinism Contract

1. Every frame uses canonical sort key ordering.
2. Cull decisions are pure function of:
- camera state,
- component bounds,
- fixed prefetch margin parameters.
3. Clamp behavior is channel-local and deterministic with no float rounding drift (`int` arithmetic for blend accumulation where possible).
4. Scrollbar geometry derives from exact content/viewport extents.

## 6) Error Handling

1. Invalid component payload in strict runtime mode:
- hard fail render for frame, emit structured error event.
2. Invalid optional hint in permissive mode:
- skip hint, continue with deterministic fallback.
3. Unknown blend mode:
- strict fail, permissive fallback to `absolute_rgba` + warning.

## 7) Telemetry Hooks

Per-frame metrics:
1. total components
2. culled components
3. draw commands emitted
4. overlay commands emitted
5. clamp operations count
6. frame compose time (ms)

These metrics are required inputs for T-823 performance gates.

## 8) Integration with T-820 Matrix

Runtime design must satisfy:
1. `S11/S12` section-cut routing behavior.
2. `S13/S14` deterministic order key behavior.
3. `S15/S16` delta blend clamp behavior.
4. `S18` active route and plane filtering behavior.

## 9) Implementation Boundary

Design-only task; no runtime code changes in this step.

Implementation sequencing:
1. T-823 defines optimization/invalidation execution strategy.
2. T-824 defines end-to-end verification demos for this pipeline.
3. T-825 gates rollout policy based on matrix pass/fail.

## 10) Evidence

1. `docs/ui_ir_v2_field_contract.md`
2. `docs/ui_ir_v2_validation_plan.md`
3. `ops/planning/adr/ADR-008-absolute-delta-rgba-compositing.md`
4. `ops/planning/adr/ADR-010-camera-relative-culling-and-prefetch.md`
5. `ops/planning/agile/m008_execution_board.md`
