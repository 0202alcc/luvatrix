# Planes Protocol v0

Status: Draft v0.1.0

Planes is a JSON-first 2D app design schema for Luvatrix. A Plane is an object that contains Component objects and deterministic interaction/rendering rules.

## 1. Protocol Goals

1. Define app UI as data ("HTML-like JSON") instead of imperative render code.
2. Keep rendering deterministic across runtimes.
3. Preserve first-party App Protocol safety (capability gating, auditability, validation).
4. Support multiple coordinate frames, layered components, clipping/viewports, and standardized interactions.
5. Enable language-neutral app authoring through schema + function binding contracts.

## 2. Top-Level Document Contract

A Planes document MUST be a JSON object with:

1. `planes_protocol_version: str`
2. `app: object`
3. `plane: object`
4. `components: list[object]`

Optional top-level sections:

1. `scripts: list[object]`
2. `theme_tokens: object`
3. `animations: list[object]`
4. `data_sources: list[object]`

## 3. App Metadata Contract

Required app fields:

1. `id: str`
2. `title: str`
3. `icon: str` (URI/path)

Optional app fields:

1. `description: str`
2. `version: str`
3. `default_locale: str`
4. `web: object`

### 3.1 Web Inheritance Rules

1. `web.tab_title` defaults to `app.title` when omitted or `null`.
2. `web.tab_icon` defaults to `app.icon` when omitted or `null`.
3. Explicit `web.tab_title` / `web.tab_icon` override defaults.

## 4. Plane Metadata Contract

Required plane fields:

1. `id: str`
2. `default_frame: str`
3. `background: object`

Recommended plane fields:

1. `size` (logical width/height expressions)
2. `fonts` (default font family stack and sources)
3. `theme` (token references)
4. `safe_area` / margins

## 5. Units and Normalization

Supported size/position units in v0:

1. `px`
2. `vw`
3. `vh`
4. `%`
5. `pt`
6. `cm`

Normalization rules:

1. Runtime/compiler MUST normalize all units to pixels before layout.
2. `pt` and `cm` conversion MUST use explicit DPI policy.
3. Unresolvable units MUST fail validation in strict mode.

## 6. Component Base Contract

Every component MUST include:

1. `id: str`
2. `type: str`
3. `position: {x, y, frame?}`
4. `size: {width, height}`
5. `z_index: int`
6. `visible: bool` (default `true`)

Optional shared fields:

1. `interaction`
2. `functions`
3. `interaction_bounds`
4. `props`
5. `animations`

## 7. Coordinate Frames

1. `plane.default_frame` is the fallback frame.
2. `component.position.frame` overrides the plane default.
3. Interaction coordinates MUST be transformed into the component's expected frame before dispatch.
4. Render placement MUST be transformed into runtime render frame (`screen_tl`) before draw.

## 8. Interaction Contract (HDI-Normalized)

Function hooks MUST map to normalized HDI lifecycle names.

Supported v0 hook names:

1. `on_press_down`
2. `on_press_repeat`
3. `on_press_hold_start`
4. `on_press_hold_tick`
5. `on_press_up`
6. `on_press_hold_end`
7. `on_press_single`
8. `on_press_double`
9. `on_press_cancel`
10. `on_hover_start`
11. `on_hover_end`
12. `on_drag_start`
13. `on_drag_move`
14. `on_drag_end`
15. `on_scroll`
16. `on_pinch`
17. `on_rotate`

Additional interaction flags:

1. `draggable: bool`
2. `pointer_capture: bool`

Unknown hook names MUST fail strict validation.

## 9. Script Registry and Function Resolution

Planes supports custom scripts through explicit script registration.

### 9.1 Script Registry

`scripts[]` entry fields:

1. `id: str`
2. `lang: str` (for example `python`, `javascript`, `wasm`)
3. `src: str` (path/URI)

### 9.2 Function Target Syntax

Component `functions` values MUST use:

`<script_id>::<function_name>`

Example:

`"on_press_single": "main_handlers::refresh_data"`

### 9.3 Resolution Rules

1. Resolve `script_id` in `scripts` registry.
2. Load script from `src`.
3. Resolve `function_name` export/symbol.
4. Verify callable signature for event handler contract.
5. Fail initialization in strict mode if any binding fails.

Recommended handler signature:

1. `handler(event_ctx, app_ctx) -> action | None`

## 10. Viewport / Clip Window Semantics

A viewport is a component that exposes a rectangular window into larger content.

Viewport v0 required props:

