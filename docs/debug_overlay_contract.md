# Overlay Contract (T-2906)

## Scope
Define overlay bounds/dirty-rect/coordinate contracts and non-destructive toggle behavior.

## Overlay Model
1. Overlay uses explicit `bounds` rectangle.
2. Overlay updates include deterministic `dirty_rects`.
3. Coordinate space is explicit: `window_px` or `content_px`.
4. Opacity is clamped to `[0.0, 1.0]`.

## Non-Destructive Toggle Rule
1. Overlay enable/disable must not mutate underlying content digest.
2. Toggle result reports before/after digest equality and `destructive=false`.

## Platform Capability Policy
1. `macos`: supports `debug.overlay.render`.
2. `windows`: explicit `debug.overlay.stub`.
3. `linux`: explicit `debug.overlay.stub`.
