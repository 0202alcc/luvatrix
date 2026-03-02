# UI IR v2 Gap Assessment (T-818)

Status: Draft assessment (2026-03-01)
Milestone: M-008
Task: T-818

## 1) Objective

Assess whether the current UI IR + Planes compiler/runtime contracts are sufficient for the M-008 vNext model and identify exact gaps before IR v2 field-contract work (`T-819`).

Scope anchors:
1. `docs/planes_protocol_vnext.md`
2. `docs/app_protocol_v2_superset_spec.md`
3. `luvatrix_ui/planes_protocol.py`
4. `docs/json_ui_compiler.md`

## 2) Current IR Baseline (Observed)

Current Planes compile path emits `UIIRPage` + `UIIRComponent` with v0 assumptions:

1. Single `plane` object (not `planes[]`).
2. `z_index` only (no split between global-plane and local-component ordering).
3. No explicit attachment kind (`plane` vs `camera_overlay`).
4. No section-cut metadata.
5. No route/active-plane metadata.
6. No compositing mode field (`absolute_rgba` vs `delta_rgba`).
7. No culling hint or world-bounds hint channels.

## 3) Capability Matrix

Legend: `Ready`, `Partial`, `Missing`

| Requirement | Status | Notes |
| --- | --- | --- |
| Multi-plane schema ingestion (`planes[]`) | Missing | Validator/compiler currently require single `plane`. |
| Global plane ordering (`plane_global_z`) | Missing | Ordering model is component-only `z_index`. |
| Local component ordering (`component_local_z`) | Partial | `z_index` exists but not explicitly scoped per-plane. |
| Explicit attachment kind (`plane` / `camera_overlay`) | Missing | No IR field currently distinguishes overlay attachment. |
| `attach_to` plane reference resolution | Missing | No plane-ref structure in IR pipeline. |
| Section-cut metadata passthrough | Missing | No schema/IR structure for cut ownership/region/targets. |
| Route/active-plane activation metadata | Missing | No route selection encoded in current IR page. |
| Blend mode declaration (`absolute_rgba`, `delta_rgba`) | Missing | Current IR does not carry compositing mode. |
| World bounds and culling hints | Missing | No fields for culling contracts/prefetch hints. |
| Deterministic tie-break key exposure | Partial | Determinism is implicit (source order) but not explicit key contract. |
| Backward compatibility mapping support | Partial | v0 behavior exists; explicit vNext compatibility map not compiled into IR metadata. |
| Strict/permissive validation for vNext fields | Missing | Validation rules are v0-focused. |

## 4) Gap Severity

1. High severity (blocks vNext implementation):
- Multi-plane ingestion
- Attachment semantics
- Section cuts
- Blend mode
- Route activation

2. Medium severity (risk of ambiguity/perf regressions):
- Explicit deterministic key contract
- World-bounds/culling hints
- Formal compatibility metadata in IR output

3. Low severity:
- Documentation synchronization once v2 fields are implemented

## 5) Recommended IR v2 Field Set (Minimum)

Per page/runtime payload:
1. `ir_version = "planes-v2"`
2. `active_route_id`
3. `active_plane_ids`
4. `ordering_contract_version`

Per component:
1. `attachment_kind` (`plane` | `camera_overlay`)
2. `plane_id` (nullable for overlay)
3. `plane_global_z`
4. `component_local_z`
5. `blend_mode`
6. `world_bounds`
7. `world_bounds_hint` (optional)
8. `culling_hint` (optional)
9. `section_cut_refs` (optional)
10. `stable_order_key`

Per section cut (IR object):
1. `cut_id`
2. `owner_plane_id`
3. `target_plane_ids`
4. `region_bounds`
5. `enabled`

## 6) Go/No-Go for Runtime Rewrite

Decision: **NO-GO** for full runtime vNext rewrite until `T-819` lands.

Rationale:
1. Runtime can emulate parts of behavior ad-hoc, but core semantics (multi-plane ordering, cuts, blend mode, overlay attachment) are not yet representable in IR.
2. Implementing runtime first would create unstable duplicate contracts and migration debt.

Required gate to proceed:
1. IR v2 contract defined and accepted (`T-819`).
2. Validation/snapshot strategy agreed (`T-820`).

## 7) Transition Strategy

1. Keep current `planes-v0` compile path untouched.
2. Introduce parallel `planes-v2` compile mode behind feature flag.
3. Provide deterministic compatibility mapper `v0 -> v2` for mixed-app migration.
4. Run dual-path snapshot checks during rollout (`T-825`).

## 8) Evidence and References

1. `docs/planes_protocol_vnext.md`
2. `docs/app_protocol_v2_superset_spec.md`
3. `luvatrix_ui/planes_protocol.py`
4. `docs/json_ui_compiler.md`
5. `ops/planning/agile/m008_execution_board.md`
