# Planes Canonical IR Contract (UF-029)

## Canonical Target
Compiler outputs a single canonical IR contract represented by `UIIRPage` with these invariants:
- `ir_version = "planes-v2"`
- `ordering_contract_version = "plane-z-local-z-overlay-v1"`
- Runtime basis is canonical `u/v/w` semantics only.

## Input Mapping
### Split-file input (`planes[]`)
- Preserve `plane_global_z` ordering.
- Normalize component ordering into `stable_order_key = (attachment_rank, plane_global_z, component_local_z, mount_order)`.
- Preserve `camera_overlay` vs `plane` attachment semantics.

### Monolith input (`plane`)
- Adapt monolith `plane` into canonical `planes[]` manifest with one default plane.
- Preserve component geometry and interaction bindings.
- Emit canonical ordering contract and stable ordering keys.

## Alias Normalization Contract
When basis aliases are present, normalize before runtime:
- `x/y/z -> u/v/w`
- `i_hat/j_hat/k_hat -> u_hat/v_hat/w_hat`

## Parity Contract (Go Blockers)
The following are hard NO-GO mismatches:
- ordering mismatch
- transform mismatch
- hit-test mismatch

## Demonstration Mapping
- `closeout_training_project_ids = ["camera_overlay_basics"]`
- Required demonstration scope:
  1. split vs monolith compile parity to canonical IR
  2. overlay parity semantics
