"""Spotify Light — a lightweight Spotify desktop client built on luvatrix.

Renders natively through the luvatrix scene graph (macOS Metal target) and
talks to the real Spotify Web API: OAuth Authorization Code + PKCE for
sign-in, browse/search/library for content, and Spotify Connect for playback
control with now-playing polling. All network runs on one worker thread; the
render loop only draws cached state and stays render-on-invalidation.
"""
from __future__ import annotations

import sys
import threading
import time
import webbrowser
from pathlib import Path

# The runtime loads this module via spec_from_file_location without putting the
# app folder on sys.path; sibling modules import flat, so register the folder.
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from luvatrix.app import (
    App,
    ScrollbarController,
    apply_hdi_events,
    reset_transient_input,
)

import sl_api
import sl_art
import sl_models
import sl_oauth
import sl_store
import sl_ui
import sl_views
import sl_worker

POLL_PLAYING_SECS = 3.0
POLL_IDLE_SECS = 5.0
POLL_AFTER_ACTION_SECS = 0.7
SEARCH_DEBOUNCE_SECS = 0.4
STATUS_TOAST_SECS = 6.0
LOGIN_TIMEOUT_SECS = 180.0

CONTROL_KEYCODES = {
    36: "enter",
    76: "enter",
    51: "backspace",
    53: "escape",
    48: "tab",
}


class TokenManager:
    """Thread-safe token access with automatic refresh (worker thread only)."""

    def __init__(self, cfg_dir: Path, client_id: str, tokens: sl_oauth.TokenSet) -> None:
        self._lock = threading.Lock()
        self._cfg_dir = cfg_dir
        self._client_id = client_id
        self._tokens = tokens

    def access_token(self) -> str:
        with self._lock:
            if self._tokens.needs_refresh(time.time()):
                refreshed = sl_oauth.refresh_tokens(
                    self._client_id, self._tokens.refresh_token or ""
                ).with_fallback_refresh(self._tokens)
                self._tokens = refreshed
                sl_store.save_tokens(self._cfg_dir, refreshed)
            return self._tokens.access_token

    def replace(self, tokens: sl_oauth.TokenSet) -> None:
        with self._lock:
            self._tokens = tokens
            sl_store.save_tokens(self._cfg_dir, tokens)


