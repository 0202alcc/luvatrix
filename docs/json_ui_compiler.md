# Luvatrix JSON UI Compiler Spec (Draft v0)

This document defines a first-party JSON-to-component compiler for app protocol apps.

The compiler goal is deterministic conversion from design JSON (page JSON now, Lottie-derived JSON later) into a renderable component tree and action wiring that can be compiled into matrix writes for the next frame.

## 1. Position in the Runtime

1. App code loads JSON.
2. Compiler validates and normalizes JSON into a typed UI IR.
3. Runtime mounts IR components in a UI frame pass.
4. `MatrixUIFrameRenderer` compiles mounted components into a single RGBA tensor.
5. App protocol submits one `WriteBatch(FullRewrite(...))` for that frame.

## 2. Compiler Phases

1. Parse:
   Read JSON text into raw objects.
2. Validate:
   Check required keys, types, and value ranges.
3. Normalize:
   Resolve defaults for frame, bounds, opacity, z-index, and style.
4. Bind:
   Resolve interaction action names against app backend action registry.
5. Emit:
   Produce IR objects sorted in deterministic draw order.

## 3. Recommended Source Schema

Top-level shape:

```json
{
  "page_id": "home",
  "viewport": {"width": 640, "height": 360},
  "background": "#0b1020",
  "default_frame": "cartesian_bl",
  "elements": []
}
```

Element shape (component-generic):

```json
{
  "id": "cta",
  "type": "svg",
  "z_index": 100,
  "position": {"x": 60, "y": 240, "frame": "cartesian_bl"},
  "interaction_bounds": {"x": 60, "y": 240, "width": 120, "height": 44, "frame": "cartesian_bl"},
  "functions": {
    "on_press": "open_settings",
    "on_hover_start": "preload_settings"
  },
  "props": {}
}
```

Text-specific `props`:

```json
{
  "text": "Play",
  "font": {"family": "Comic Mono", "file_path": null, "weight": 400, "slant": "regular"},
  "size": {"unit": "ratio_display_height", "value": 0.06},
  "appearance": {
    "color_hex": "#FFFFFF",
    "opacity": 1.0,
    "letter_spacing_px": 0,
    "line_height_multiplier": 1.2,
    "underline": false,
    "strike": false
  },
  "max_width_px": 320
}
```

SVG-specific `props`:

```json
{
  "svg": "assets/button.svg",
  "width": 120,
  "height": 44,
  "opacity": 1.0
}
```

## 4. UI IR Contract

Recommended IR fields per node:

1. `id: str`
2. `type: "text" | "svg" | ...`
3. `z_index: int`
4. `mount_order: int` (source order for deterministic ties)
5. `frame: str`
6. `visual_bounds: BoundingBox`
7. `interaction_bounds: BoundingBox`
8. `events: ActionBindings`
9. `payload: typed component payload`

Rules:

1. `interaction_bounds` defaults to `visual_bounds`.
2. `interaction_bounds` never changes visual paint.
3. Paint order is `z_index ASC`, then `mount_order ASC`.
4. Hit-test order is reverse paint order.

## 5. Coordinate Frame Rules

1. Page-level `default_frame` is used if component frame is absent.
2. Component-level `position.frame` overrides page default.
3. `interaction_bounds.frame` defaults to component frame.
4. Runtime transforms all component placement into render frame (`screen_tl`) before raster write.
5. HDI events should be transformed into the frame expected by hit-test logic before dispatch.

## 6. Action/Function Binding

`functions` maps interaction hooks to backend function names.

Example:

```json
{
  "functions": {
    "on_press": "open_settings",
    "on_press_hold": "show_context_menu"
  }
}
```

Recommended backend registration:

```python
handlers = {
    "open_settings": open_settings,
    "show_context_menu": show_context_menu,
}
```

Binding semantics:

1. Compiler stores action name strings in IR.
2. Runtime resolves action names against backend registry at app init.
3. Missing action names should fail fast in strict mode.
4. Non-callable bindings should fail compile.
5. Action execution receives a normalized event context (`component_id`, frame-local pointer, press phase, active keys, app state handle).

## 7. Strict vs Permissive Compile Modes

`strict` mode:

1. Unknown fields fail compile.
2. Missing action handlers fail compile.
3. Asset load failures fail compile.

`permissive` mode:

1. Unknown fields are ignored with warnings.
2. Missing action handlers are stubbed as no-op with warnings.
3. Invalid elements are dropped with warnings.

Use `strict` in CI and release builds.

## 8. Lottie Ingest Mapping (Planned)

For Figma/Lottie export support:

1. Parse Lottie layers.
2. Map shape/image/text layers into first-party component IR where possible.
3. Preserve timing/animation metadata as optional runtime animation tracks.
4. Carry layer index into `z_index`.
5. Emit unsupported features as explicit diagnostics.

Recommended initial scope:

1. Static text layers -> `TextComponent`
2. Static vector layers -> `SVGComponent`
3. Position/opacity keyframes -> runtime animation modifiers

## 9. MatrixUIFrameRenderer Generation Path

For each app loop tick:

1. `ctx.begin_ui_frame(renderer, ...)`
2. App mounts compiler-produced components with `ctx.mount_component(...)`
3. `ctx.finalize_ui_frame()`:
   Convert `TextComponent` and `SVGComponent` to batch commands.
   Call renderer batch draw methods.
   Retrieve RGBA frame via `renderer.end_frame()`.
   Submit a single `WriteBatch([FullRewrite(frame)])`.

This keeps component logic in app protocol/runtime and keeps display backends limited to matrix visualization.

## 10. Current Demo App Alignment

`examples/demo_app/page.json` currently uses a minimal schema.

Current implemented fields:

1. `viewport.width`, `viewport.height`
2. `background`
3. `elements[].id`
4. `elements[].svg`
5. `elements[].x`, `elements[].y` (interpreted in bottom-left page frame)
6. `elements[].scale`
7. `elements[].opacity`
8. `elements[].animate` (float only)

Recommended next migration for demo app JSON:

1. Add explicit `type`.
2. Replace `x/y` with `position` object.
3. Add `z_index` and `functions`.
4. Add optional `interaction_bounds`.
5. Switch compiler output to shared IR object model.

## 11. Known Limitations

1. v0 text rendering does not include advanced shaping/kerning engine behavior.
2. SVG support is intentionally narrow and does not cover full SVG spec.
3. JSON action dispatch contract is specified here but not fully wired in runtime yet.
4. Layout constraints/flex/grid are out of scope for this phase.

## 12. Extraction Boundary

Keep this compiler and contracts cleanly extractable into a future `luvatrix-ui` package:

1. No macOS imports in compiler or component contracts.
2. No direct presenter/backend calls in compiler.
3. Only typed contracts to app protocol runtime (`mount_component`, frame compile).

## 13. In-Repo Typed Schema Reference

Current typed draft for this spec lives at:

- `luvatrix_ui/ui_ir.py`

It includes:

1. dataclass contracts (`UIIRPage`, `UIIRComponent`, related nested specs)
2. parse/validate helpers (`UIIRPage.from_dict`, `validate_ui_ir_payload`)
3. embedded JSON Schema (`UI_IR_PAGE_JSON_SCHEMA`)
