# Spotify Light

A lightweight Spotify desktop client built **natively on luvatrix** — the Python
app protocol renders through the luvatrix scene graph to the macOS Metal target,
with no Electron, no Chromium, and no webview. The data layer is the real Spotify
Web API: OAuth sign-in, browse/search/library reads, and Spotify Connect playback
control with now-playing polling.

```
uv sync --extra macos
uv run python main.py run-app examples/spotify_light --render macos-metal
```

## What you get

- **Sign-in** — OAuth Authorization Code + PKCE with a loopback redirect on
  `http://127.0.0.1:8888/callback`; tokens refresh automatically and are stored
  `0600` under the config dir.
- **Sidebar** — Home / Search / Your Library, your playlists, account chip,
  log out.
- **Home** — greeting plus card sections: Top tracks, New releases, Your
  playlists, Top artists.
- **Playlist detail** — header art + Play button, full track table with
  title/artists/album/duration and an accent highlight on the playing track.
- **Search** — the dock's search circle expands into the query field while
  the library docks as a floating panel right-aligned above it (SL-39);
  debounced as-you-type search keeps results in the content area with
  Songs / Albums / Artists / Playlists groups. Dismiss via the field's × cap
  or Escape to restore the left rail.
- **Now-playing bar** — art, transport (shuffle, previous, play/pause, next,
  repeat), draggable seek bar, volume, and a device picker popup (Spotify
  Connect).
- **Efficiency** — render-on-invalidation scheduling (`set_continuous_render(False)`);
  the loop idles until input, poll results, or playback ticks request a frame.

## Native macOS controls (luvatrix feature)