class SpotifyLightApp(App):
    def setup(self) -> None:
        self.cfg_dir = sl_store.config_dir()
        self.art_cache = sl_art.ArtCache(self.cfg_dir / "art")
        self.worker = sl_worker.Worker()
        self.scrollbar_sidebar = ScrollbarController("vertical")
        self.scrollbar_content = ScrollbarController("vertical")

        self.client_id = sl_store.load_client_id(self.cfg_dir)
        self._tokens = sl_store.load_tokens(self.cfg_dir)
        self._token_manager: TokenManager | None = None
        self._client: sl_api.SpotifyClient | None = None

        # View + navigation state.
        self.view = "home"
        self.authenticated = False
        self.auth_working = False
        self.auth_error = ""
        self.status_message = ""
        self._status_until = 0.0

        # Data state (only ever mutated on the app thread, from worker results).
        self.profile: sl_models.Profile | None = None
        self.playlists: list[sl_models.Playlist] = []
        self.home_sections: list[sl_ui.SectionView] = []
        self.bootstrap_error = ""
        self.playlist_detail: tuple[sl_models.Playlist, list[sl_models.Track]] | None = None
        self.search_results: sl_models.SearchResults | None = None
        self.search_error = ""
        self.player: sl_models.PlayerState | None = None
        self.devices: list[sl_models.Device] = []
        self._player_synced_at = 0.0
        self.last_volume = 50

        # Input state.
        self.search_query = ""
        self.search_focused = False
        self._search_dirty_at: float | None = None
        self.client_id_draft = ""
        self.client_id_focused = False
        self.show_devices = False
        self._hits: list[sl_views.HitRegion] = []
        self._mouse = (0.0, 0.0)
        self._drag: tuple[str, object] | None = None
        self.content_scroll = 0.0
        self.sidebar_scroll = 0.0
        self._content_height = 0.0

        # Bookkeeping.
        self.now_monotonic = time.monotonic()
        self._next_player_poll = 0.0
        self._next_progress_tick = 0.0
        self._art_in_flight: set[str] = set()
        self._art_pending: dict[str, tuple[str, int]] = {}
        self._login_receiver: sl_oauth.LoopbackReceiver | None = None

        self.set_continuous_render(False)

        if self.client_id and self._tokens is not None:
            self._begin_session(self._tokens)

    # -- session wiring ------------------------------------------------------

    def _begin_session(self, tokens: sl_oauth.TokenSet) -> None:
        self._token_manager = TokenManager(self.cfg_dir, self.client_id, tokens)
        self._client = sl_api.SpotifyClient(token_provider=self._token_manager.access_token)
        self.authenticated = True
        self.worker.submit("bootstrap", self._job_bootstrap)
        self._next_player_poll = 0.0  # poll immediately

    def _end_session(self) -> None:
        sl_store.clear_tokens(self.cfg_dir)
        self._tokens = None
        self._token_manager = None
        self._client = None
        self.authenticated = False
        self.profile = None
        self.playlists = []
        self.home_sections = []
        self.playlist_detail = None
        self.search_results = None
        self.player = None
        self.devices = []
        self.view = "home"
        self.invalidate()

    # -- worker jobs (background thread) --------------------------------------

    def _job_bootstrap(self):
        assert self._client is not None
        profile = self._client.me()
        playlists = self._client.my_playlists()
        top_tracks = self._client.top_tracks(limit=10)
        new_releases = self._client.new_releases(limit=12)
        top_artists: list = []
        try:
            top_artists = self._client.top_artists(limit=12)
        except sl_api.ApiError:
            pass  # top/artists can 403 for some accounts; home still works
        return (profile, playlists, top_tracks, new_releases, top_artists)

    def _job_login(self):
        receiver = sl_oauth.LoopbackReceiver(sl_oauth.DEFAULT_PORT)
        receiver.start()
        self._login_receiver = receiver
        try:
            redirect_uri = sl_oauth.redirect_uri_for_port(receiver.port)
            verifier = sl_oauth.generate_verifier()
            state = sl_oauth.generate_state()
            url = sl_oauth.authorize_url(
                client_id=self.client_id,
                redirect_uri=redirect_uri,
                challenge=sl_oauth.challenge_s256(verifier),
                state=state,
            )
            webbrowser.open(url)
            code = receiver.wait_for_code(expected_state=state, timeout=LOGIN_TIMEOUT_SECS)
            tokens = sl_oauth.exchange_code(
                client_id=self.client_id,
                redirect_uri=redirect_uri,
                code=code,
                verifier=verifier,
            )
            return tokens
        finally:
            receiver.close()
            self._login_receiver = None

    def _job_poll_player(self):
        assert self._client is not None
        player = self._client.player_state()
        devices = self._client.devices()
        return (player, devices)

    def _job_search(self, query: str):
        assert self._client is not None
        return self._client.search(query, limit=10)

    def _job_playlist(self, playlist_id: str):
        assert self._client is not None
        playlist = next((p for p in self.playlists if p.id == playlist_id), None)
        tracks = self._client.playlist_tracks(playlist_id)
        return (playlist, tracks)

    def _job_player_action(self, fn):
        assert self._client is not None
        fn(self._client)
        return True

    def _job_art(self, url: str, size: int):
        return (url, size, self.art_cache.fetch(url, size))

    # -- worker results (app thread) -------------------------------------------

    def _handle_worker_results(self) -> None:
        for label, outcome in self.worker.poll():
            self._apply_result(label, outcome)

    def _apply_result(self, label: str, outcome) -> None:
        if isinstance(outcome, sl_api.ApiError):
            self._apply_api_error(label, outcome)
            return
        if isinstance(outcome, sl_oauth.OAuthError):
            if label == "login":
                if self.auth_working:  # not a user cancel
                    self.auth_error = str(outcome)
                self.auth_working = False
            else:
                self._toast(str(outcome))
            self.invalidate()
            return
        if isinstance(outcome, Exception):
            if label == "login":
                if self.auth_working:
                    self.auth_error = f"Sign-in failed: {outcome}"
                self.auth_working = False
            elif label.startswith("art:"):
                self._art_in_flight.discard(label[4:])
            elif label == "bootstrap":
                self.bootstrap_error = f"Could not load your library: {outcome}"
            else:
                self._toast(str(outcome))
            self.invalidate()
            return

        if label == "bootstrap":
            profile, playlists, top_tracks, new_releases, top_artists = outcome
            self.profile = profile
            self.playlists = playlists
            self.home_sections = sl_ui.build_home_sections(
                top_tracks=top_tracks,
                new_releases=new_releases,
                playlists=playlists[:12],
                top_artists=top_artists,
            )
            self.bootstrap_error = ""
        elif label == "login":
            self.auth_working = False
            self.auth_error = ""
            self._tokens = outcome
            sl_store.save_tokens(self.cfg_dir, outcome)
            self._begin_session(outcome)
        elif label == "poll-player":
            player, devices = outcome
            self.player = player
            self.devices = devices
            self._player_synced_at = time.monotonic()
            if player and player.device and player.device.volume_percent is not None:
                self.last_volume = player.device.volume_percent
        elif label == "search":
            self.search_results = outcome
            self.search_error = ""
        elif label.startswith("playlist:"):
            playlist, tracks = outcome
            if playlist is not None:
                self.playlist_detail = (playlist, tracks)
        elif label.startswith("art:"):
            self._art_in_flight.discard(label[4:])
        self.invalidate()

    def _apply_api_error(self, label: str, error: sl_api.ApiError) -> None:
        if error.kind == sl_api.ErrorKind.UNAUTHORIZED:
            self._toast("Session expired — please reconnect Spotify")
            self._end_session()
            return
        if error.kind == sl_api.ErrorKind.PREMIUM_REQUIRED:
            self._toast("Spotify Premium is required for playback control")
        elif error.kind == sl_api.ErrorKind.DEVICE_NOT_FOUND:
            self._toast("No active device — pick one under Devices")
        elif label == "search":
            self.search_error = str(error)
        else:
            self._toast(str(error))
        self.invalidate()

    def _toast(self, message: str) -> None:
        self.status_message = message
        self._status_until = time.monotonic() + STATUS_TOAST_SECS

    # -- timers -----------------------------------------------------------------

    def _handle_timers(self) -> None:
        now = time.monotonic()
        self.now_monotonic = now

        if self.authenticated and self._client is not None and now >= self._next_player_poll:
            self._next_player_poll = now + (
                POLL_PLAYING_SECS if (self.player and self.player.is_playing) else POLL_IDLE_SECS
            )
            self.worker.submit("poll-player", self._job_poll_player)

        # While playing, tick the progress bar once per second between polls.
        if self.player and self.player.is_playing and now >= self._next_progress_tick:
            self._next_progress_tick = now + 1.0
            self.invalidate()

        if self._search_dirty_at is not None and now - self._search_dirty_at >= SEARCH_DEBOUNCE_SECS:
            self._search_dirty_at = None
            self._submit_search()

        if self.status_message and now >= self._status_until:
            self.status_message = ""
            self.invalidate()

        # Caret blink + hover redraws need a slow heartbeat even when idle.
        if self.search_focused or self.client_id_focused:
            self.invalidate()

    # -- input --------------------------------------------------------------------

    def _handle_input(self, events) -> None:
        state = self.input.state
        self._mouse = (state.mouse_x, state.mouse_y)

        for event in events:
            if getattr(event, "device", None) == "keyboard":
                self._handle_key(event)

        # Scrollbar drags get first claim on the mouse.
        list_top = 64 + 44 * 3 + 34
        sidebar_update = self.scrollbar_sidebar.update(
            state,
            x=sl_views.SIDEBAR_W - 10,
            y=list_top,
            width=13,
            height=max(0.0, self.display.height_px - sl_views.PLAYER_H - 64 - list_top),
            content_extent=30.0 * len(self.playlists),
            viewport_extent=max(1.0, self.display.height_px - sl_views.PLAYER_H - 64 - list_top),
            offset=self.sidebar_scroll,
        )
        if sidebar_update.consumed:
            self.sidebar_scroll = sidebar_update.offset
            self.invalidate()
            return
        viewport = self.display.height_px - sl_views.PLAYER_H
        content_update = self.scrollbar_content.update(
            state,
            x=self.display.width_px - 11,
            y=0,
            width=13,
            height=viewport,
            content_extent=self._content_height,
            viewport_extent=viewport,
            offset=self.content_scroll,
        )
        if content_update.consumed:
            self.content_scroll = content_update.offset
            self.invalidate()
            return

        if state.scroll_y:
            self._apply_scroll(state.scroll_y)
        if state.scroll_x:
            pass  # horizontal sections are not scrollable in v1

        if state.left_clicked:
            self._dispatch_click(state.mouse_x, state.mouse_y)
        if self._drag is not None:
            self._update_drag(state)
        if not state.left_down:
            self._drag = None

    def _apply_scroll(self, delta_y: float) -> None:
        mx, my = self._mouse
        if mx < sl_views.SIDEBAR_W:
            self.sidebar_scroll = self._clamp_scroll(
                self.sidebar_scroll - delta_y, 30.0 * len(self.playlists),
                self.display.height_px - sl_views.PLAYER_H - 64 - (64 + 44 * 3 + 34),
            )
        else:
            viewport = self.display.height_px - sl_views.PLAYER_H
            self.content_scroll = self._clamp_scroll(
                self.content_scroll - delta_y, self._content_height, viewport
            )
        self.invalidate()

    @staticmethod
    def _clamp_scroll(value: float, content: float, viewport: float) -> float:
        max_offset = max(0.0, content - viewport)
        return max(0.0, min(value, max_offset))

    def _dispatch_click(self, x: float, y: float) -> None:
        for region in reversed(self._hits):
            if region.contains(x, y):
                self._dispatch_action(region.action, region.payload, x)
                return
        # Clicked empty space: drop focus / close popups.
        self.search_focused = False
        self.client_id_focused = False
        self.show_devices = False
        self.invalidate()

    def _update_drag(self, state) -> None:
        action, payload = self._drag
        if action == "seek_bar":
            seek_x, seek_w, duration = payload
            if duration > 0:
                frac = max(0.0, min(1.0, (state.mouse_x - seek_x) / seek_w))
                if self.player is not None:
                    self.player = self._player_with_progress(int(duration * frac))
                    self._player_synced_at = time.monotonic()
                self.invalidate()
        elif action == "volume_bar":
            vol_x, vol_w = payload
            pct = int(max(0.0, min(1.0, (state.mouse_x - vol_x) / vol_w)) * 100)
            self.last_volume = pct
            self.invalidate()

    def _player_with_progress(self, progress_ms: int) -> sl_models.PlayerState:
        assert self.player is not None
        return sl_models.PlayerState(
            is_playing=self.player.is_playing,
            progress_ms=progress_ms,
            track=self.player.track,
            device=self.player.device,
            shuffle=self.player.shuffle,
            repeat=self.player.repeat,
            timestamp_ms=self.player.timestamp_ms,
        )

    def _dispatch_action(self, action: str, payload, click_x: float) -> None:
        if action == "nav":
            self.view = payload
            self.content_scroll = 0.0
            self.show_devices = False
            self.invalidate()
        elif action == "open_playlist":
            self.view = f"playlist:{payload}"
            self.content_scroll = 0.0
            self.playlist_detail = None
            self.worker.submit(f"playlist:{payload}", lambda: self._job_playlist(payload))
            self.invalidate()
        elif action == "open_card":
            card = payload
            if card.kind == "playlist":
                self._dispatch_action("open_playlist", card.id, click_x)
            elif card.context_uri:
                self._player_action(lambda c: c.play(context_uri=card.context_uri))
        elif action == "play_card":
            card = payload
            if card.context_uri:
                self._player_action(lambda c: c.play(uris=[card.context_uri]))
        elif action == "play_context":
            self._player_action(lambda c: c.play(context_uri=payload))
        elif action == "play_track_in_context":
            context_uri, track_uri = payload
            self._player_action(lambda c: c.play(context_uri=context_uri, offset_uri=track_uri))
        elif action == "play_uris":
            self._player_action(lambda c: c.play(uris=list(payload)))
        elif action == "toggle_play":
            if self.player and self.player.is_playing:
                self._player_action(lambda c: c.pause())
            else:
                self._player_action(lambda c: c.play())
        elif action == "next":
            self._player_action(lambda c: c.next_track())
        elif action == "prev":
            self._player_action(lambda c: c.previous_track())
        elif action == "toggle_shuffle":
            enabled = not (self.player and self.player.shuffle)
            self._player_action(lambda c: c.set_shuffle(enabled))
        elif action == "cycle_repeat":
            order = ["off", "context", "track"]
            current = self.player.repeat if self.player else "off"
            nxt = order[(order.index(current) + 1) % len(order)] if current in order else "off"
            self._player_action(lambda c: c.set_repeat(nxt))
        elif action == "seek_bar":
            self._drag = ("seek_bar", payload)
            seek_x, seek_w, duration = payload
            if duration > 0:
                frac = max(0.0, min(1.0, (click_x - seek_x) / seek_w))
                self._player_action(lambda c: c.seek(int(duration * frac)))
        elif action == "volume_bar":
            self._drag = ("volume_bar", payload)
            vol_x, vol_w = payload
            pct = int(max(0.0, min(1.0, (click_x - vol_x) / vol_w)) * 100)
            self._player_action(lambda c: c.set_volume(pct))
        elif action == "open_devices":
            self.show_devices = not self.show_devices
            if self.show_devices and self.authenticated:
                self.worker.submit("poll-player", self._job_poll_player)
            self.invalidate()
        elif action == "pick_device":
            self._player_action(lambda c: c.transfer(payload, play=True))
            self.show_devices = False
        elif action == "focus_search":
            self.search_focused = True
            self.client_id_focused = False
            self.invalidate()
        elif action == "focus_client_id":
            self.client_id_focused = True
            self.search_focused = False
            self.invalidate()
        elif action == "save_client_id":
            self.client_id = self.client_id_draft.strip()
            sl_store.save_client_id(self.cfg_dir, self.client_id)
            self.client_id_focused = False
            self.invalidate()
        elif action == "start_login":
            self.auth_working = True
            self.auth_error = ""
            self.worker.submit("login", self._job_login)
            self.invalidate()
        elif action == "cancel_login":
            if self._login_receiver is not None:
                self._login_receiver.close()
            self.auth_working = False
            self.invalidate()
        elif action == "logout":
            self._end_session()
        elif action == "scrollbar":
            pass  # handled by ScrollbarController.update above

    def _player_action(self, fn) -> None:
        if self._client is None:
            self._toast("Connect Spotify first")
            return
        self.worker.submit("player-action", lambda: self._job_player_action(fn))
        self._next_player_poll = time.monotonic() + POLL_AFTER_ACTION_SECS
        self.invalidate()

    def _handle_key(self, event) -> None:
        payload = getattr(event, "payload", None) or {}
        phase = str(payload.get("phase", ""))
        if phase not in ("down", "repeat"):
            return
        key = str(payload.get("key", ""))
        code = payload.get("code")
        control = CONTROL_KEYCODES.get(code) if isinstance(code, int) else None

        if self.client_id_focused:
            self.client_id_draft = self._edit_text(self.client_id_draft, key, control)
            self.invalidate()
            return
        if self.search_focused:
            if control == "enter":
                self._search_dirty_at = None
                self._submit_search()
            elif control == "escape":
                self.search_focused = False
            else:
                self.search_query = self._edit_text(self.search_query, key, control)
                self._search_dirty_at = time.monotonic()
            self.invalidate()
            return
        if key == " ":
            self._dispatch_action("toggle_play", None, 0.0)

    @staticmethod
    def _edit_text(value: str, key: str, control: str | None) -> str:
        if control == "backspace":
            return value[:-1]
        if control in ("enter", "escape", "tab"):
            return value
        if len(key) == 1 and key.isprintable():
            return value + key
        return value

    def _submit_search(self) -> None:
        query = self.search_query.strip()
        if not query or self._client is None:
            return
        self.search_results = None
        self.search_error = ""
        self.worker.submit("search", lambda: self._job_search(query))
        self.invalidate()

    # -- art -----------------------------------------------------------------------

    def art_for(self, url: str | None, size: int):
        """Cached RGBA pixels, or None (and a scheduled fetch) on a miss."""
        if not url:
            return None
        key = f"{url}|{size}"
        try:
            return self.art_cache.fetch(url, size, http_get=self._fail_offline)
        except sl_art.ArtError:
            pass
        if key not in self._art_in_flight:
            self._art_in_flight.add(key)
            self.worker.submit(f"art:{key}", lambda: self._job_art(url, size))
        return None

    @staticmethod
    def _fail_offline(url: str):
        # Render thread must never hit the network; miss means "fetch on worker".
        raise sl_art.ArtError("not cached")

    # -- progress ---------------------------------------------------------------------

    def progress_ms(self) -> int:
        if self.player is None:
            return 0
        duration = self.player.track.duration_ms if self.player.track else 0
        return sl_ui.interpolate_progress(
            base_ms=self.player.progress_ms,
            base_monotonic=self._player_synced_at,
            duration_ms=duration,
            playing=self.player.is_playing,
        )

    # -- app loop ---------------------------------------------------------------------

    def update(self, dt: float) -> None:
        events = self.input.raw_events()
        reset_transient_input(self.input.state)
        apply_hdi_events(self.input.state, events)
        if events:
            self.invalidate()
        self._handle_input(events)
        self._handle_worker_results()
        self._handle_timers()

    def render(self) -> None:
        if self.ctx.supports_scene_graph:
            with self.scene_frame(clear=sl_views.BG) as frame:
                self._render_scene(frame)
        else:
            with self.matrix_frame(clear=sl_views.BG) as frame:
                self._render_matrix(frame)

    def _render_scene(self, frame) -> None:
        width = float(self.ctx.display_width_px)
        height = float(self.ctx.display_height_px)
        out = sl_views.FrameOut()
        mouse = self._mouse

        if not self.authenticated:
            sl_views.draw_login(frame, self, out, width=width, height=height, mouse=mouse)
        else:
            if self.view == "search":
                sl_views.draw_search(frame, self, out, width=width, height=height, mouse=mouse)
            elif self.view.startswith("playlist:"):
                sl_views.draw_playlist(frame, self, out, width=width, height=height, mouse=mouse)
            elif self.view == "library":
                sl_views.draw_library(frame, self, out, width=width, height=height, mouse=mouse)
            else:
                sl_views.draw_home(frame, self, out, width=width, height=height, mouse=mouse)

            # Content-area scrollbar for tall views.
            viewport = height - sl_views.PLAYER_H
            if self._content_height > viewport:
                metrics = self.scrollbar_content.metrics(
                    track_extent=viewport, content_extent=self._content_height,
                    viewport_extent=viewport, offset=self.content_scroll,
                )
                if metrics.thumb_extent > 0:
                    frame.rounded_rect(
                        x=width - 7, y=metrics.thumb_start, width=5,
                        height=metrics.thumb_extent, radius=2.5, color=(90, 90, 90, 255), z_index=5,
                    )

            sl_views.draw_sidebar(frame, self, out, width=width, height=height, mouse=mouse)
            sl_views.draw_player_bar(frame, self, out, width=width, height=height, mouse=mouse)

            if self.bootstrap_error:
                self._draw_toast(frame, self.bootstrap_error, width, height)
            elif self.status_message:
                self._draw_toast(frame, self.status_message, width, height)

        self._content_height = out.content_height
        self._hits = out.hits

    def _draw_toast(self, frame, message: str, width: float, height: float) -> None:
        toast_w = min(520.0, width - 40)
        toast_x = (width - toast_w) / 2
        toast_y = height - sl_views.PLAYER_H - 56
        frame.rounded_rect(x=toast_x, y=toast_y, width=toast_w, height=40, radius=8,
                           color=(50, 50, 50, 255), z_index=30)
        frame.text(
            sl_ui.truncate(message, 70),
            x=toast_x + 16,
            y=toast_y + 12,
            font_size_px=13,
            color=sl_views.TEXT,
            z_index=31,
            cache_key=f"toast|{message}",
        )

    def _render_matrix(self, frame) -> None:
        """Headless fallback: status dashboard (the full UI needs a scene target)."""
        lines = [
            "Spotify Light",
            "",
            f"auth: {'connected' if self.authenticated else 'not connected'}",
            f"view: {self.view}",
        ]
        if self.player and self.player.track:
            state = "playing" if self.player.is_playing else "paused"
            lines.append(f"now {state}: {self.player.track.name}")
            lines.append(
                f"{sl_ui.format_duration_ms(self.progress_ms())} / "
                f"{sl_ui.format_duration_ms(self.player.track.duration_ms)}"
            )
        else:
            lines.append("now playing: nothing")
        if self.status_message:
            lines.append(f"status: {self.status_message}")
        lines.append("")
        lines.append("full UI renders on the macOS Metal scene target")
        y = 12
        for line in lines:
            frame.text(line, x=12, y=y, font_size_px=10, color=sl_views.TEXT)
            y += 14

    def teardown(self) -> None:
        if self._login_receiver is not None:
            self._login_receiver.close()
        self.worker.shutdown()


def create() -> SpotifyLightApp:
    return SpotifyLightApp()