1. `clip: bool` (MUST be true for clipping behavior)
2. `content_ref: str` (target component id)
3. `scroll: {x, y}` (logical offset)

Rules:

1. Viewport clip rectangle is defined by viewport `position + size`.
2. Content is transformed by viewport `scroll` offsets before clipping.
3. Pointer events inside viewport MUST be remapped to content coordinates.
4. Scroll state updates MUST be deterministic and bounded.

## 11. Ordering Rules

1. Paint order: `z_index` ascending, then source order ascending.
2. Hit-test order: reverse paint order.
3. Event dispatch stops at first consumer unless explicit bubbling is enabled.

## 12. Strict vs Permissive Modes

Strict mode requirements:

1. Unknown fields fail.
2. Unknown hooks fail.
3. Missing/invalid script bindings fail.
4. Invalid unit conversions fail.

Permissive mode behavior:

1. Unknown fields warn.
2. Missing bindings become no-op with warning.
3. Invalid components may be dropped with warning.

CI/release builds SHOULD use strict mode.

## 13. Security and Capability Boundary

1. Script execution MUST remain within runtime capability policy.
2. Component functions MUST NOT bypass capability checks.
3. Security/audit events SHOULD capture script binding and invocation outcomes for privileged actions.

## 14. Gantt + Agile Feature Profile (Required)

For a Gantt/Agile app, Planes v0 MUST support:

1. `text` components for labels/titles.
2. `svg` components for vector bars, badges, and icons.
3. `viewport` components for scroll/pan regions.
4. Deterministic layering (`z_index`) for overlays/tooltips.
5. HDI-normalized interactions for selection, drag, hover, and scroll.
6. Script-bound handlers for card click-through and timeline navigation.
7. Themed tokens for status color mapping (`Backlog`, `Ready`, `In Progress`, `Review`, `Done`, `Blocked`).

Recommended first implementation set:

1. Timeline lane header strip
2. Milestone/task bar lane with dependency lines
3. Agile board columns with card stacks
4. Shared viewport controls for both views

## 15. Minimal Example

```json
{
  "planes_protocol_version": "0.1.0",
  "app": {
    "id": "com.luvatrix.gantt_agile",
    "title": "Planning Workspace",
    "icon": "assets/planning.svg",
    "web": {
      "tab_title": null,
      "tab_icon": null
    }
  },
  "plane": {
    "id": "main",
    "default_frame": "screen_tl",
    "background": {"color": "#101820"}
  },
  "scripts": [
    {"id": "planning_handlers", "lang": "python", "src": "scripts/planning_handlers.py"}
  ],
  "components": [
    {
      "id": "title",
      "type": "text",
      "position": {"x": 50, "y": 16, "frame": "screen_tl"},
      "size": {"width": {"unit": "vw", "value": 100}, "height": {"unit": "px", "value": 24}},
      "z_index": 10,
      "props": {"text": "Planning Workspace", "align": "center"}
    },
    {
      "id": "board_viewport",
      "type": "viewport",
      "position": {"x": 30, "y": 45},
      "size": {"width": {"unit": "px", "value": 760}, "height": {"unit": "px", "value": 360}},
      "z_index": 5,
      "functions": {
        "on_scroll": "planning_handlers::scroll_board",
        "on_press_single": "planning_handlers::select_card"
      },
      "props": {
        "clip": true,
        "content_ref": "agile_columns",
        "scroll": {"x": 0, "y": 0}
      }
    }
  ]
}
```

## 16. Versioning and Evolution

1. Planes versioning is independent from app protocol runtime version.
2. App manifests SHOULD declare which Planes version they target.
3. New versions MUST define compatibility and migration notes.
4. Future `v0.x` changes should remain additive when possible.

## 17. First-Party Runtime Loader (Developer UX)

Apps SHOULD use the first-party loader so they do not implement custom compiler/render boilerplate.

Tiny `app_main.py` pattern:

```python
from pathlib import Path
from luvatrix_ui.planes_runtime import load_plane_app

APP_DIR = Path(__file__).resolve().parent

def open_card(event_ctx, app_state):
    app_state["last_action"] = ("open_card", event_ctx.get("component_id"))

def create():
    return load_plane_app(
        APP_DIR / "plane.json",
        handlers={
            "handlers::open_card": open_card,
        },
        strict=True,
    )
```

Loader responsibilities:

1. parse + validate Planes payload
2. compile Planes to shared UI IR
3. handle component mounting + frame render pipeline
4. dispatch HDI-normalized hooks to registered handlers
