# Static Bundle Format (Schema v1)

Status: Normative for `schema_version: 1`.

The static bundle is the compiled artifact of the planes app container:
`build-web` (Python reference implementation, `luvatrix_ui/planes_static_compile.py`)
turns a container document into `static_bundle.json`, which the browser
runtime (`runtime/static-core.js` + `runtime/luvatrix-static.js`) renders
with no Python and no Pyodide. This document specifies the format so
builders in any language can emit conforming bundles — the format is the
product; the Python builder is a reference implementation.

## 1. Conformance

A bundle is conforming when:

1. It parses as JSON with the structure below.
2. The browser runtime renders it without errors.
3. For containers the Python runtime can also run, the emitted frames are
   **byte-identical** to the Python `PlaneWebApp` output at the same tick
   sequence (see `tools/web/static_core_parity.mjs`, wired into
   `tests/test_planes_static_compile.py`). Parity is the executable spec.

## 2. Top-Level Structure

```json
{
  "schema_version": 1,
  "app": {"title": "string", "icon": "string"},
  "entry_route": "route-id",
  "page_background": "#RRGGBB",
  "display": {"width": 320, "height": 180},
  "planes": [...],
  "routes": [...],
  "components": [...],
  "animations": [...],
  "scripts": [...]
}
```

## 3. Planes

```json
{"id": "home_plane", "background_color": "#RRGGBB", "global_z": 0, "size": {"width": 320, "height": 180}}
```

- `global_z` orders planes (ascending = back to front).
- Plane sizes are px (the static tier does not resolve viewport units for
  planes). `page_background` equals the first plane's background; it is
  what the CLEAR op emits every frame.

## 4. Routes

```json
{
  "id": "home",
  "default": true,
  "active_planes": ["home_plane"],
  "transitions": [
    {"trigger": "navigate_settings", "to_route": "settings", "kind": "fade", "duration_ms": 200, "easing": "ease_out"}
  ]
}
```

- Exactly one route has `default: true`; `entry_route` names it.
- `kind`: `none | fade | slide_left | slide_right | slide_up | slide_down`.
- `easing`: `linear | ease_in | ease_out | ease_in_out`.
- Activation semantics mirror `luvatrix_ui/planes_motion.py`: the active
  plane set swaps immediately; a `fade` crossfades entering
  (opacity = eased progress) against exiting (1 - progress) planes;
  slide kinds offset entering planes in from the named edge and exiting
  planes out the opposite edge. The completion frame always presents the
  settled route.

## 5. Components

```json
{
  "id": "home_title",
  "type": "text",            // or "svg"
  "plane_id": "home_plane",
  "z": 1,
  "x": 10, "y": 10, "unit": "px",   // unit: px | vw | vh
  "width": 120, "height": 24,
  "opacity": 1.0,
  "trigger": "navigate_settings",     // optional declarative navigation
  "handler": "ui::say_hello",         // optional JS handler binding
  // text only:
  "text": "Home (click me)", "font_size_px": 14, "color_hex": "#F5FBFF",
  // svg only:
  "svg_data_url": "data:image/svg+xml;base64,..."
}
```

- `x`/`y` are design-space numbers; `unit` resolves sizes (and positions
  when unitized): `vw` = (value / 100) * display.width, `vh` against
  display.height — mirroring the Python compile's unit resolution.
- Interactions hit-test in reverse paint order; a press fires `trigger`
  (route transition) or dispatches `handler` (see §8).
- Draw order key: `(global_z of the attached plane, z, source index, id)`.

## 6. Animations

```json
{
  "target": "settings_title",
  "trigger": "route_enter",   // route_enter | route_exit | on_mount
  "kind": "fade",
  "duration_ms": 100, "delay_ms": 0,
  "easing": "linear", "loop": "none",   // none | repeat | ping_pong
  "keyframes": [{"at": 0.0, "props": {"opacity": 0.0}}, {"at": 1.0, "props": {"opacity": 1.0}}]
}
```

- Keyframe `at` is normalized progress in [0, 1], ascending.
- `props` are numeric render properties: `opacity`, `offset_x`,
  `offset_y` (scale/rotate are reserved for future raster support).
- Opacity composes multiplicatively with any active transition fade;
  offsets add. Completed `none`-loop animations persist their final
  keyframe props as the rest state.

## 7. Command-Buffer Emission (Determinism)

Per frame the runtime emits the shared web command buffer:
`{headers, floats, strings, width, height}` with flat 4-word headers
`[opcode, float_start, float_count, meta0]` (plus a 5th `font_id` word for
TEXT) and interned strings. The emission order is fixed:

1. `CLEAR` with `page_background`.
2. Components in draw order (active planes only), each advancing the
   float/string tables.

A conforming builder/runtime pair must produce identical headers, floats,
and strings for identical bundle + tick inputs. The node parity harness
compares exactly these three arrays.

## 8. JS Handler Scripts

```json
"scripts": [{"id": "ui", "lang": "javascript", "src": "app/scripts/ui.js"}]
```

- Only `lang: "javascript"` is valid in the static tier (Python scripts
  require the Pyodide tier).
- `src` is a path relative to the build root; the build copies app files
  under `app/`, so sources are addressable as `app/<original src>`.
- The browser entry imports each script as an ES module and maps exported
  functions to `"<script_id>::<export name>"`. A component's `handler`
  names one of these.
- Handler contract:

```js
export function handler_name(event, state) { /* return value ignored */ }
```

with `event = {component_id, event_type: "click", hook: "on_press_single",
payload: {x, y}, fireTrigger}` and `state` a mutable object shared across
handlers (the app state). `event.fireTrigger(name)` activates the named
transition on the current route.

## 9. Versioning

- `schema_version: 1` is current. Additive fields may appear in minor
  revisions without a bump; breaking changes require a new version and a
  runtime feature check. The Python compiler and the JS runtime are
  versioned together in-repo; out-of-tree builders should target this
  document plus the parity harness as their conformance suite.
