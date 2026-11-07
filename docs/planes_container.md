# Luvatrix App Container Schema (Draft v0)

Status: Draft v0.1.0

The app container is the first-class bundle format that promotes per-plane
Planes JSON into a complete app document: app metadata, planes and
components, routes, route transitions, component animations, and script
references. UI is data; logic stays behind named function bindings, so the
same container runs against any backend (Python, JavaScript, WASM) that
implements the handler contract.

Implementation: `luvatrix_ui/planes_container.py`.
Reference importer: `luvatrix_ui/figma_import.py`.

## 1. Container Document Contract

A container document is a JSON object with:

1. `container_protocol_version: str` (currently `0.1.0`)
2. `app: object` (same contract as Planes `app`)
3. `routes: list[object]` (non-empty)
4. One of:
   - `planes: list[object]` (Planes v2 split-style planes), or
   - `plane: object` (monolith Planes plane)

Optional sections:

1. `components: list[object]` (same contract as Planes components)
2. `scripts: list[object]` (same contract as Planes scripts)
3. `animations: list[object]` (container-only)
4. `planes_protocol_version: str` (defaults to the current Planes version)

## 2. Route Contract

Each `routes[]` entry:

1. `id: str` (unique across the container)
2. `active_planes: list[str]` (each must reference a declared plane)
3. `default: bool` (exactly one route must be the default; it is the entry
   route)
4. `transitions: list[object]` (optional, container-only)

Transitions:

1. `trigger: str` (unique per source route)
2. `to_route: str` (must reference a declared route)
3. `kind: str` — one of `none`, `fade`, `slide_left`, `slide_right`,
   `slide_up`, `slide_down` (default `fade`)
4. `duration_ms: int` (positive; default `200`)
5. `easing: str` — one of `linear`, `ease_in`, `ease_out`, `ease_in_out`
   (default `ease_in_out`)

## 3. Animation Contract

Each `animations[]` entry:

1. `target: str` (must reference a declared component id)
2. `trigger: str` — one of `route_enter`, `route_exit`, `on_mount`,
   `on_state`
3. `kind: str` — one of `fade`, `slide`, `scale`, `rotate`
4. `duration_ms: int` (positive)
5. `delay_ms: int` (non-negative; default `0`)
6. `easing: str` (same enum as transitions; default `ease_in_out`)
7. `loop: str` — one of `none`, `repeat`, `ping_pong` (default `none`)
8. `keyframes: list[object]` (optional) — each entry has `at: number` in
   `[0, 1]` and `props: object` of numeric style values. Keyframes must be
   ordered by ascending `at`.

## 4. Compile Contract

`compile_container(payload)` returns a `CompiledAppContainer` with:

1. `app_id`, `entry_route`
2. `routes`: normalized `ContainerRoute` entries (transitions resolved and
   validated)
3. `animations`: normalized `ComponentAnimation` entries
4. `planes_payload`: the payload with container-only keys stripped, ready
   for `luvatrix_ui.planes_protocol.compile_planes_to_ui_ir`

Stripping rules:

1. `container_protocol_version` and `animations` are removed.
2. Per-route `transitions` are removed.
3. `planes_protocol_version` is defaulted when absent.

Validation is fail-fast: container schema errors raise
`PlanesValidationError` regardless of `strict`. The `strict` flag is passed
through to the underlying Planes validation (unknown hooks, blend modes,
and so on).

## 5. Minimal Example

```json
{
  "container_protocol_version": "0.1.0",
  "app": {
    "id": "com.example.bundle",
    "title": "Bundle",
    "icon": "assets/icon.svg",
    "web": {"tab_title": null, "tab_icon": null}
  },
  "planes": [
    {
      "id": "home_plane",
      "default_frame": "screen_tl",
      "background": {"color": "#000000"},
      "plane_global_z": 0,
      "position": {"x": 0, "y": 0, "frame": "screen_tl"},
      "size": {"width": {"unit": "px", "value": 800}, "height": {"unit": "px", "value": 600}}
    },
    {
      "id": "settings_plane",
      "default_frame": "screen_tl",
      "background": {"color": "#000000"},
      "plane_global_z": 1,
      "position": {"x": 0, "y": 0, "frame": "screen_tl"},
      "size": {"width": {"unit": "px", "value": 800}, "height": {"unit": "px", "value": 600}}
    }
  ],
  "routes": [
    {
      "id": "home",
      "default": true,
      "active_planes": ["home_plane"],
      "transitions": [
        {"trigger": "navigate_settings", "to_route": "settings", "kind": "slide_left", "duration_ms": 240, "easing": "ease_out"}
      ]
    },
    {"id": "settings", "active_planes": ["settings_plane"]}
  ],
  "scripts": [
    {"id": "handlers", "lang": "python", "src": "scripts/handlers.py"}
  ],
  "components": [
    {
      "id": "home_title",
      "type": "text",
      "attach_to": "home_plane",
      "component_local_z": 1,
      "blend_mode": "absolute_rgba",
      "position": {"x": 20, "y": 16, "frame": "screen_tl"},
      "size": {"width": {"unit": "px", "value": 240}, "height": {"unit": "px", "value": 24}},
      "z_index": 1,
      "props": {"text": "Home"}
    }
  ],
  "animations": [
    {
      "target": "home_title",
      "trigger": "route_enter",
      "kind": "fade",
      "duration_ms": 180,
      "easing": "ease_in_out",
      "loop": "none",
      "keyframes": [
        {"at": 0.0, "props": {"opacity": 0.0}},
        {"at": 1.0, "props": {"opacity": 1.0}}
      ]
    }
  ]
}
```

## 6. Figma Reference Importer

`import_figma_document(document)` compiles a Figma REST-style document JSON
into a container payload plus generated assets. The reference subset:

1. Top-level `FRAME` nodes on each `CANVAS` page become one plane and one
   route each; route ids are slugs of frame names, plane ids are
   `plane_<slug>`.
2. The page-level `prototypeStartNodeID` (when it matches a top-level
   frame) selects the entry route; otherwise the first frame is the entry.
3. Frame `fills` map to the plane background color.
4. `TEXT` nodes become `text` components: `characters` as text, `style`
   font family/size/weight, first solid fill as `color_hex`. Positions are
   converted from absolute bounding boxes to coordinates relative to the
   parent frame (`screen_tl`).
5. Shape nodes (`RECTANGLE`, `ELLIPSE`, `POLYGON`, `STAR`, `LINE`,
   `VECTOR`) and nested `FRAME` leaves become `svg` components. The
   importer generates the SVG markup into `FigmaImportResult.assets` keyed
   by `assets/svg_<node_id>.svg`; callers materialize those files next to
   the container document.
6. Node `interactions` with `NODE` actions become route transitions on the
   route containing the interacting node, with trigger
   `navigate_<target_route>`. Figma transition types map as:
   `MOVE_IN_LEFT` → `slide_left` (and the right/top/bottom variants),
   `DISSOLVE` and `SMART_ANIMATE` → `fade`, others → `none`. Figma easing
   types map to the container easing enum. Durations convert from seconds
   to milliseconds.

Unmapped Figma node types are skipped and reported in
`FigmaImportResult.warnings`.

## 7. Known Limitations and Follow-ups

1. Transitions and animations are schema/normalization only in this
   revision; the Planes runtime does not yet interpolate them at present
   time. Wiring into the planes runtime present pipeline is the next step.
2. The Figma importer covers the reference subset above; gradients,
   auto-layout, components/instances, and Lottie sources are future work.
3. `on_state` animations have no state-binding wiring yet.
