# MCP Mode

MCP mode lets a local MCP client (an agent, an IDE, a test harness) inspect and
drive a running Luvatrix app over the Model Context Protocol.

## Activation

Both are required; either one alone leaves MCP off.

1. App opt-in in `app.toml`:

   ```toml
   [mcp]
   enabled = true
   # Optional: restrict capability families. Default allows all four.
   # allow = ["inspect", "input", "control", "app"]
   ```

2. Runtime flag: `luvatrix run-app <app> --mcp`.

With `--mcp` and no explicit `--ticks`, the app runs until the client stops it
(instead of the headless 600-tick default).

v1 supports in-process apps only (`runtime.kind = "process"` is rejected).

## Transport and discovery

- JSON-RPC 2.0 over streamable HTTP at `http://127.0.0.1:<ephemeral>/mcp`.
- Every request needs `Authorization: Bearer <token>`; the token is generated
  per run.
- The session is discoverable at `<app>/.luvatrix/mcp-session.json`
  (mode 0600): `{protocol_version, url, token, pid, app_id, capabilities,
  started_at}`. It is removed on shutdown.
- Responses are plain JSON; SSE streams (HTTP GET) are not served in v1.

For stdio-only MCP clients, bridge with:

```bash
luvatrix mcp-proxy <app-dir>          # or a direct mcp-session.json path
```

The proxy speaks NDJSON on stdin/stdout and forwards to the HTTP session.

## Capabilities and audit

MCP tools are gated by runtime-side capability families, filtered by
`[mcp] allow`:

| Family        | Tools                                            |
| ------------- | ------------------------------------------------ |
| `mcp.inspect` | `app_state`, `app_screenshot`, `app_scene_tree`, `app_drawable_probe`, `app_window_stack`, `app_frame_time_probe`, `app_logs` |
| `mcp.input`   | `app_input`                                      |
| `mcp.control` | `app_pause`, `app_step`, `app_resume`, `app_stop` |
| `mcp.app`     | app-defined tools                                |

Grant/deny decisions are written to the capability audit logger
(`granted_mcp_capability` / `denied_mcp_capability`), including SQLite audit
sinks from `--audit-sqlite`.

## Built-in tools

- `app_state` — app id, runtime telemetry, gate state, and the app's
  `mcp_state()` snapshot (when defined).
- `app_screenshot` — current frame as raw RGBA (base64): `{width, height,
  format: "raw_rgba", source, data_base64}`. Uses the retained scene frame
  when scene render mode produced one (`source = "scene_retained"`), else the
  window matrix (`source = "matrix"`).
