# Planes Protocol vNext (Schema Extension Draft)

Status: Draft v0.2.0-dev

This document extends `docs/planes_protocol_v0.md` for the M-008 architecture chain (`T-816`).

It formalizes:
1. multi-plane composition,
2. `camera_overlay` attachment semantics,
3. section-cut metadata,
4. compositing mode declarations,
5. deterministic schema-level compatibility behavior.

## 1) Scope and Goals

1. Keep deterministic render/hit behavior from v0.
2. Introduce multi-plane schema with global plane ordering.
3. Represent component attachment explicitly (`plane` vs `camera_overlay`).
4. Encode compositing intent (`absolute_rgba` vs `delta_rgba`) at schema level.
5. Preserve backward compatibility with existing v0 payloads.

## 2) Top-Level Contract (vNext)

A vNext Planes document MUST include:

1. `planes_protocol_version: str`
2. `app: object`
3. `planes: list[object]`
4. `components: list[object]`

Optional top-level sections:

1. `routes: list[object]`
2. `section_cuts: list[object]`
3. `scripts: list[object]`
4. `theme_tokens: object`
5. `animations: list[object]`
6. `data_sources: list[object]`

## 3) Plane Contract (vNext)

Each `planes[]` entry MUST include:

1. `id: str`
2. `default_frame: str`
3. `background: object`
4. `plane_global_z: int`

Recommended fields:

1. `position: {x, y, frame?}`
2. `size: {width, height}`
3. `relative_to: {plane_id, anchor, offset}`
4. `scrollable: bool`
5. `scroll_limits: {x_min, x_max, y_min, y_max}`
6. `active: bool`

Validation invariants:

1. `id` must be unique.
2. `plane_global_z` ties are allowed but deterministic tie-break uses lexical `plane.id`.
3. `relative_to.plane_id` must resolve and must not form cycles.

## 4) Component Contract Extensions

v0 component fields remain valid. vNext adds:

1. `attachment_kind: "plane" | "camera_overlay"`
2. `attach_to: str | null`
- Required when `attachment_kind == "plane"` (`attach_to` is plane id).
- Must be `null` or omitted when `attachment_kind == "camera_overlay"`.
3. `component_local_z: int`
4. `blend_mode: "absolute_rgba" | "delta_rgba"` (default `absolute_rgba`)
5. `world_bounds_hint` (optional optimization hint)

Validation invariants:

1. `attachment_kind` must be explicit in strict vNext mode.
2. `attach_to` must reference an existing plane when attachment is `plane`.
3. `component_local_z` participates in deterministic ordering only within target plane.

## 5) Section-Cut Schema

`section_cuts[]` entries define transparent interaction/render portals:

1. `id: str`
2. `owner_plane_id: str`
3. `target_plane_ids: list[str]`
4. `region: {x, y, width, height, frame?}`
5. `enabled: bool` (default `true`)

Rules:

1. Cut region removes owner-plane occupancy in that region.
2. Underlying planes in `target_plane_ids` are eligible for draw/hit through the cut.
3. Invalid plane references fail strict validation.

## 6) Routing Schema (Optional)

`routes[]` may define plane activation sets:

1. `id: str`
2. `active_planes: list[str]`
3. `default: bool`
4. `params_schema` (optional)

Rules:

1. At least one route SHOULD be marked default if routes are present.
2. Active plane ids must resolve.

## 7) Deterministic Ordering Contract

Draw order key:

1. `attachment_kind` (`plane` before `camera_overlay`)
2. `plane_global_z` ascending (for plane-attached components)
3. `component_local_z` ascending
4. stable lexical `component.id` tie-break

Hit-test order is the reverse of draw order, modified only by section-cut pass-through semantics.

## 8) Compositing Declarations

1. `blend_mode = "absolute_rgba"`
- source channels expected in `[0,255]`.

2. `blend_mode = "delta_rgba"`
- source channels expected in `[-255,255]` before runtime clamp.

Final MatrixBuffer channel values MUST clamp to `[0,255]`.

## 9) Backward Compatibility Mapping (v0 -> vNext)

For legacy payloads with `plane` (single object) and without `attachment_kind`:

1. Promote `plane` to `planes=[plane]`.
2. Assign `plane_global_z=0` when missing.
3. Map each component to:
- `attachment_kind="plane"`
- `attach_to=<promoted_plane_id>`
- `component_local_z = z_index` (legacy field)
- `blend_mode="absolute_rgba"`
4. If `z_index` missing, default to `0`.

Strict vNext mode MAY require explicit vNext fields after migration window.

## 10) Validation Modes

Strict mode:

1. Unknown vNext fields fail.
2. Missing required references fail.
3. Invalid blend/attachment/cut values fail.

Permissive mode:

1. Unknown fields warn.
2. Invalid optional references may be ignored with warning.
3. Missing vNext fields on v0 payloads are auto-mapped by compatibility rules.

## 11) Minimal vNext Example

```json
{
  "planes_protocol_version": "0.2.0-dev",
  "app": {"id": "demo.multi", "title": "Demo", "icon": "assets/logo.svg"},
  "planes": [
    {"id": "index", "default_frame": "screen_tl", "background": {"color": "#0d1720"}, "plane_global_z": 10},
    {"id": "plot", "default_frame": "screen_tl", "background": {"color": "#111827"}, "plane_global_z": 5}
  ],
  "section_cuts": [
    {
      "id": "plot_window",
      "owner_plane_id": "index",
      "target_plane_ids": ["plot"],
      "region": {"x": 200, "y": 220, "width": 900, "height": 460}
    }
  ],
  "components": [
    {
      "id": "index_title",
      "type": "text",
      "attachment_kind": "camera_overlay",
      "component_local_z": 0,
      "position": {"x": 20, "y": 20},
      "size": {"width": {"unit": "px", "value": 260}, "height": {"unit": "px", "value": 28}},
      "props": {"text": "Overlay title"}
    },
    {
      "id": "plot_line",
      "type": "svg",
      "attachment_kind": "plane",
      "attach_to": "plot",
      "component_local_z": 30,
      "blend_mode": "absolute_rgba",
      "position": {"x": 40, "y": 40},
      "size": {"width": {"unit": "px", "value": 1400}, "height": {"unit": "px", "value": 800}},
      "props": {"svg": "assets/plot.svg"}
    }
  ]
}
```

## 12) Relationship to Chain Tasks

1. This schema update is the T-816 deliverable.
2. T-817 will align App Protocol capability/version signaling with this schema.
3. T-819 will map these fields into UI IR v2 contract form.
