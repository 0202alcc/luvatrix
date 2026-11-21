# eme-probe (SL-30)

Minimal macOS probe harness answering one question: **can a WKWebView host
the Spotify Web Playback SDK** (which needs working EME/DRM), or do we need a
Chromium-based surface?

It opens a small WKWebView, then:

1. runs `navigator.requestMediaKeySystemAccess` for `com.widevine.alpha`,
   `com.apple.fps`, `com.apple.fps.1_0/.2_0/.3_0`, and `org.w3.clearkey`
   against two audio configs (AAC in MP4, Opus in WebM), exercising
   `createMediaKeys()` + session creation when access is granted;
2. loads `https://sdk.scdn.co/spotify-player.js` and reports whether
   `onSpotifyWebPlaybackSDKReady` fires;
3. **with a token** — constructs a real `Spotify.Player` and calls
   `connect()`, reporting `ready` (with the Connect `device_id`),
   `initialization_error`, `authentication_error`, `account_error`, and
   `playback_error` over a 25 s event window.

Every event is printed to stdout as `[probe] {...}` and the full run is
written to `eme-probe-results.json` in the working directory.

## Prerequisites

- macOS with **Xcode Command Line Tools**: `xcode-select --install`
  (SwiftPM + AppKit/WebKit are all you need — no brew, no pods, no npm).
- Network access (the SDK script and its license endpoints are remote).
- For the full answer: a Spotify **Premium** account and an OAuth access
  token with the `streaming` scope (see *Minting a token*).

## Build and run

```sh
cd spike/eme-probe

# Tokenless run — answers "what does WKWebView's EME support look like,
# and does the SDK script load and initialize?"
make run

# Full run — additionally answers "does Spotify.Player reach ready?"
./EMEProbe.app/Contents/MacOS/EMEProbe --token <ACCESS_TOKEN>

# Useful flags
#   --chrome-ua        spoof a desktop Chrome UA (tests UA gating)
#   --out <path>       results JSON path (default: eme-probe-results.json)
#   --timeout <secs>   harness watchdog (default: 45)
#   --event-window <s> player event window after connect (default: 25)
```

`make run` builds the SwiftPM executable, assembles `EMEProbe.app`, ad-hoc
signs it, and runs it. A small window appears while the probe runs; it quits
itself when done.

> **Signing note:** the default ad-hoc signature works for local runs. If
> *every* key system rejects (including `org.w3.clearkey`, which should
> always be granted), re-sign with a real identity:
> `codesign --force --sign "Apple Development" EMEProbe.app` and run again.

## Minting a token (streaming scope)

The token needs the `streaming` scope; Spotify Light's saved tokens predate
it. Quickest path with this repo:

1. In `examples/spotify_light/sl_oauth.py`, add `"streaming"` to `_SCOPES`.
2. Delete the config dir to force re-consent: `rm -rf ~/.config/spotify-light`
3. Run the app on the Mac (`uv run python main.py run-app examples/spotify_light --render macos-metal`),
   paste the Client ID, click **Connect Spotify**, sign in.
4. Read the token: `jq -r .access_token ~/.config/spotify-light/tokens.json`
   (`jq` optional — it's the `access_token` field in that JSON file).

Tokens expire after ~1 hour; mint a fresh one per probe session.
Alternatively export `SPOTIFY_ACCESS_TOKEN` instead of passing `--token`.

## Reading the results

| Observation in `eme-probe-results.json` | Meaning |
| --- | --- |
| `com.apple.fps*` granted + `player_ready` | **WKWebView works.** Adopt the WKWebView surface (option a in the spike doc). |
| `com.apple.fps*` granted + `initialization_error` | WebKit EME is fine but the SDK rejects this environment. Try `--chrome-ua`; if that flips it to `player_ready`, the gate is UA-based and fragile — prefer the companion-browser route for anything beyond personal use. |
| `com.apple.fps*` granted + `authentication_error` | Token missing/expired or lacking the `streaming` scope — mint a fresh one and rerun. Not an EME verdict. |
| `com.apple.fps*` granted + `account_error` | Account is not Premium (or dev-mode allowlist/owner-Premium rule hit). Not an EME verdict. |
| Only `org.w3.clearkey` granted | WKWebView has no usable DRM here (unexpected on modern macOS — check the signing note). Fall back to option (b)/(c) in the spike doc. |
| `sdk_script` fatal | No network / scdn.co blocked. Fix connectivity and rerun. |

The decision tree this feeds is in the spike doc `docs/web-playback-spike.md`
(project agent store, under **Recommendation** — ask Alec for the current
copy if you don't have store access).