The Client ID setup field is a **real `NSTextField`** on macOS Metal — native
focus ring, key handling, paste (⌘V or the field's right-click context menu),
and IME — not a painted imitation. This is the
first consumer of the luvatrix native-controls feature:

- `main.py` wires every macOS render path through
  `luvatrix_core.platform.macos.native_controls.wire_native_controls`, which
  registers an `AppKitNativeControlBridge` for the window and wraps the HDI
  source in a `GatedHDIEventSource`. The gate drops keyboard events while a
  native field is first responder and clicks/scrolls that land on a native
  control, so the app never double-handles input the OS already consumed.
- Apps read the active bridge via `luvatrix.app.native_controls()` and create
  fields with `bridge.create_text_field(...)`; frames are given in scene
  logical coordinates (top-left origin), and the bridge converts to AppKit
  view points (including the Y-flip and any content-scale factor).
- The bridge also embeds glass buttons (`create_button`) and a full web view
  (`create_web_view`, WKWebView) — the latter powers the embedded Spotify
  sign-in: navigations matching the loopback redirect URI are cancelled by
  the navigation delegate and reported to the app, so the OAuth handshake
  completes without leaving the window.
- Off macOS (or without PyObjC) `native_controls()` returns an unavailable
  bridge and the app falls back to its drawn field unchanged — same geometry,
  same hit regions.

Manual check on a Mac: launch with `--render macos-metal`, click the Client ID
field (blue focus ring appears), type or paste (⌘V, or right-click → Paste),
press **Enter** to save, and
resize-independence is covered by the window's fixed logical size. Typing must
not trigger the app's keyboard shortcuts while the field is focused.

## Liquid Glass (macOS 26 Tahoe)

On macOS the chrome is backed by real system glass plates via the
native-controls bridge's `create_glass_surface(...)`:

- **macOS 26+**: `NSGlassEffectView` (looked up at runtime — no hard PyObjC
  symbol requirement).
- **Below macOS 26**: `NSVisualEffectView` fallback (Sidebar material for the
  sidebar, HUD elsewhere, within-window blending, always active).
- **Off macOS / headless**: an unavailable bridge, and the app draws its
  original opaque backgrounds — pixel-identical to the pre-glass layout.

App-declared glass regions:

- **Sidebar** — full-height plate; the scene draws only a low-alpha tint over
  it so artwork and content glow through.
- **Now-playing pill** — the player chrome is a centered floating capsule
  (scene-drawn simulated glass) flanked by circular nav buttons. Content
  rows/cards flow under the dock zone instead of being culled, but a bottom
  scrim (transparent → near-opaque backdrop gradient) dissolves them before
  they reach the pill, and the bottom scroll inset lets the last row scroll
  fully clear of the pill.
- **Client ID field (login)** — the field sits borderless inside a rounded
  glass container (corner radius 20) instead of painting its own bezel. The
  native focus ring is suppressed (`NSFocusRingTypeNone`): the capsule is the
  affordance, not an accent-colored rectangle.
- **Auth-wall buttons** — Save and Connect Spotify are real borderless
  `NSButton`s inside matching glass capsules (created via
  `bridge.create_button(...)`); the drawn versions return when no bridge is
  available. Each capsule gets a low-alpha light tint drawn beneath it so the
  glass reads on the near-black backdrop.

Glass plates are decorative AppKit siblings layered above the Metal surface;
they never intercept scene input. Creating three plates adds a low
single-digit MB of AppKit/memory overhead.

Manual check on macOS 26+: sidebar and player bar show real glass blur/vibrancy
over the desktop wallpaper tint, scrolling content visibly flows under the
player bar, and the login Client ID field is borderless inside a frosted
capsule. On macOS 15 and below the same layout renders with vibrancy plates;
on Linux/headless everything looks exactly as before glass landed.

## Agent control (MCP)

The app is drivable by a local MCP client (agent, IDE, test harness) — useful
for agentic building and validation instead of synthetic OS events. The app
opts in via `[mcp] enabled = true` in `app.toml`; add the runtime flag:

```bash
uv run python main.py run-app examples/spotify_light --render macos-metal --mcp
```

- **Discovery** — the session lands in `examples/spotify_light/.luvatrix/mcp-session.json`
  (mode `0600`): JSON-RPC over HTTP at `http://127.0.0.1:<port>/mcp` with a
  per-run bearer token. Stdio-only clients bridge with
  `uv run python main.py mcp-proxy examples/spotify_light` (NDJSON on
  stdin/stdout). See `docs/mcp_mode.md`.
- **Built-ins** — `app_state` (includes the `mcp_state()` snapshot below),
  `app_scene_tree`, `app_screenshot` (raw RGBA), `app_logs`, `app_input`
  (synthetic HDI events through the real input path — clicks drive scene hit
  regions), and deterministic control: `app_pause` / `app_step` / `app_resume`
  / `app_stop`.
- **App snapshot** (`mcp_state()`, merged into `app_state` under `"app"`) —
  `view`, `authenticated`, `client_id_configured`, `client_id_draft_len`
  (never the value), `native_field_active`, `search_query`, `content_scroll`,
  `hit_actions` (affordance discovery), `now_playing` summary.
- **App tools** — `sl_set_client_id {value}` and `sl_submit_client_id {}`.

**Native-field caveat:** while the Client ID `NSTextField` is up, AppKit owns
its key path — synthetic `app_input` keystrokes cannot type into it. Use
`sl_set_client_id` to set the text and `sl_submit_client_id` to save; that's
what they're for. The OAuth consent that follows stays human-driven inside
the embedded web view (Spotify's own page; credentials never touch app code),
but the agent can click **Connect Spotify** via `app_input` and poll
`app_state` for `authenticated`.

## Spotify app setup (one time)

1. Create an app at <https://developer.spotify.com/dashboard> → *Create app*.
2. Add the redirect URI `http://127.0.0.1:8888/callback` in its settings.
3. Apps in *development mode* only serve users listed under *User management* —
   add your Spotify account email there.
4. Launch Spotify Light and paste the app's **Client ID** into the setup field
   (saved to the config dir), or export it first:
   `export SPOTIFY_LIGHT_CLIENT_ID=<your client id>`.
5. Click **Connect Spotify** — on macOS the Spotify authorize page opens in an
   embedded web view inside the app: sign in there, the loopback redirect is
   intercepted in-app, and the view dismisses itself. (Spotify requires
   credentials to go through their own page; nothing you type reaches the
   app's code.) Without a native bridge — headless or an unsupported host —
   the same button falls back to opening your system browser.

Playback control requires **Spotify Premium**.

## Run it

| Where | Command |
| --- | --- |
| macOS (Metal UI) | `uv sync --extra macos && uv run python main.py run-app examples/spotify_light --render macos-metal` |
| Linux headless smoke | `uv run python main.py validate-app examples/spotify_light --render headless` |
| Linux headless run | `uv run python main.py run-app examples/spotify_light --render headless --ticks 3 --energy-safety off` |
| Tests | `uv run --extra desktop --with pytest pytest tests/test_spotify_light.py tests/test_spotify_light_app.py tests/test_native_controls.py` |

Headless runs use the matrix fallback (a text status dashboard); the full UI
needs the scene target. Config lives in `~/.config/spotify-light` (override with
`SPOTIFY_LIGHT_CONFIG_DIR`); delete it to sign out everywhere.

### Lighter macOS install (optional)

`--render macos-metal` validates `AppKit/Quartz/Metal/objc` — **not torch**. The
`macos` extra bundles torch for the repo's CPU pipelines, but this app never
imports it. For the lightest footprint, install the base package plus only the
PyObjC pieces (`pyobjc-framework-cocoa`, `pyobjc-framework-quartz`,
`pyobjc-framework-Metal`) and skip the extras.

## Memory footprint

Peak RSS of the running app (240-tick scene loop with warm art cache, measured
via `getrusage`/`VmHWM` on Linux; Metal driver buffers add a little on macOS):

| Configuration | Peak RSS |
| --- | --- |
| luvatrix base install (numpy + Pillow), this app | **~82 MB** |
| same app with the repo `desktop`/`macos` extra (torch imported) | ~552 MB |
| Electron Spotify desktop (commonly reported, multi-process) | ~500 MB–1.5 GB |

The torch number is a repo-extra artifact, not an app requirement — see the
torch-free install note above. Reproduce with the measurement harness in the
PR description, or on macOS run the app under `--render macos-metal` and sample
`ps -o rss=` / `footprint` on the `luvatrix` process.

## How it works

| Module | Role |
| --- | --- |
| `app_main.py` | `App` subclass: worker-job wiring, timers, input dispatch, render gating |
| `sl_views.py` | scene-graph drawing of every view + hit regions |
| `sl_icons.py` | dock/card icon glyphs: Phosphor codepoints + the regular/Fill family split |
| `sl_oauth.py` | PKCE, authorize URL, loopback receiver, token exchange/refresh |
| `sl_api.py` | Web API + Connect endpoints with injectable transport, pagination, error kinds |
| `sl_models.py` | defensive parsers for Spotify's JSON shapes |
| `sl_ui.py` | view-model builders and display math (pure functions) |
| `sl_store.py` | config dir, client id, `0600` token persistence |
| `sl_art.py` | album-art LRU + disk cache, deterministic placeholders |
| `sl_worker.py` | single daemon thread; the render loop never touches the network |

## Icons

Dock and card icons are [Phosphor](https://phosphoricons.com) (MIT): regular
weight for nav/search/overflow/note, Phosphor-Fill for the transport
play/prev/next. The TTFs ship in `assets/fonts/` with their license
(`Phosphor-LICENSE.txt`); the runtime font resolver picks them up from there
on every host, so macOS Metal and the headless CI rasterizer draw identical
icon pixels through the normal text path.

## Limitations and follow-ups

- **No in-app audio.** Spotify streams are DRM-protected (Widevine); this app
  controls playback on Spotify Connect devices instead — pick a device from the
  bar. Integrating [librespot](https://github.com/librespot-org/librespot) as a
  local Connect receiver/player is the planned follow-up for real audio.
- Spotify's November 2024 API changes removed *featured playlists* and
  *recommendations* for new apps; Home leans on top tracks/artists, new
  releases, and your playlists instead.
- Artist detail pages and horizontally scrolling sections are not wired yet;
  the seek and volume bars are the draggable surfaces in v1.
- The window does not yet opt into the full-size-content-view titlebar style
  that lets glass extend behind the title bar; that needs a `create_window`
  flag plumbed through the render targets, so it is a follow-up. Text
  scrolling under the dock zone is dissolved by the bottom scrim before it
  reaches the pill (round 8b), matching Apple Music's own trade-off.