- `app_scene_tree` — serialized nodes of the latest retained scene frame.
- `app_drawable_probe` — read back the PRESENTED GPU drawable and report
  per-pixel alpha (macOS Metal scene target only). Unlike `app_screenshot`,
  which re-rasterizes the scene on the CPU, this blits the CAMetalDrawable
  texture into a CPU-readable texture inside the present command buffer and
  analyzes what the window server actually receives: global alpha stats plus
  per-region `{alpha_mean, rgb_mean, ...}` samples. Optional arguments:
  `regions` (scene-space rects `[{name?, x, y, width, height, expected_alpha?}]`;
  defaults to regions derived from the latest scene frame — every translucent
  fill with its expected alpha, text runs, and one inter-fill gap) and
  `wait_s` (capture timeout, default 2s; one frame is captured per call).
  Returns `{available: false, reason}` on non-Metal targets or when no frame
  presents in time. Region expectations are composite-aware: `expected_alpha`
  is the theoretical source-over stack beneath the sampled fill (not the
  fill's own alpha), compared against the region floor (`alpha_min`); a
  region fully covered by an opaque node reports `expected_skipped:
  "covered_by_opaque"` and a null match flag instead of a misleading False.
- `app_window_stack` — dump the live NSWindow view/layer hierarchy with the
  properties that decide Core Animation compositing (macOS Metal scene target
  only): per-view class, frame, depth-first z-order, `isOpaque`, background
  alpha, NSVisualEffectView `material`/`blendingMode`/`state`, and the
  CAMetalLayer's `pixelFormat`, `framebufferOnly`, and `isOpaque`. Where
  `app_drawable_probe` verifies the renderer's alpha, this verifies what the
  window stack does with it. Best-effort: failing properties are collected
  under `notes`/per-view `error` and never crash the app.
- `app_frame_time_probe {frames?, wait_s?, drive?}` — time the present path
  under a synthetic scroll (macOS Metal scene target only). Scroll injection
  is banned for measurement, so by default (`drive: true`) the probe
  publishes a real transform-only revision per tick — a 1px content-offset
  oscillation around the presented frame's offset, mirroring the
  retained-scroll hot path and restored when the chain ends — and records
  per-frame phase timings:
  `drawable_wait_ms` (CA/GPU backpressure, e.g. the window backdrop material
  recompositing), `setup_ms`, `encode_ms` (scene raster), `commit_ms`, and
  `gap_ms` (present-loop turnaround + app scene build between presents).
  With `drive: false` the probe records passively instead — no synthetic
  invalidate chain — so `gap_ms` reflects whatever the human drives (e.g.
  hand-scrolling the retained content band) between presents. Returns the
  raw series plus mean/p50/p95/max per phase; a timeout still returns the
  partial series. Run it before/after a candidate fix (for example with and
  without `LUVATRIX_VEV_RASTERIZE=1`) to name the cost center from data.
- `app_logs` — recent log records (ring buffer, 200 entries). The root log
  level is lowered to INFO for the session and restored on shutdown.
- `app_input` — inject synthetic HDI events: `{event: {device, event_type,
  payload}}` or `{events: [...]}`. Events flow through the real normalization
  path (keyboard state machine, touch fan-out) and are visible to the app on
  the next tick. The app still needs the matching `hdi.<device>` capability
  to consume them. Position payloads (`x`/`y`) are SCENE coordinates — the
  same space `app_screenshot`, `app_scene_tree`, and `app_state` report — so
  injected input lands on the same point no matter how the window has been
  resized; bounds are validated against the scene extent. Use
  `screen_x`/`screen_y` instead when you hold raw screen points: those route
  through window geometry and project into the scene exactly like
  OS-delivered events.
- `app_pause` / `app_step {ticks}` / `app_resume` — deterministic run-loop
  control. While paused, targets keep pumping and inspection tools keep
  working; `app_step` releases an exact number of ticks.
- `app_stop` — graceful stop (works while paused).

## App-defined tools

An app lifecycle object may expose hooks:

```python
class App:
    def mcp_tools(self):
        return [{"name": "demo_get_count",
                 "description": "Get loop count.",
                 "inputSchema": {"type": "object", "properties": {}}}]

    def mcp_call(self, name, arguments):
        if name == "demo_get_count":
            return {"count": self.count}
        raise KeyError(name)

    def mcp_state(self):
        return {"count": self.count}
```

- Tool calls queue on the MCP server thread and execute on the runtime thread
  between ticks, so app code needs no extra locking. Calls time out (default
  10 s) when the loop is paused or not ticking.
- Tool names must not start with `app_` (reserved for built-ins); colliding or
  malformed entries are skipped with a warning.
- `mcp_state()` snapshots refresh per tick and merge into `app_state` under
  the `"app"` key.

## Spotify Light: live layout overrides

`examples/spotify_light` exposes the layout-tool loop: nudge chrome positions
on the running app, and the nudge persists — `layout_set`/`layout_clear`
write through to `examples/spotify_light/layout.toml`, the same declarative
file the app reads at startup, so a moved component survives restart and
shows up as an ordinary git diff in the worktree.

Addressable component ids:

- `pill` — the now-playing capsule (art, metadata, progress, transport ride it)
- `nav_home`, `nav_search` — the bottom-dock circles
- `nav_more` — the overflow circle (volume, shuffle, repeat, devices popup);
  the shipped `layout.toml` ATTACHES it into the pill's top-right slot
  (`["nav_more".attach]` with `container = "pill"`, `slot = "top-right"`,
  `inset = 12` — round 41, SL-26/27): it rides the pill's corner inside
  the glass, keeps its 44pt size, and the text column yields its slot.
  Detached (after `layout_clear`), the dock natural returns.
- `sidebar` — the left rail plate (its contents shift with it)

Interior ids rearrange the pill's inside in PILL-LOCAL space: `(0, 0)` is
the pill's top-left, rects and anchors clamp into the pill's current rect
(never the window), and locals compose with whole-pill moves — overriding
`pill` carries the interior, and an interior override keeps its local offset
when the pill moves. `layout_set`, `layout_list`, and `layout_export` report
interior rects in these local coordinates.

- `pill.art` — the album tile (also the idle thumb). Square: the drawn side
  is `min(width, height)`.
- `pill.title` — the title/artist text column ("Nothing playing" + subtitle
  when idle). Above all the alignment REFERENCE for the progress strip;
  moving it moves the texts.
- `pill.progress` — the progress strip; `x`/`y`/`width` are layout inputs
  (height stays 3pt) and the elapsed/remaining labels ride above the
  strip's ends. The shipped `layout.toml` aligns its left edge to
  `pill.title`'s left edge (SL-21). Round 40 (SL-25): the strip's natural
  SPANS THE TEXT COLUMN — left edge on the title, right edge on the
  column's right edge — and the align relationship no-ops on the natural
  while still guarding the column edge. Round 41 (SL-26/27): the column
  yields the attached ⋯ menu's slot, so at 1280×800 the strip resolves to
  pill-local `(110, 59, 394, 3)` (right edge 504 == menu.left − 12) and
  title/artist/bar all follow the narrower column. The bar's midpoint
  sits a constant 21pt right of the play center (the art tile skews the
  column) — known and accepted; play itself stays pill-centered (SL-23).
  This replaces SL-24's centered-on-play derivation.
- `pill.transport` — the prev/play/next cluster, positioned by the rect's
  center. Cluster size is not a layout input: the buttons keep fixed offsets
  and 34pt hit targets. Round 38 (SL-23): the natural centers on the PILL
  itself — `PILL_W` is 2 × the transport center (572), so the play button
  is the plate's geometric center by construction at any width, and the
  empty right half after "next" mirrors the left half.

Tools:

- `layout_set {id, rect: {x, y, width, height}}` or
  `layout_set {id, anchor, dx, dy, width?, height?}` — move a component and
  persist the spec. Anchors are `top-left`, `top-right`, `bottom-left`,
  `bottom-right`, or `center`; `dx`/`dy` measure inward from that window
  corner, so `{id: "pill", anchor: "top-right", dx: 16, dy: 16}` reproduces
  the pill's own layout rule and follows window resizes. Prefer the anchor
  form: it persists resize-safe, while a raw `rect` is only the degenerate
  fallback. Overrides are consulted at draw time: they win over the app's
  per-frame layout recomputation, and state changes cannot stomp them. Rects
  clamp into the window; unknown ids fail with an error listing the valid
  ids, and a rejected spec never reaches the scene. A failed file write
  rolls the override back and errors the call — a nudge that cannot persist
  never pretends it did.
- `layout_align {id, edge, to, ref_edge?, offset?, keep?}` — align one edge
  of a component (`edge`: `left`/`right`/`top`/`bottom`/`center_x`/
  `center_y`) to an edge of another component's CURRENT rect (`to` +
  `ref_edge`, defaulting to `edge`), plus `offset` points (default 0).
  Edge alignment keeps the component's opposite edge fixed (its extent
  changes); center alignment keeps its size; `keep: "size"` (round 38)
  makes an EDGE rule a position move instead — the named edge meets the
  reference line and the extent holds (for a component whose natural sits
  past the reference, which the default would collapse). What persists is
  the RELATIONSHIP — an `[id.align]` spec resolved at layout time — so the
  edge tracks the reference if the reference later moves, and the result
  stays resize-safe. Calls upsert one rule per axis: a second call on the
  other axis adds to the relationship (two rules max, persisted as an
  array of tables), a same-axis call replaces its rule, and any
  rect/anchor spec on the id is replaced by the align form. References
  stay in one frame: interior ids reference interior ids (or the pill
  frame itself as `pill`), window ids reference window ids; self-
  references, cross-axis pairs, and reference cycles are rejected before
  they reach the scene or the file. Example (SL-21's bake):
  `layout_align {id: "pill.progress", edge: "left", to: "pill.title",
  ref_edge: "left"}` pins the strip's left edge to the text column.
  (SL-23's two-axis `nav_more` align parked the overflow circle left of
  the pill; SL-26 cleared those rules with `layout_clear` and replaced
  them with the `layout_attach` containment below.)
- `layout_attach {id, container, slot, inset?}` — attach a window-space
  component INTO a container at a named slot (`top-right`, `top-left`,
  `bottom-right`, `bottom-left`), `inset` points in from the container's
  corner (default 0). The component switches to container-local space:
  it rides the container's CURRENT rect (natural or overridden) like the
  pill's interior ids, keeps its size, and clamps inside the container.
  What persists is the RELATIONSHIP — an `["id".attach]` spec (`id`,
  `container`, `slot`, `inset`) resolved at layout time — resize-safe,
  never raw pixels. The slot's occupied region is queryable by the
  container's own layout (`slot_reservations`): the pill's text column
  yields a top-right attachment, narrowing title/artist/bar left of it.
  `layout_clear` detaches back to the window-space natural; a rect or
  anchor spec replaces the attachment. Validation rejects self-attach,
  attach/align reference cycles, unknown containers or slots, and
  interior ids on either side — before the scene or the file is touched.
  Example (SL-26's bake, the tool's first persisted use):
  `layout_attach {id: "nav_more", container: "pill", slot: "top-right",
  inset: 12}` merges the overflow button into the pill's top-right
  corner; the playback popup re-anchors to drop from the pill's bottom,
  right-aligned to the circle.
- `layout_list {}` — valid ids plus every active override with its resolved
  rect at the current window size.
- `layout_clear {id?}` — clear one override, or all when `id` is omitted.
  Also persists: the component's code natural returns and survives restart.
- `layout_export {}` — JSON dump of the current specs plus rects resolved at
  the current window size, for inspection.

## Spotify Light: live visual effects (SL-34)

The same write-through loop covers scrim/gradient bands — the kind the old
`draw_top_scrim`/`draw_dock_scrim` hardcoded (both removed: SL-33/SL-35, so
the app boots with zero declared effects and renders none). Effects are
declared data, tuned live, and persisted as `["<id>".effect]` tables in the
SAME `layout.toml`:

- `effect_apply {id, kind?, edge, height, fade?, alpha?, margin?}` — add or
  tune an effect. The one kind today is `scrim` (default): a solid backdrop
  band in from `edge` (`top`/`bottom`/`left`/`right`), then a smoothstep
  fade. `height` is the total thickness (band + fade), `fade` the gradient
  length (0..height), `alpha` the band opacity (0-255), `margin` an inset
  along the band's long axis (x for top/bottom, y for left/right; 240 keeps
  a top/bottom scrim off the sidebar). A partial call on an existing id
  tunes — omitted knobs keep their stored values
  (`effect_apply {id: "scrim.dock", alpha: 120}` dims a dock dissolve).
  New ids need `edge` + `height`. The band renders on the next frame and
  the spec persists. Recreate the old dock idiom with
  `effect_apply {id: "scrim.dock", edge: "bottom", height: 148, fade: 56,
  alpha: 240, margin: 240}`.
