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
- **Search** — debounced as-you-type search with Songs / Albums / Artists /
  Playlists groups.
- **Now-playing bar** — art, transport (shuffle, previous, play/pause, next,
  repeat), draggable seek bar, volume, and a device picker popup (Spotify
  Connect).
- **Efficiency** — render-on-invalidation scheduling (`set_continuous_render(False)`);
  the loop idles until input, poll results, or playback ticks request a frame.

## Spotify app setup (one time)

1. Create an app at <https://developer.spotify.com/dashboard> → *Create app*.
2. Add the redirect URI `http://127.0.0.1:8888/callback` in its settings.
3. Apps in *development mode* only serve users listed under *User management* —
   add your Spotify account email there.
4. Launch Spotify Light and paste the app's **Client ID** into the setup field
   (saved to the config dir), or export it first:
   `export SPOTIFY_LIGHT_CLIENT_ID=<your client id>`.
5. Click **Connect Spotify** — the browser opens for consent, then returns to
   the app automatically.

Playback control requires **Spotify Premium**.

## Run it

| Where | Command |
| --- | --- |
| macOS (Metal UI) | `uv sync --extra macos && uv run python main.py run-app examples/spotify_light --render macos-metal` |
| Linux headless smoke | `uv run python main.py validate-app examples/spotify_light --render headless` |
| Linux headless run | `uv run python main.py run-app examples/spotify_light --render headless --ticks 3 --energy-safety off` |
| Tests | `uv run --extra desktop --with pytest pytest tests/test_spotify_light.py tests/test_spotify_light_app.py` |

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
| `sl_oauth.py` | PKCE, authorize URL, loopback receiver, token exchange/refresh |
| `sl_api.py` | Web API + Connect endpoints with injectable transport, pagination, error kinds |
| `sl_models.py` | defensive parsers for Spotify's JSON shapes |
| `sl_ui.py` | view-model builders and display math (pure functions) |
| `sl_store.py` | config dir, client id, `0600` token persistence |
| `sl_art.py` | album-art LRU + disk cache, deterministic placeholders |
| `sl_worker.py` | single daemon thread; the render loop never touches the network |

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
