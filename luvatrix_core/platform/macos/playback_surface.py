"""WKWebView playback surface: the Web Playback SDK hosted in-app.

A hidden scripted web view loads the host page below, which pulls
``spotify-player.js`` and adapts its ``Spotify.Player`` to the
``luvatrix_core.core.playback_bridge`` contract: SDK listeners post
``{type, payload}`` into the ``luvatrixPlayer`` message handler, and the
app drives the player with ``LuvatrixPlayerHost.invoke(verb, args)``.

The view is a 1×1 attached, alpha-zero subview — deliberately NOT
``setHidden_(True)``: WebKit throttles JS timers in hidden views, which
would stall playback events, and an occluded-but-"visible" 1×1 keeps the
page live without pixels. The spike probe verified this exact shape hosts
the SDK through ``ready`` on macOS.

Only the page string and the queue/token/lifecycle logic are testable off
a Mac (over the null bridge's recording stub); the live WebKit channel is
covered by the scripted Mac probe in the follow-up slice.
"""
from __future__ import annotations

import json
import queue
from typing import Any, Callable

from luvatrix_core.core.playback_bridge import (
    MESSAGE_HANDLER_NAME,
    PlaybackEvent,
    PlaybackEventKind,
    encode_command,
    parse_event,
)

DEFAULT_DEVICE_NAME = "Luvatrix Player"
_SECURE_BASE_URL = "https://localhost/"  # EME requires a secure origin

# The host page. Contract halves: posts into messageHandlers.<handler name>,
# receives LuvatrixPlayerHost.invoke(verb, args). Keep every verb of
# playback_bridge.VERBS dispatchable and every PlaybackEventKind postable —
# tests pin both directions.
PLAYER_HOST_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>luvatrix player host</title>
<script>
window.LuvatrixPlayerHost = {
  _token: null,
  _player: null,

  setToken: function(t) { this._token = t; },

  _post: function(type, payload) {
    try {
      window.webkit.messageHandlers.luvatrixPlayer.postMessage(
        {type: type, payload: payload || {}});
    } catch (e) {}
  },

  _slimState: function(s) {
    if (!s) { return {empty: true}; }
    var t = s.track_window && s.track_window.current_track;
    return {
      paused: !!s.paused,
      position_ms: s.position,
      duration_ms: s.duration,
      shuffle: !!s.shuffle,
      repeat_mode: s.repeat_mode,
      track: t ? {
        uri: t.uri,
        name: t.name,
        artists: (t.artists || []).map(function(a) { return a.name; }).join(", "),
        album: t.album && t.album.name,
        art_url: t.album && t.album.images && t.album.images[0] && t.album.images[0].url
      } : null
    };
  },

  _ensurePlayer: function() {
    if (this._player) { return this._player; }
    var self = this;
    var player = new Spotify.Player({
      name: __DEVICE_NAME__,
      getOAuthToken: function(cb) { cb(self._token || ""); },
      volume: 0.5
    });
    player.addListener("ready", function(d) {
      self._post("ready", {device_id: d && d.device_id});
    });
    player.addListener("not_ready", function(d) {
      self._post("not_ready", {device_id: d && d.device_id});
    });
    ["initialization_error", "authentication_error", "account_error",
     "playback_error"].forEach(function(t) {
      player.addListener(t, function(e) {
        self._post(t, {message: e && e.message});
      });
    });
    player.addListener("player_state_changed", function(s) {
      self._post("player_state_changed", self._slimState(s));
    });
    this._player = player;
    return player;
  },

  invoke: function(verb, args) {
    args = args || {};
    var self = this;
    try {
      switch (verb) {
        case "connect":
          this._ensurePlayer().connect();
          break;
        case "disconnect":
          if (this._player) { this._player.disconnect(); }
          break;
        case "activateElement":
          this._ensurePlayer().activateElement();
          break;
        case "seek":
          this._ensurePlayer().seek(args.position_ms);
          break;
        case "setVolume":
          this._ensurePlayer().setVolume(args.volume);
          break;
        case "getCurrentState":
          this._ensurePlayer().getCurrentState().then(function(s) {
            self._post("state_snapshot", self._slimState(s));
          });
          break;
        case "pause":
        case "resume":
        case "togglePlay":
        case "nextTrack":
        case "previousTrack":
          this._ensurePlayer()[verb]();
          break;
        default:
          this._post("initialization_error", {message: "unknown verb: " + verb});
      }
    } catch (e) {
      this._post("initialization_error",
                 {message: verb + ": " + (e && e.message)});
    }
  }
};

