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

## 6. Runtime Behavior (Implemented)

The planes runtime consumes container documents natively: a payload with
`container_protocol_version` is compiled through `compile_container`, and
the runtime keeps the normalized routes/transitions/animations for motion.

1. `PlaneApp.activate_route(route_id)` swaps the active-plane set
   immediately, then plays the declared transition (looked up on the
   source route by `to_route`; an explicit `transition=` argument
   overrides). Without a matching spec the switch is immediate.
2. `fade` transitions crossfade: entering components take the eased
   progress as an opacity multiplier, exiting components take
   `1 - progress`. `slide_left`/`slide_right`/`slide_up`/`slide_down`
   offset the entering plane in from the named edge and the exiting plane
   out the opposite edge (offsets in pixels over the matrix size). During
   a transition both routes' planes render.
3. Component animations interpolate their keyframes each frame (`opacity`,
   `offset_x`, `offset_y`, `scale`, `rotation_deg` props). Opacity
   composes multiplicatively with transition multipliers; offsets add.
   `scale`/`rotation_deg` interpolate and are exposed in
   overrides/telemetry, but are not yet rasterized by the text/svg mount
   pipeline.
4. Triggers: `route_enter` starts when their route activates; `route_exit`
   when their route deactivates; `on_mount` when the target component
   first becomes active; `on_state` when the referenced `state_key` value
   changes between frames (re-setting the same value does not restart).
5. `delay_ms` holds the first keyframe; `loop: repeat` wraps raw progress;
   `ping_pong` reflects it (triangle wave). When a `none`-loop animation
   completes, its final keyframe props persist as the rest state, and the
   completion frame is presented once.
6. Determinism: all motion is driven by the frame `dt`. Route changes
   force the full-frame invalidation boundary (existing escape hatch,
   reason `route_change:<from>-><to>`); running animations contribute
   their component bounds (plus offsets) as dirty rects so incremental
   present still applies between transition frames.
7. Telemetry: `state["perf"]["active_transition"]` is `null` or
   `{from_route, to_route, kind, progress, duration_ms}`;
   `state["perf"]["animation_progress"]` maps target component id to raw
   progress for running animations. Both sit alongside `compose_mode`.

## 7. Figma Reference Importer

`import_figma_document` covers:

1. Top-level `FRAME` and `INSTANCE` nodes become one plane and one route
   each; `prototypeStartNodeID` selects the entry route.
2. Solid fills map to hex colors; `GRADIENT_LINEAR`/`GRADIENT_RADIAL`
   fills compile to SVG gradient defs using Figma handle order (start,
   end, width direction).
3. Auto-layout frames (`layoutMode`) stack bounds-less children along the
   primary axis from padding with `itemSpacing` (REST JSON normally
   carries resolved bounds; this covers plugin/file exports that omit
   them).
4. `TEXT` nodes become text components; shapes and nested
   frames/instances become svg components with generated markup returned
   in `FigmaImportResult.assets`.
5. `NODE` prototype interactions become route transitions with mapped
   kinds and easings.
6. Top-level `COMPONENT` definitions are excluded from routes/planes.

Still skipped (with warnings): boolean operations, complex vector
geometry beyond bounding shapes, and Lottie sources.

## 8. Known Limitations and Follow-ups

1. `scale`/`rotation_deg` animation props interpolate and report but are
   not yet rasterized by the text/svg mount pipeline.
2. Route activation is currently API-driven (`activate_route`); wiring
   transition triggers to HDI-dispatched handler actions is future work.
3. Gradients import as SVG defs and rasterize through the existing SVG
   pipeline.
