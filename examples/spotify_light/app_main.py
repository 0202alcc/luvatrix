"""Spotify Light — a lightweight Spotify desktop client built on luvatrix.

Renders natively through the luvatrix scene graph (macOS Metal target) and
talks to the real Spotify Web API: OAuth Authorization Code + PKCE for
sign-in, browse/search/library for content, and Spotify Connect for playback
control with now-playing polling. All network runs on one worker thread; the
render loop only draws cached state and stays render-on-invalidation.
"""
from __future__ import annotations

import logging
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
    native_controls,
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

log = logging.getLogger("spotify_light")

POLL_PLAYING_SECS = 3.0
POLL_IDLE_SECS = 5.0
POLL_AFTER_ACTION_SECS = 0.7
SEARCH_DEBOUNCE_SECS = 0.4
STATUS_TOAST_SECS = 6.0
LOGIN_TIMEOUT_SECS = 180.0
# How long a failed art fetch backs off before one retry: a dead CDN URL must
# not be re-fetched on every redraw while its card is on screen.
ART_FAIL_TTL_SECS = 300.0

CONTROL_KEYCODES = {
    36: "enter",
    76: "enter",
    51: "backspace",
    53: "escape",
    48: "tab",
}

# Synthetic keyboards (the MCP tunnel, accessibility drivers) name control
# keys instead of sending platform keycodes — and the HDI keyboard
# normalizer rebuilds key_down payloads without `code`, so keycodes never
# survive remote input. Names are the portable contract.
CONTROL_KEY_NAMES = frozenset(CONTROL_KEYCODES.values())


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
        self._bootstrap_done = False
        self.bootstrap_notices: list[str] = []
        self.playlist_detail: tuple[sl_models.Playlist, list[sl_models.Track]] | None = None
        self.playlist_error = ""
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
        self._native_client_id_field = None  # real NSTextField when the bridge is up
        self._native_buttons: dict[str, object] = {}  # keyed native glass buttons (auth wall)
        self._glass_surfaces: dict[str, object] = {}  # keyed glass regions (liquid glass)
        self.glass_active = False  # True while chrome glass plates are up
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
        self._art_failures: dict[str, float] = {}
        self._art_pending: dict[str, tuple[str, int]] = {}
        self._login_receiver: sl_oauth.LoopbackReceiver | None = None
        # Embedded login (native web view): set only while the in-app flow is up.
        self._login_web_view = None
        self._login_cancel_button = None
        self._login_cancel_capsule = None
        self._login_back_button = None
        self._login_back_capsule = None
        self._embedded_callback: str | None = None
        self._login_verifier: str | None = None
        self._login_state: str | None = None
        self._login_redirect_uri: str | None = None

        self.set_continuous_render(False)

        if self.client_id and self._tokens is not None:
            self._begin_session(self._tokens)

    # -- session wiring ------------------------------------------------------

    def _begin_session(self, tokens: sl_oauth.TokenSet) -> None:
        self._token_manager = TokenManager(self.cfg_dir, self.client_id, tokens)
        self._client = sl_api.SpotifyClient(token_provider=self._token_manager.access_token)
        self.authenticated = True
        self._bootstrap_done = False
        self.bootstrap_notices = []
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
        self.playlist_error = ""
        self.search_results = None
        self.player = None
        self.devices = []
        self.view = "home"
        self.invalidate()

    # -- worker jobs (background thread) --------------------------------------

    def _job_bootstrap(self):
        """Fetch the home-view data. Per-section degradation: Spotify dev-mode
        apps get 403s on whole endpoint families regardless of scopes (Alec's
        first session), so a non-401 ApiError degrades THAT section to an
        inline note naming the call while the rest of the library loads. A
        401 means the token is dead — that still fails the job (and the
        session) outright, named. Generic exceptions likewise fail named."""
        assert self._client is not None
        notices: list[str] = []

        def section(label: str, fn, fallback):
            try:
                return fn()
            except sl_api.ApiError as exc:
                if exc.kind == sl_api.ErrorKind.UNAUTHORIZED:
                    raise sl_api.ApiError(exc.kind, f"{label}: {exc}",
                                          status=exc.status) from exc
                # UI copy stays human; the raw API detail goes to the log.
                log.info("bootstrap section %r degraded: %s", label, exc)
                notices.append(f"Couldn't load {label} right now")
                return fallback
            except Exception as exc:  # noqa: BLE001 — surfaced via bootstrap_error
                raise RuntimeError(f"{label}: {exc}") from exc

        profile = section("profile", self._client.me, None)
        playlists = section("playlists", self._client.my_playlists, [])
        top_tracks = section("top tracks", lambda: self._client.top_tracks(limit=10), [])
        new_releases = section("new releases", lambda: self._client.new_releases(limit=12), [])
        top_artists: list = []
        try:
            top_artists = self._client.top_artists(limit=12)
        except sl_api.ApiError:
            pass  # top/artists can 403 for some accounts; home still works
        return (profile, playlists, top_tracks, new_releases, top_artists, notices)

    # -- embedded login (native web view) ----------------------------------------

    def _start_login(self) -> None:
        """Connect Spotify: embedded web-view flow when a bridge is up, else browser."""
        self.auth_error = ""
        bridge = native_controls()
        if bridge is not None and bridge.available and self._try_embedded_login(bridge):
            return
        self.auth_working = True
        self.worker.submit("login", self._job_login)
        self.invalidate()

    def _try_embedded_login(self, bridge) -> bool:
        """Open Spotify's authorize page in an in-app web view. False -> browser flow."""
        try:
            verifier = sl_oauth.generate_verifier()
            state = sl_oauth.generate_state()
            redirect_uri = sl_oauth.redirect_uri_for_port(sl_oauth.DEFAULT_PORT)
            url = sl_oauth.authorize_url(
                client_id=self.client_id,
                redirect_uri=redirect_uri,
                challenge=sl_oauth.challenge_s256(verifier),
                state=state,
            )
            width = float(self.ctx.display_width_px)
            height = float(self.ctx.display_height_px)
            web_view = bridge.create_web_view(
                x=0.0, y=0.0, width=width, height=height,
                redirect_prefix=redirect_uri, on_redirect=self._on_embedded_redirect,
                on_navigation_state=self._on_embedded_nav_state)
        except Exception:  # noqa: BLE001 — no WebKit, no window: browser still works
            return False
        web_view.load_url(url)
        self._login_verifier = verifier
        self._login_state = state
        self._login_redirect_uri = redirect_uri
        self._login_web_view = web_view
        try:
            # Sheet controls ride their own frosted capsules (same
            # construction as Save/Connect) so they stay visible over
            # arbitrary page content. Cancel top-right is the way out; Back
            # top-left steps through the provider's own pages (Google's
            # sign-in offers no way back to the email step otherwise).
            cancel_capsule = bridge.create_glass_surface(
                x=width - 106, y=16, width=90, height=36,
                corner_radius=18.0, style="regular")
            cancel = bridge.create_button(
                x=width - 106, y=16, width=90, height=36, title="Cancel",
                within=cancel_capsule,
                on_press=lambda: self._dispatch_action("cancel_login", None, 0.0))
            back_capsule = bridge.create_glass_surface(
                x=16, y=16, width=90, height=36,
                corner_radius=18.0, style="regular")
            back = bridge.create_button(
                x=16, y=16, width=90, height=36, title="Back",
                within=back_capsule,
                on_press=lambda: web_view.go_back())
            back.set_enabled(False)  # quiet until the page has history
        except Exception as exc:  # noqa: BLE001
            # Escape is suppressed while the sheet is live: without Cancel
            # there is no way out — tear the sheet down and use the browser
            # flow, which has its own cancel path.
            print(f"[luvatrix] embedded login sheet controls failed: {exc!r}; "
                  "using browser flow", file=sys.stderr, flush=True)
            self._login_web_view = None
            web_view.destroy()
            return False
        self._login_cancel_capsule = cancel_capsule
        self._login_cancel_button = cancel
        self._login_back_capsule = back_capsule
        self._login_back_button = back
        self.auth_working = True
        self.invalidate()
        return True

    def _on_embedded_nav_state(self) -> None:
        """Web view history changed (KVO on canGoBack): arm/disarm Back."""
        back = self._login_back_button
        view = self._login_web_view
        if back is not None and view is not None:
            back.set_enabled(bool(view.can_go_back))

    def _on_embedded_redirect(self, url: str) -> None:
        """Navigation delegate callback; stash for the app thread, never handle inline."""
        self._embedded_callback = url
        self.invalidate()

    def _end_embedded_login(self) -> None:
        if self._login_web_view is not None:
            self._login_web_view.destroy()
            self._login_web_view = None
        if self._login_cancel_button is not None:
            self._login_cancel_button.destroy()
            self._login_cancel_button = None
        if self._login_cancel_capsule is not None:
            self._login_cancel_capsule.destroy()
            self._login_cancel_capsule = None
        if self._login_back_button is not None:
            self._login_back_button.destroy()
            self._login_back_button = None
        if self._login_back_capsule is not None:
            self._login_back_capsule.destroy()
            self._login_back_capsule = None

    def _job_embedded_exchange(self, callback_url: str):
        code = sl_oauth.parse_callback_url(callback_url, self._login_state)
        return sl_oauth.exchange_code(
            client_id=self.client_id,
            redirect_uri=self._login_redirect_uri,
            code=code,
            verifier=self._login_verifier,
        )

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
        if self._embedded_callback is not None:
            # Spotify redirected inside the embedded web view: dismiss it and
            # finish PKCE off-thread. The callback URL never left the app.
            callback_url = self._embedded_callback
            self._embedded_callback = None
            self._end_embedded_login()
            self.worker.submit("login", lambda: self._job_embedded_exchange(callback_url))
            self.invalidate()
        for label, outcome in self.worker.poll():
            self._apply_result(label, outcome)

    def _apply_result(self, label: str, outcome) -> None:
        if label == "bootstrap":
            # Any outcome means the job finished: the home view must leave the
            # loading state regardless of success, failure, or empty data.
            self._bootstrap_done = True
        if isinstance(outcome, sl_api.ApiError):
            self._apply_api_error(label, outcome)
            return
        if isinstance(outcome, sl_oauth.OAuthError):
            if label == "login":
                if self.auth_working:  # not a user cancel
                    self.auth_error = str(outcome)
                self.auth_working = False
            elif label == "bootstrap":
                self.bootstrap_error = f"Could not load your library: {outcome}"
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
                self._art_failures[label[4:]] = time.monotonic()
            elif label == "bootstrap":
                self.bootstrap_error = f"Could not load your library: {outcome}"
            elif label.startswith("playlist:"):
                # Inline error state in the playlist view, not a vanishing toast.
                self.playlist_error = str(outcome)
            else:
                self._toast(str(outcome))
            self.invalidate()
            return

        if label == "bootstrap":
            profile, playlists, top_tracks, new_releases, top_artists, notices = outcome
            self.profile = profile
            self.playlists = playlists
            self.bootstrap_notices = list(notices)
            self.home_sections = sl_ui.build_home_sections(
                top_tracks=top_tracks,
                new_releases=new_releases,
                playlists=playlists[:12],
                top_artists=top_artists,
                image_target_px=self._art_pick_target(sl_views.CARD_ART),
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
                self.playlist_error = ""
        elif label.startswith("art:"):
            self._art_in_flight.discard(label[4:])
            self._art_failures.pop(label[4:], None)
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
        elif label.startswith("playlist:"):
            # The playlist view renders this as a persistent inline state with
            # a Retry affordance; a 6s toast would leave "Loading…" forever.
            self.playlist_error = str(error)
        elif label == "bootstrap":
            # Persistent, not a 6s toast: a failed bootstrap must not leave
            # the home view claiming "Loading your music…" forever.
            self.bootstrap_error = f"Could not load your library: {error}"
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
        list_top = sl_views.SIDEBAR_LIST_TOP
        sidebar_update = self.scrollbar_sidebar.update(
            state,
            x=sl_views.SIDEBAR_W - 10,
            y=list_top,
            width=13,
            height=max(0.0, self.display.height_px - 64 - list_top),
            content_extent=30.0 * len(self.playlists),
            viewport_extent=max(1.0, self.display.height_px - 64 - list_top),
            offset=self.sidebar_scroll,
        )
        if sidebar_update.consumed:
            self.sidebar_scroll = sidebar_update.offset
            self.invalidate()
            return
        viewport = self.display.height_px - sl_views.DOCK_H
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
                self.display.height_px - 64 - sl_views.SIDEBAR_LIST_TOP,
            )
        else:
            viewport = self.display.height_px - sl_views.DOCK_H
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
            self.playlist_error = ""
            self.worker.submit(f"playlist:{payload}", lambda: self._job_playlist(payload))
            self.invalidate()
        elif action == "retry_playlist":
            self.playlist_detail = None
            self.playlist_error = ""
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
            self._start_login()
        elif action == "cancel_login":
            sheet_up = self._login_web_view is not None
            self._end_embedded_login()
            # Cancel wins over a same-tick redirect intercept: never let a
            # stashed callback submit the exchange after the user bailed.
            self._embedded_callback = None
            if self._login_receiver is not None:
                self._login_receiver.close()
            self.auth_working = False
            if sheet_up:
                # Sheet closed without a redirect intercept: user bailed, or
                # the provider dead-ended on its own error page (Spotify's
                # authorize page defers client_id validation until after IdP
                # sign-in, rendering a bare `client_id: Invalid`). Don't drop
                # back to a silent wall.
                self.auth_error = ("Login didn't complete — double-check your "
                                   "Client ID and try again.")
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
        if control is None and key in CONTROL_KEY_NAMES:
            control = key

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

    def _backing_scale(self) -> float:
        try:
            return max(0.25, float(self.display.backing_scale))
        except Exception:  # noqa: BLE001 — pre-init or headless: point size is fine
            return 1.0

    def _art_pick_target(self, point_size: float) -> int:
        """Source-image pixels that cover ``point_size`` on the current display."""
        return max(1, int(round(float(point_size) * self._backing_scale())))

    def art_for(self, url: str | None, size: int):
        """Cached RGBA pixels, or None (and a scheduled fetch) on a miss."""
        if not url:
            return None
        device_size = self._art_pick_target(size)
        key = f"{url}|{device_size}"
        try:
            return self.art_cache.fetch(url, device_size, http_get=self._fail_offline)
        except sl_art.ArtError:
            pass
        failed_at = self._art_failures.get(key)
        if failed_at is not None and time.monotonic() - failed_at < ART_FAIL_TTL_SECS:
            return None  # backing off: keep the placeholder, skip the refetch
        if key not in self._art_in_flight:
            self._art_in_flight.add(key)
            self.worker.submit(f"art:{key}", lambda: self._job_art(url, device_size))
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

    # -- native controls -------------------------------------------------------------

    def _sync_glass_surfaces(self, width: float, height: float, *,
                             want_login_field: bool,
                             want_save_button: bool = False,
                             want_connect_button: bool = False) -> None:
        """Create/update/destroy app-declared glass regions to match the layout.

        Native glass is kept ONLY behind native content (login-wall capsules);
        text-bearing authed chrome draws scene tint plates instead, because an
        AppKit plate above the Metal layer blurs every scene glyph beneath it.
        """
        bridge = native_controls()
        available = bool(bridge is not None and bridge.available)
        wanted: dict[str, dict] = {}
        if available:
            if want_login_field:
                x, y, w, h = sl_views.login_field_rect(width, height)
                wanted["login_field"] = dict(x=x, y=y, width=w, height=h,
                                             corner_radius=20.0, style="regular")
            if want_save_button:
                x, y, w, h = sl_views.login_save_button_rect(width, height)
                wanted["login_save_button"] = dict(x=x, y=y, width=w, height=h,
                                                   corner_radius=20.0, style="regular")
            if want_connect_button:
                x, y, w, h = sl_views.login_connect_button_rect(width, height)
                wanted["login_connect_button"] = dict(x=x, y=y, width=w, height=h,
                                                      corner_radius=24.0, style="regular")
        for key in list(self._glass_surfaces):
            if key not in wanted:
                self._glass_surfaces.pop(key).destroy()
        for key, spec in wanted.items():
            surface = self._glass_surfaces.get(key)
            if surface is None:
                self._glass_surfaces[key] = bridge.create_glass_surface(**spec)
            else:
                # Always re-apply: the bridge derives the AppKit frame from the
                # content view's current bounds, which can change under an
                # unchanged logical frame (window resize). Early-outing here
                # baked a stale offset into the native plate.
                surface.set_frame(spec["x"], spec["y"], spec["width"], spec["height"])

    def _sync_native_login_buttons(self, width: float, height: float) -> None:
        """Create/update/destroy the native glass buttons on the auth wall."""
        bridge = native_controls()
        wanted: dict[str, tuple] = {}
        if (bridge is not None and bridge.available
                and not self.authenticated and not self.auth_working):
            if not self.client_id:
                wanted["save"] = (sl_views.login_save_button_rect(width, height),
                                  "Save", "save_client_id")
            else:
                wanted["connect"] = (sl_views.login_connect_button_rect(width, height),
                                     "Connect Spotify", "start_login")
        for key in list(self._native_buttons):
            if key not in wanted:
                self._native_buttons.pop(key).destroy()
                self.invalidate()
        for key, (rect, title, action) in wanted.items():
            button = self._native_buttons.get(key)
            if button is None:
                capsule = self._glass_surfaces.get(f"login_{key}_button")
                x, y, w, h = rect
                button = bridge.create_button(
                    x=x, y=y, width=w, height=h, title=title, within=capsule,
                    on_press=lambda a=action: self._dispatch_action(a, None, 0.0))
                self._native_buttons[key] = button
                self.invalidate()
            else:
                button.set_frame(*rect)  # re-apply against current bounds, always
        save = self._native_buttons.get("save")
        if save is not None:
            save.set_enabled(bool(self.client_id_draft.strip()))

    def _login_field_editor_rect(self, width: float, height: float,
                                 glass) -> tuple[float, float, float, float]:
        """Rect for the native Client ID editor.

        Inside a glass capsule the borderless editor insets 14pt at the sides
        and vertically centers a 20pt-high line, so the placeholder and text
        sit mid-plate instead of top-aligned in the 40pt plate.
        """
        x, y, w, h = sl_views.login_field_rect(width, height)
        if glass is not None:
            return (x + 14.0, y + (h - 20.0) / 2.0, w - 28.0, 20.0)
        return (x, y, w, h)

    def _sync_native_login_field(self, width: float, height: float) -> None:
        """Create/position/destroy the native Client ID field to match the login view."""
        bridge = native_controls()
        want = bool(
            bridge is not None
            and bridge.available
            and not self.authenticated
            and not self.client_id
            and not self.auth_working
        )
        if want and self._native_client_id_field is None:
            glass = self._glass_surfaces.get("login_field")
            x, y, w, h = self._login_field_editor_rect(width, height, glass)
            self._native_client_id_field = bridge.create_text_field(
                x=x,
                y=y,
                width=w,
                height=h,
                within=glass,
                bordered=glass is None,
                placeholder="Client ID",
                value=self.client_id_draft,
                on_change=self._on_native_client_id_change,
                on_submit=lambda _value: self._dispatch_action("save_client_id", None, 0.0),
            )
            self.invalidate()
        elif not want and self._native_client_id_field is not None:
            self._native_client_id_field.destroy()
            self._native_client_id_field = None
            self.invalidate()
        if self._native_client_id_field is not None:
            # Re-apply every render: the bridge derives the AppKit frame from
            # the content view's current bounds, which can change under an
            # unchanged logical frame (window resize drifted the plate).
            glass = self._glass_surfaces.get("login_field")
            x, y, w, h = self._login_field_editor_rect(width, height, glass)
            self._native_client_id_field.set_frame(x, y, w, h)

    def _on_native_client_id_change(self, value: str) -> None:
        self.client_id_draft = value
        self.invalidate()

    def _sync_embedded_sheet_geometry(self, width: float, height: float) -> None:
        """Re-apply embedded-login sheet frames every render.

        The web view and Cancel/Back controls bake their frames at creation;
        a window resize after the sheet opened left them shifted (measured:
        Cancel capsule ~22pt right of its design slot). Same re-apply policy
        as the login field/buttons.
        """
        if self._login_web_view is not None:
            self._login_web_view.set_frame(0.0, 0.0, width, height)
        if self._login_cancel_capsule is not None:
            self._login_cancel_capsule.set_frame(width - 106.0, 16.0, 90.0, 36.0)
        if self._login_cancel_button is not None:
            self._login_cancel_button.set_frame(width - 106.0, 16.0, 90.0, 36.0)
        if self._login_back_capsule is not None:
            self._login_back_capsule.set_frame(16.0, 16.0, 90.0, 36.0)
        if self._login_back_button is not None:
            self._login_back_button.set_frame(16.0, 16.0, 90.0, 36.0)

    # -- MCP agent surface -----------------------------------------------------
    # Hooks run on the runtime thread between ticks (queued by the MCP server
    # thread), so no locking is needed here. Tool names must not start with
    # "app_" (reserved for built-ins).

    def mcp_state(self) -> dict:
        player = self.player
        now_playing = None
        if player is not None and player.track is not None:
            now_playing = {
                "track": player.track.name,
                "artists": ", ".join(artist.name for artist in player.track.artists),
                "duration_ms": player.track.duration_ms,
                "progress_ms": player.progress_ms,
                "is_playing": player.is_playing,
                "device": player.device.name if player.device is not None else None,
            }
        return {
            "view": self.view,
            "authenticated": self.authenticated,
            "client_id_configured": bool(self.client_id),
            "client_id_draft_len": len(self.client_id_draft),  # never the value
            "native_field_active": self._native_client_id_field is not None,
            "search_query": self.search_query,
            "content_scroll": round(self.content_scroll, 1),
            "hit_actions": sorted({region.action for region in self._hits}),
            "now_playing": now_playing,
        }

    def mcp_tools(self) -> list[dict]:
        return [
            {
                "name": "sl_set_client_id",
                "description": (
                    "Set the Spotify Client ID into the login field. Uses the native "
                    "text field when present (synthetic keyboard input cannot enter "
                    "AppKit controls), otherwise the drawn-field draft."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            },
            {
                "name": "sl_submit_client_id",
                "description": "Save the current Client ID draft (same as pressing Enter in the field).",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]

    def mcp_call(self, name: str, arguments: dict) -> dict:
        if name == "sl_set_client_id":
            value = str((arguments or {}).get("value", ""))
            field = self._native_client_id_field
            if field is not None:
                # Programmatic setStringValue does not fire controlTextDidChange,
                # so the draft is set explicitly below for both paths.
                field.set_value(value)
            self.client_id_draft = value
            self.invalidate()
            return {
                "client_id_draft_len": len(self.client_id_draft),
                "native_field_active": field is not None,
            }
        if name == "sl_submit_client_id":
            self._dispatch_action("save_client_id", None, 0.0)
            return {"client_id_configured": bool(self.client_id)}
        raise KeyError(name)

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
            bridge = native_controls()
            bridge_up = bridge is not None and bridge.available
            self.glass_active = False  # chrome glass is an authed-only concern
            want_field = bool(bridge_up and not self.client_id and not self.auth_working)
            want_connect = bool(bridge_up and self.client_id and not self.auth_working)
            self._sync_glass_surfaces(width, height,
                                      want_login_field=want_field,
                                      want_save_button=want_field,
                                      want_connect_button=want_connect)
            self._sync_native_login_field(width, height)
            self._sync_native_login_buttons(width, height)
            self._sync_embedded_sheet_geometry(width, height)
            sl_views.draw_login(frame, self, out, width=width, height=height, mouse=mouse,
                                native_field_active=self._native_client_id_field is not None,
                                native_save_active="save" in self._native_buttons,
                                native_connect_active="connect" in self._native_buttons,
                                embedded_active=self._login_web_view is not None)
        else:
            bridge = native_controls()
            # Text-bearing chrome draws scene tint plates (crisp by
            # construction); glass_active keeps the translucent treatment and
            # content-under-bar flow while the bridge is up.
            self.glass_active = bridge is not None and bridge.available
            self._sync_glass_surfaces(width, height, want_login_field=False)
            if self.view == "search":
                sl_views.draw_search(frame, self, out, width=width, height=height, mouse=mouse)
            elif self.view.startswith("playlist:"):
                sl_views.draw_playlist(frame, self, out, width=width, height=height, mouse=mouse)
            elif self.view == "library":
                sl_views.draw_library(frame, self, out, width=width, height=height, mouse=mouse)
            else:
                sl_views.draw_home(frame, self, out, width=width, height=height, mouse=mouse)

            # Content-area scrollbar for tall views.
            viewport = height - sl_views.DOCK_H
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

            sl_views.draw_dock_scrim(frame, width=width, height=height)
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
        toast_y = height - sl_views.DOCK_H - 56
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
            font_family=sl_views.FONT_FAMILY,
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
        self._end_embedded_login()
        if self._native_client_id_field is not None:
            self._native_client_id_field.destroy()
            self._native_client_id_field = None
        for button in self._native_buttons.values():
            button.destroy()
        self._native_buttons.clear()
        for surface in self._glass_surfaces.values():
            surface.destroy()
        self._glass_surfaces.clear()
        self.glass_active = False
        if self._login_receiver is not None:
            self._login_receiver.close()
        self.worker.shutdown()


def create() -> SpotifyLightApp:
    return SpotifyLightApp()
