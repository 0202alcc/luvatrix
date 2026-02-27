# Luvatrix UI Component Protocol (v0)

This note defines how in-repo `luvatrix_ui` components are expected to be consumed.

## Scope

- Keep `luvatrix_ui` backend-agnostic and free of macOS-specific imports.
- Use typed renderer interfaces (`TextRenderer`, `SVGRenderer`) as API boundaries.
- Treat text rendering as font-dependent glyph-run rendering only in v0 (no shaping engine yet).
- SVG rendering uses explicit target width/height per component command and should rasterize
  directly to target size (vector -> final pixels; no intermediate bitmap scaling).
- Component rendering is compiled by app protocol/runtime into matrix writes; display renderer
  only visualizes the matrix output.

## Interaction Contract

Controls consume standardized HDI keyboard press events:

- `event_type` must be `press`
- `payload.phase` must be one of:
  `down`, `repeat`, `hold_start`, `hold_tick`, `up`, `hold_end`, `single`, `double`, `cancel`

`ButtonModel` maps these into UI state:

- `down` -> `press_down` (when hovered)
- `hold_start`/`hold_tick` -> `press_hold`
- `up`/`cancel` -> `hover` or `idle` based on hover status
- `disabled` overrides all interactive states

## Extraction Notes

- Keep external dependencies out of `luvatrix_ui`; pass renderer implementations from runtime layer.
- Preserve these contracts as stable seams for future extraction into `luvatrix-ui`.

## App Protocol Integration (v0)

- `AppContext.begin_ui_frame(...)` starts a component frame compile pass.
- `AppContext.mount_component(...)` queues components for that frame.
- `AppContext.finalize_ui_frame()` renders queued components and submits one matrix write batch.
- `MatrixUIFrameRenderer` (in `luvatrix_core.core.ui_frame_renderer`) is the default in-repo
  component-to-matrix renderer for first-party text + SVG component batches.

## Shared Component Schema

All first-party components inherit from `ComponentBase` and must support:

1. `component_id`
2. `default_frame`
3. `disabled`
4. `interaction_bounds_override`
5. `visual_bounds()` and `interaction_bounds()`
6. `hit_test(...)` and `on_press(...)`

Rules:

1. `interaction_bounds` defaults to `visual_bounds`.
2. overriding interaction bounds must not change rendered appearance.
3. component events are evaluated against interaction bounds in that bounds frame.

## Coordinate Frames

Coordinate placement supports:

1. default app frame from `AppContext.default_coordinate_frame`
2. per-component frame override via `CoordinatePoint.frame`
3. coordinate notation parsing (`x,y` or `frame:x,y`)

Transform behavior:

1. runtime should transform component placement into render frame (`screen_tl`) before draw
2. runtime should transform HDI pointer coordinates into the requested frame for interaction
3. frame transforms require a transformer when source/target frames differ

## Text Rendering Contract

`TextComponent` and `TextRenderer` contracts are backend-agnostic.

Supported v0 text configuration:

1. font source by system family or explicit file path
2. default family: `Comic Mono`
3. size units:
   `px`, `ratio_display_height`, `ratio_display_width`, `ratio_display_min`, `ratio_display_max`
4. appearance:
   `color_hex`, `opacity`, `letter_spacing_px`, `line_height_multiplier`,
   `underline`, `strike`
5. optional `max_width_px` wrapping constraint

Performance rule:

1. text rendering is full-string batched draw commands
2. components do not issue per-character runtime draw calls

## SVG Rendering Contract

`SVGComponent` and `SVGRenderer` contracts are backend-agnostic.

Rules:

1. SVG command includes explicit target `width` and `height`
2. renderer should rasterize vector data directly at target size
3. opacity is applied as part of blend
4. component visual bounds default to component placement rectangle

## Draw Order and Interaction Order

When components are sourced from a page compiler:

1. draw order should use `z_index` ascending, then source order ascending
2. interaction hit-test order should be reverse draw order
3. event dispatch should stop at first component that consumes the event, unless broadcast is explicitly configured

## JSON Compiler Hand-off

Recommended JSON compiler output for runtime mount:

1. typed component payload (`TextComponent`, `SVGComponent`, ...)
2. resolved frame and coordinates
3. resolved interaction bounds
4. resolved action bindings (`functions`)
5. deterministic ordering metadata (`z_index`, mount order)

See `docs/json_ui_compiler.md` for the source schema and compile pipeline.
