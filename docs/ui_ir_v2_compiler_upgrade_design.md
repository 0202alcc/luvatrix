# UI IR v2 Compiler Upgrade Design (T-821)

Status: Draft design (2026-03-01)
Milestone: M-008
Task: T-821

## 1) Purpose

Define the compiler upgrade path from Planes schema vNext inputs to `planes-v2` UI IR output, with deterministic ordering, strict/permissive validation behavior, and backward compatibility with `planes-v0`.

## 2) Inputs and Outputs

Inputs:
1. Planes v0 payload (`plane` + legacy component fields).
2. Planes vNext payload (`planes[]`, optional `routes[]`, `section_cuts[]`, `attachment_kind`, `blend_mode`).
3. Compile mode (`strict` or `permissive`).

Output:
1. `UIIRPage` with `ir_version`:
- `planes-v0` for legacy unchanged path.
- `planes-v2` for vNext path (or compatibility-lifted v0 path when explicitly requested).

## 3) Compiler Pipeline

Stage 1. Parse + schema detect
1. Detect source schema by required top-level shape:
- `plane` only -> v0.
- `planes[]` present -> vNext.
2. Reject mixed ambiguous shapes in strict mode.

Stage 2. Structural normalization
1. Convert coordinate/bounds forms into canonical normalized bounds objects.
2. Normalize component mount ordering with a deterministic `mount_order` sequence.
3. Normalize optional route and section-cut definitions.

Stage 3. Semantic validation
1. Validate attachment references:
- `attachment_kind=plane` requires valid `plane_id`.
- `attachment_kind=camera_overlay` forbids `plane_id`.
2. Validate section-cut references:
- `owner_plane_id` and each target must resolve.
3. Validate `blend_mode` enum and default policy by mode.

Stage 4. IR object emission
1. Emit page-level `plane_manifest` and `section_cuts`.
2. Emit components with v2 fields (`plane_global_z`, `component_local_z`, `blend_mode`, `stable_order_key`, culling hints).
3. Emit `ordering_contract_version`.

Stage 5. Post-emit determinism pass
1. Re-sort emitted component list by canonical key.
2. Assert stable order key uniqueness.
3. Emit deterministic diagnostics list ordering.

## 4) Strict vs Permissive Behavior

Strict mode:
1. Unknown enum values fail.
2. Unresolved references fail.
3. Ambiguous payload shape fails.
4. Required v2 fields missing fail.

Permissive mode:
1. Missing `blend_mode` defaults to `absolute_rgba`.
2. Missing `attachment_kind` defaults to `plane` only when mapping is unambiguous.
3. Invalid optional hints may be dropped with warning.
4. Unknown extra fields preserved in metadata passthrough bucket.

## 5) Compatibility Mapping Path (v0 -> v2)

Optional compatibility-lift compiler mode:
1. Create synthetic plane manifest with one plane (`plane_global_z=0`).
2. Map `z_index -> component_local_z`.
3. Set `attachment_kind=plane`, `blend_mode=absolute_rgba`.
4. Compute v2 `stable_order_key` using canonical order contract.
5. Preserve original v0 payload snapshot in compiler metadata for traceability.

## 6) Diagnostics Contract

Compiler diagnostics fields:
1. `code` (stable identifier)
2. `severity` (`error`, `warning`, `info`)
3. `path` (JSON pointer-like location)
4. `message`
5. `suggested_fix` (optional)

Determinism rules:
1. Diagnostics sorted by `(severity_rank, path, code, message)`.
2. Warning text templates are static (no nondeterministic fragments).

## 7) Ordering Key Construction

`stable_order_key = (attachment_rank, plane_global_z, component_local_z, mount_order, component_id_lexical)`

1. `attachment_rank`: `plane=0`, `camera_overlay=1`.
2. `plane_global_z`: real plane value; overlay sentinel at compare time.
3. `mount_order`: deterministic index assigned during normalization.
4. `component_id_lexical`: final tie-break for identical structural fields.

## 8) Failure Policy

1. Strict compile errors stop emission.
2. Permissive compile emits output only when deterministic defaults resolve ambiguity.
3. Non-recoverable ambiguity must fail in both modes.

## 9) Test Plan Mapping (T-820 Integration)

Minimum mapping:
1. `S03/S04`: vNext minimal valid -> emits `planes-v2`.
2. `S05/S06`: missing `attachment_kind` strict fail / permissive default.
3. `S07/S08`: invalid blend strict fail / permissive fallback + warning.
4. `S09/S10`: unresolved attach references strict fail / permissive deterministic policy.
5. `S13/S14`: equal-z deterministic order-key stability.
6. `S17`: v0->v2 compatibility-lift deterministic mapping.

## 10) Implementation Boundaries

Design scope only. No runtime behavior changes in this task.

Execution tasks:
1. T-822: runtime pipeline design aligned to emitted v2 fields.
2. T-823: performance plan integration for culling hints and invalidation metadata.
3. T-824: demo/verification coverage for compile + runtime interaction.

## 11) Evidence

1. `docs/ui_ir_v2_field_contract.md`
2. `docs/ui_ir_v2_validation_plan.md`
3. `docs/planes_protocol_vnext.md`
4. `ops/planning/agile/m008_execution_board.md`