window.onSpotifyWebPlaybackSDKReady = function() {
  // Player construction is deferred to the first invoke (connect) so the
  // native side controls when the device registers.
};

(function() {
  var s = document.createElement("script");
  s.src = "https://sdk.scdn.co/spotify-player.js";
  s.onerror = function() {
    window.LuvatrixPlayerHost._post(
      "initialization_error", {message: "spotify-player.js failed to load"});
  };
  document.head.appendChild(s);
})();
</script></head><body></body></html>
"""


def player_host_html(device_name: str) -> str:
    """The host page with the Connect device name baked in (JSON-escaped)."""
    return PLAYER_HOST_HTML.replace("__DEVICE_NAME__", json.dumps(device_name))


class WKWebPlaybackSurface:
    """PlaybackBridge over a hidden WKWebView running the SDK host page.

    Construct with the window's native-control bridge; ``start`` attaches
    the view and loads the page. Commands encode through the contract and
    evaluate in the page; page posts land in a queue the app loop drains.
    """

    def __init__(self, bridge, *, device_name: str = DEFAULT_DEVICE_NAME,
                 token: str | None = None,
                 view_factory: Callable[..., Any] | None = None) -> None:
        self._bridge = bridge
        self._device_name = device_name
        self._token = token
        self._view_factory = view_factory
        self._events: queue.Queue[PlaybackEvent] = queue.Queue()
        self._view = None
        self._started = False
        self._stopped = False
        self.device_id: str | None = None

    @property
    def available(self) -> bool:
        return not self._stopped

    def start(self) -> None:
        if self._stopped:
            raise RuntimeError("playback surface is stopped")
        if self._started:
            return
        factory = self._view_factory or self._bridge.create_scripted_web_view
        self._view = factory(
            x=0.0, y=0.0, width=1.0, height=1.0,
            handler_name=MESSAGE_HANDLER_NAME,
            on_message=self._on_message,
            html=player_host_html(self._device_name),
            base_url=_SECURE_BASE_URL,
        )
        # Invisible but attached: hidden views get their JS throttled.
        ns_view = getattr(self._view, "ns_web_view", None)
        if ns_view is not None:
            try:
                ns_view.setAlphaValue_(0.0)
            except Exception:  # noqa: BLE001
                pass
        self._started = True
        if self._token:
            self._push_token()

    def set_token(self, token: str) -> None:
        """Push a fresh OAuth token into the page (initial + refresh)."""
        self._token = token
        if self._view is not None:
            self._push_token()

    def _push_token(self) -> None:
        self._view.evaluate_js(
            f"window.LuvatrixPlayerHost.setToken({json.dumps(self._token)})")

    def send(self, verb: str, **args: Any) -> None:
        if self._stopped:
            raise RuntimeError("playback surface is stopped")
        if not self._started:
            raise RuntimeError("playback surface not started")
        self._view.evaluate_js(encode_command(verb, args))

    def drain_events(self) -> list[PlaybackEvent]:
        out: list[PlaybackEvent] = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                return out

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self.device_id = None
        if self._view is not None:
            try:
                self._view.destroy()
            except Exception:  # noqa: BLE001 — teardown must not raise
                pass
            self._view = None

    def _on_message(self, message: object) -> None:
        event = parse_event(message)
        if event is None:
            return
        if event.kind is PlaybackEventKind.READY:
            device_id = event.payload.get("device_id")
            self.device_id = str(device_id) if device_id else None
        elif event.kind is PlaybackEventKind.NOT_READY:
            self.device_id = None
        self._events.put(event)
