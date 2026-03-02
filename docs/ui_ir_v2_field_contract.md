# UI IR v2 Field Contract (T-819)

Status: Draft contract (2026-03-01)
Milestone: M-008
Task: T-819

## 1) Purpose

Define the normative UI IR v2 field set needed to represent Planes vNext semantics deterministically while preserving a migration path from current `planes-v0` IR payloads.

## 2) Versioning

1. `UIIRPage.ir_version` MUST be:
- `"planes-v0"` for legacy payloads
- `"planes-v2"` for new multi-plane payloads

2. v2 payloads MUST include `ordering_contract_version`.

## 3) Page-Level v2 Fields

`UIIRPage` additions for `planes-v2`:

1. `active_route_id: str | None`
2. `active_plane_ids: tuple[str, ...]`
3. `ordering_contract_version: str` (example: `"plane-z-local-z-overlay-v1"`)
4. `section_cuts: tuple[UIIRSectionCut, ...]`
5. `plane_manifest: tuple[UIIRPlaneRef, ...]`

### Validation

1. `active_plane_ids` must all resolve in `plane_manifest`.
2. `active_route_id` must resolve if routes are present.
3. `ordering_contract_version` must be non-empty for `planes-v2`.

## 4) Plane-Level IR Objects

`UIIRPlaneRef` fields:

1. `plane_id: str`
2. `plane_global_z: int`
3. `active: bool`
4. `resolved_position: CoordinateRef`
5. `resolved_bounds: BoundingBoxSpec`
6. `default_frame: str`

### Validation

1. `plane_id` unique.
2. Deterministic tie-break for equal `plane_global_z` is lexical `plane_id`.

## 5) Section-Cut IR Objects

`UIIRSectionCut` fields:

1. `cut_id: str`
2. `owner_plane_id: str`
3. `target_plane_ids: tuple[str, ...]`
4. `region_bounds: BoundingBoxSpec`
5. `enabled: bool`

### Validation

1. `owner_plane_id` and all `target_plane_ids` must resolve.
2. Empty `target_plane_ids` is invalid in strict mode.

## 6) Component-Level v2 Fields

`UIIRComponent` additions for `planes-v2`:

1. `attachment_kind: "plane" | "camera_overlay"`
2. `plane_id: str | None`
3. `plane_global_z: int | None`
4. `component_local_z: int`
5. `blend_mode: "absolute_rgba" | "delta_rgba"`
6. `world_bounds: BoundingBoxSpec`
7. `world_bounds_hint: BoundingBoxSpec | None`
8. `culling_hint: dict[str, object]`
9. `section_cut_refs: tuple[str, ...]`
10. `stable_order_key: tuple[int, int, int, str]`

### Validation

1. If `attachment_kind == "plane"`:
- `plane_id` required
- `plane_global_z` required

2. If `attachment_kind == "camera_overlay"`:
- `plane_id` MUST be `None`
- `plane_global_z` ignored and SHOULD be `None`

3. `blend_mode` defaults to `absolute_rgba` if omitted in permissive mode.

4. `stable_order_key` MUST be derivable and deterministic from canonical ordering fields.

## 7) Deterministic Ordering Contract

Draw order key in v2:

1. `attachment_rank` (`plane=0`, `camera_overlay=1`)
2. `plane_global_z` (ascending; overlay uses sentinel)
3. `component_local_z` (ascending)
4. `mount_order` (ascending)
5. `component_id` lexical

Hit-test order is exact reverse of draw order before section-cut pass-through adjustments.

## 8) Compositing Contract in IR

1. `blend_mode = absolute_rgba`
- renderer expects source channels in `[0,255]`

2. `blend_mode = delta_rgba`
- renderer expects source channels in `[-255,255]`
- final destination channels clamped to `[0,255]`

3. `blend_mode` MUST be explicit in strict v2 mode.

## 9) Compatibility Mapping (v0 -> v2)

For migration shims:

1. `z_index -> component_local_z`
2. `attachment_kind = plane`
3. `plane_id = <legacy_page_id>`
4. `plane_global_z = 0`
5. `blend_mode = absolute_rgba`
6. `stable_order_key` computed using v2 ordering contract

`camera_overlay` inference is optional and MUST be deterministic if enabled.

## 10) Strict vs Permissive

Strict `planes-v2`:
1. Missing required v2 fields fail validation.
2. Unknown enum values fail.
3. Unresolved references fail.

Permissive `planes-v2`:
1. Missing optional fields default deterministically.
2. Unknown extra fields warn.
3. Invalid optional hints may be dropped with warning.

## 11) Serialization Guidance

`UIIRPage.to_dict()` for v2 SHOULD emit:

1. all v2 page fields,
2. plane and cut object lists,
3. per-component v2 fields,
4. explicit `ordering_contract_version`.

Deserialization MUST reject ambiguous mixed-mode payloads (for example `ir_version=planes-v2` with missing attachment fields) in strict mode.

## 12) Implementation Boundary

This document is the contract only.

Actual implementation will land in:
1. `T-820` (validation/snapshot plan)
2. `T-821` (compiler design)
3. `T-822` (runtime pipeline design)

## 13) Evidence

1. `docs/ui_ir_v2_gap_assessment.md`
2. `docs/planes_protocol_vnext.md`
3. `docs/app_protocol_v2_superset_spec.md`
4. `ops/planning/agile/m008_execution_board.md`
