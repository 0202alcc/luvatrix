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
| `mcp.inspect` | `app_state`, `app_screenshot`, `app_scene_tree`, `app_logs` |
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
- `app_logs` — recent log records (ring buffer, 200 entries). The root log
  level is lowered to INFO for the session and restored on shutdown.
- `app_input` — inject synthetic HDI events: `{event: {device, event_type,
  payload}}` or `{events: [...]}`. Events flow through the real normalization
  path (keyboard state machine, touch fan-out, window-geometry bounds) and are
  visible to the app on the next tick. The app still needs the matching
  `hdi.<device>` capability to consume them.
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
  the shipped `layout.toml` parks it 12pt left of the pill, vertically
  centered (`{anchor: "top-right", dx: 548, dy: 48}`)
- `sidebar` — the left rail plate (its contents shift with it)

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
- `layout_list {}` — valid ids plus every active override with its resolved
  rect at the current window size.
- `layout_clear {id?}` — clear one override, or all when `id` is omitted.
  Also persists: the component's code natural returns and survives restart.
- `layout_export {}` — JSON dump of the current specs plus rects resolved at
  the current window size, for inspection.

The persisted file is TOML, one table per component, in exactly the spec
shape `layout_set` accepts (`[nav_more]` with `anchor`/`dx`/`dy`, or
`[nav_more.rect]` with `x`/`y`/`width`/`height`). It is rewritten
deterministically (sorted ids) so diffs stay minimal, and written via a
temp file + replace so a crash can't tear it. Hand edits are fine:
malformed TOML or invalid entries are ignored at boot, never fatal. Tests
redirect the path with `SPOTIFY_LIGHT_LAYOUT_FILE`.

## Notes and limitations

- Bind address is loopback only; the bearer token and the 0600 discovery file
  are the access boundary. Treat both as secrets.
- macOS/iOS/Android/Web render paths work the same as headless; MCP sits in
  the shared run loop.
- While paused, GUI windows stay responsive to target pumping but app code
  does not advance.