- `effect_remove {id?}` — remove one effect, or all when `id` is omitted.
  Also persists: the band disappears on the next frame and the file drops
  the table.
- `effect_list {}` — declared effects with their specs and each scrim's
  region resolved at the current window size. Read-only.

The persisted file is TOML, one table per component, in exactly the spec
shape the tools accept (`["nav_more"]` with `anchor`/`dx`/`dy`,
`["nav_more".rect]` with `x`/`y`/`width`/`height`,
`["pill.progress".align]` with `edge`/`to`/`ref_edge`/`offset`, a
two-axis relationship as two `[["nav_more".align]]` array entries, the
x-axis rule first, or `["nav_more".attach]` with
`container`/`slot`/`inset`). Table headers quote the id so dotted interior ids stay
one literal key (an unquoted `[pill.progress.rect]` would parse as nested
tables and collide with `[pill]`). It is rewritten deterministically
(sorted ids) so diffs stay minimal, and written via a temp file + replace
so a crash can't tear it. Hand edits are fine: malformed TOML or invalid
entries are ignored at boot, never fatal. Tests redirect the path with
`SPOTIFY_LIGHT_LAYOUT_FILE`.

## Notes and limitations

- Bind address is loopback only; the bearer token and the 0600 discovery file
  are the access boundary. Treat both as secrets.
- macOS/iOS/Android/Web render paths work the same as headless; MCP sits in
  the shared run loop.
- While paused, GUI windows stay responsive to target pumping but app code
  does not advance.
