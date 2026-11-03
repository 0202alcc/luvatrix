# Origin Reference Overlay Contract (R-040 Reopen)

## Enablement
- Environment variable: `LUVATRIX_SHOW_ORIGIN_REFS` (`1` enables the overlay; default is off).
- Runtime state: `app.state["origin_refs_enabled"]`.
- Debug menu action: `debug.menu.overlay.origin_refs.toggle`.
- There is no `--show-origin-refs` CLI flag.
- Scope: runtime-local debug visualization only.
- Non-goal: no App Protocol schema/state semantics changes.

## Render Semantics
When enabled, the runtime appends an origin-reference overlay pass **after** normal composition.

Each origin marker emits:
- `+x` axis: red line.
- `+y` axis: green line.
- Origin: blue dot.
- Label: text near the origin.

Axis lengths are fixed pixel lengths for all entities in v1.

## v1 Entity Coverage
- Camera origin (`camera`).
- Active planes (`<plane_id>`).
- Mounted components (`<component_id>`).

## Deterministic Ordering Contract
Render order is deterministic and stable:
1. Camera.
2. Active planes sorted by `(plane_global_z, plane_id)` ascending.
3. Mounted components sorted by `component_id` ascending.

## Transform + Placement Rules
- Origins are computed from resolved runtime transforms, not raw JSON payload values.
- Labels are clamped to viewport bounds to avoid offscreen text placement.

## Interaction Safety
- Overlay is render-only.
- No hit-test routing, input dispatch, or component state mutation is allowed.
