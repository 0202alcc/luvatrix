# Planes v2 Protocol Foundation and File Layout Spec

Status: Frozen for F-027

## Objective

Freeze the Planes v2 split-file contract, canonical basis rules, and deterministic ordering semantics used by follow-on milestones.

## Split-File Layout (Canonical)

The runtime loader resolves a Planes v2 app from this canonical layout:

1. `plane_app/app.json` (app metadata, startup route id, protocol version)
2. `plane_app/planes.json` (plane registry and canonical k-hat ordering fields)
3. `plane_app/components/*.json` (component definitions; one file per component)
4. `plane_app/routes.json` (route graph and active plane sets)
5. `plane_app/scripts.json` (script registry for deterministic handler resolution)

Optional deterministic extensions:

1. `plane_app/theme_tokens.json`
2. `plane_app/data_sources.json`
3. `plane_app/animations.json`

## Canonical Basis Contract

All runtime math is canonicalized to `u_basis`, `v_basis`, and `w_basis`.

```json
{
  "canonical_basis": {
    "u_basis": "canonical_screen_right",
    "v_basis": "canonical_screen_up",
    "w_basis": "canonical_time_forward"
  },
  "aliases": {
    "developer": {
      "x": "u_basis",
      "y": "v_basis",
      "z": "w_basis"
    },
    "native": {
      "i_hat": "u_basis",
      "j_hat": "v_basis",
      "k_hat": "w_basis"
    }
  }
}
```

Alias semantics:

1. `x/y/z` and `i_hat/j_hat/k_hat` are syntax aliases only.
2. Runtime ordering/placement is computed from canonical `u/v/w` fields.
3. Alias and canonical values must normalize to identical ordering results.

## Temporal and Plane Ordering Rules

`k_hat_index` is the canonical plane-depth field in Planes v2.

```json
{
  "camera_k_hat": 0,
  "world_plane_k_hat_rule": "strictly_less_than_zero"
}
```

Schema invariants:

1. `kind=camera` planes require `k_hat_index == 0`.
2. `kind=world` planes require `k_hat_index < 0`.
3. World planes require attachment metadata when not root-mounted.
4. Ties are illegal for canonical ordering fields.

## Coordinate Frames

Predefined frames are required:

1. `screen_tl`
2. `cartesian_bl`
3. `cartesian_center`

Frame policy:

1. Runtime supports all predefined frames for placement and hit-test transforms.
2. `cartesian_center` remains part of default native frame support.
3. `i_hat/j_hat` directional semantics remain stable across frame transforms.

## Deterministic Resolution Rules

Deterministic sort key for render and hit-test eligibility:

1. `k_hat_index` ascending for world planes, camera plane fixed at `0`.
2. `z_local` ascending within plane.
3. `mount_order` ascending.
4. lexical `component_id` tie-break.

Script handler target resolution is strict:

1. Canonical token: `<script_id>::<function_name>`.
2. Missing script id or function name is a strict-mode failure.
3. No runtime fallback to dynamic name guessing.

## Compatibility Boundary

1. Legacy `z_index_alias` remains accepted as input alias only.
2. Canonical runtime fields are `k_hat_index`, `z_local`, and basis `u/v/w`.
3. Existing app behavior is preserved by normalization before runtime evaluation.

## Go/No-Go Blockers for Training

Training demonstration project IDs:

1. `hello_plane`
2. `coordinate_playground`

Hard blockers:

1. Coordinate ambiguity between alias/canonical fields.
2. Non-deterministic coordinate placement across runs.

The closeout packet must include per-project evidence for these blockers.
