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
import sl_layout
import sl_models
import sl_oauth
import sl_player
import sl_store
import sl_ui
import sl_views
import sl_worker

from luvatrix_core.core.playback_bridge import PlaybackEventKind

log = logging.getLogger("spotify_light")

# Event-driven sync (Alec): the bar moves on the wall clock, so steady-state
# polls exist only to catch what the app cannot know — the track boundary
# and external control. The heartbeat bounds that drift: 60s while playing
# (worst-case stale display after an external skip), 180s while paused
# (nothing advances; the user's return resyncs via activity anyway).
HEARTBEAT_PLAYING_SECS = 60.0
HEARTBEAT_PAUSED_SECS = 180.0
POLL_AFTER_ACTION_SECS = 0.7
# Fire this far before the computed track end: covers /me/player progress
# quantization and the request round-trip, so the flip confirms on time.
POLL_BOUNDARY_SKEW_SECS = 2.0
# Floor for any computed wait — a track shorter than the skew must not
# schedule a zero/negative wait or spin.
POLL_MIN_INTERVAL_SECS = 5.0
# Input after this much sync staleness means "user came back": resync once.
ACTIVITY_RESYNC_MIN_SECS = 15.0
# Fallback when a 429 arrives without a usable Retry-After header: long
# enough for a sliding-window limit to open up, short enough to feel alive.
RATE_LIMIT_DEFAULT_SECS = 10.0
SEARCH_DEBOUNCE_SECS = 0.4
# SL-41 retained scroll band: mid-gesture wheel ticks publish a
# transform-only content offset; a re-window render fires at most this often
# (keeps cull/hover/thumb honest) and one settle render lands after the
# gesture goes quiet.
SCROLL_REWINDOW_INTERVAL_S = 0.1
SCROLL_SETTLE_S = 0.12
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

    def __init__(self, cfg_dir: Path, client_id: str, tokens: sl_oauth.TokenSet,
                 on_token=None) -> None:
        self._lock = threading.Lock()
        self._cfg_dir = cfg_dir
        self._client_id = client_id
        self._tokens = tokens
        self._on_token = on_token

    def access_token(self) -> str:
        with self._lock:
            if self._tokens.needs_refresh(time.time()):
                refreshed = sl_oauth.refresh_tokens(
                    self._client_id, self._tokens.refresh_token or ""
                ).with_fallback_refresh(self._tokens)
                self._tokens = refreshed
                sl_store.save_tokens(self._cfg_dir, refreshed)
                if self._on_token is not None:
                    # The web playback surface needs the fresh token; the SDK
                    # does not refresh on its own.
                    self._on_token(refreshed.access_token)
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
        # SL-39 expanding search cluster: the dock's search circle grows into
        # the query field while the library rail docks right-aligned above it.
        # _search_pre_expand_view is restored on dismiss (close cap / Escape);
        # navigating elsewhere collapses without the restore.
        self.search_expanded = False
        self._search_pre_expand_view = "home"
        self._hits: list[sl_views.HitRegion] = []
        self._mouse = (0.0, 0.0)
        self._drag: tuple[str, object] | None = None
        self.content_scroll = 0.0
        self.sidebar_scroll = 0.0
        self._content_height = 0.0
        # SL-41 band state: _render_scroll_sub is what content draws subtract
        # (0 when the retained band carries the offset); _render_cull_lo/hi
        # bound the draw window in that same space; _last_scroll_build_t and
        # _scroll_settle_due drive the re-window throttle and settle render.
        # The band is GESTURE-scoped (round 67, runner's encode finding):
        # resting frames render bandless so non-scroll frames never pay the
        # tier-split encode tax; _band_engaged flips on the first visible
        # tick of a gesture and off at the settle render.
        self._render_scroll_sub = 0.0
        self._render_cull_lo = 0.0
        self._render_cull_hi = 0.0
        self._last_scroll_build_t = 0.0
        self._scroll_settle_due: float | None = None
        self._band_engaged = False
        self._last_scroll_published = 0.0
        self._hits_content_space = False

        # Under-glass pill (SL-36): a real NSGlassEffectView below the render
        # surface replaces the pill's simulated plate on capable hosts.
        # _pill_glass_active — window should clear transparent this frame;
        # _pill_glass_live — the native plate exists (drawn plate + backdrop
        # key off this); _pill_glass_disabled — creation failed, stop trying.
        self._pill_glass_active = False
        self._pill_glass_live = False
        self._pill_glass_disabled = False
        self._pill_glass_rect: tuple[float, float, float, float] | None = None
        # Whole-window material (SL-38): one behind-window backdrop surface
        # replaces the scene's near-black base on capable hosts.
        # _window_material_active — the backdrop is wanted this frame;
        # _window_material_live — the native backdrop exists (scene tiles and
        # component fill alphas key off this); _backdrop_disabled — creation
        # failed, keep the SL-36 opaque tiles and stop retrying.
        self._window_material_active = False
        self._window_material_live = False
        self._backdrop_disabled = False
        self._glass_specs: dict[str, dict] = {}

        # Live layout overrides (MCP, round 31): seeded from the persisted
        # layout file (round 36, SL-20) — the file is the source of truth the
        # layout tools write through to, so a nudge survives this reboot.
        self.layout_overrides = sl_layout.load(sl_layout.default_path())
        # Declared visual effects (SL-34): scrim/gradient bands ride the same
        # file — the effect tools tune them live and persist the same way.
        # Purely additive: SL-33/SL-35 removed both stock scrims, so a fresh
        # boot declares none and draws none.
        self.effect_specs = sl_layout.load_effects(sl_layout.default_path())

        # Bookkeeping.
        self.now_monotonic = time.monotonic()
        self._next_player_poll = 0.0
        self._next_progress_tick = 0.0
        self._last_player_action = None  # for no-active-device transfer+retry
        self._rate_limited_until = 0.0  # poll loop stays quiet while ahead
        self.up_next = None  # queue head, pre-staged into the pill at the boundary
        self._pending_device_recovery = False  # NO_ACTIVE_DEVICE awaiting fresh devices
        self._last_activity_resync = 0.0
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
        # In-app playback (Web Playback SDK): surface + device live only while
        # a streaming-scoped session runs on a scripted-view-capable bridge.
        self._web_surface = None
        self._web_device: sl_player.WebPlaybackDevice | None = None
        self._web_surface_factory = None  # tests inject; default builds the WK surface
        self._web_auth_failed = False  # toast once, then stay on Connect remote

        self.set_continuous_render(False)

        if self.client_id and self._tokens is not None:
            self._begin_session(self._tokens)

    # -- session wiring ------------------------------------------------------

    def _begin_session(self, tokens: sl_oauth.TokenSet) -> None:
        self._stop_web_playback()
        self._token_manager = TokenManager(self.cfg_dir, self.client_id, tokens,
                                           on_token=self._push_web_token)
        self._client = sl_api.SpotifyClient(token_provider=self._token_manager.access_token)
        self.authenticated = True
        self._bootstrap_done = False
        self.bootstrap_notices = []
        self.worker.submit("bootstrap", self._job_bootstrap)
        self.worker.submit("poll-devices", self._job_poll_devices)
        self._next_player_poll = 0.0  # poll immediately
        self._start_web_playback(tokens)

    # -- in-app playback (Web Playback SDK) ------------------------------------

    def _start_web_playback(self, tokens: sl_oauth.TokenSet) -> None:
        """Register the SDK device when the session can host it. Missing scope
        or bridge keeps today's Connect-remote behavior — no forced re-login."""
        if not sl_oauth.has_streaming_scope(tokens):
            log.info("tokens lack the streaming scope; in-app playback off until re-login")
            return
        bridge = native_controls()
        if bridge is None or not bridge.available or not hasattr(bridge, "create_scripted_web_view"):
            return
        factory = self._web_surface_factory or self._default_web_surface
        try:
            surface = factory(bridge, device_name=sl_player.DEFAULT_DEVICE_NAME,
                              token=tokens.access_token)
        except Exception:  # noqa: BLE001 — in-app playback is additive
            log.exception("web playback surface failed to start")
            return
        self._web_surface = surface
        self._web_device = sl_player.WebPlaybackDevice(surface)
        self._web_auth_failed = False
        try:
            self._web_device.connect()
        except Exception:  # noqa: BLE001
            log.exception("web playback connect failed")

    @staticmethod
    def _default_web_surface(bridge, *, device_name: str, token: str):
        # Lazy: the WK surface imports WebKit via PyObjC — macos extra only.
        from luvatrix_core.platform.macos.playback_surface import WKWebPlaybackSurface

        surface = WKWebPlaybackSurface(bridge, device_name=device_name, token=token)
        surface.start()
        return surface

    def _stop_web_playback(self) -> None:
        surface = self._web_surface
        self._web_surface = None
        self._web_device = None
        if surface is not None:
            try:
                surface.stop()
            except Exception:  # noqa: BLE001 — teardown must not raise
                log.exception("web playback surface stop failed")

    def _push_web_token(self, token: str) -> None:
        surface = self._web_surface
        if surface is not None:
            try:
                surface.set_token(token)
            except Exception:  # noqa: BLE001
                log.exception("web playback token push failed")

    def _web_is_active(self) -> bool:
        web = self._web_device
        player = self.player
        return bool(
            web is not None and web.device_id
            and player is not None and player.device is not None
            and player.device.id == web.device_id
        )

    def _transport_target(self):
        """What transport actions run against: the web device when it is
        registered (routing itself decides local-vs-Connect per verb), else
        the plain Connect client."""
        web = self._web_device
        if web is None or web.device_id is None:
            return self._client
        return sl_player.TransportRouter(self._client, web, self._web_is_active)

    def _pump_web_playback(self) -> None:
        """Drain SDK events each tick: adopt local state when the web device
        is the active one, surface auth/account problems once, and pick the
        freshly registered device up in the Connect list."""
        web = self._web_device
        if web is None:
            return
        try:
            events = web.drain_events()
        except Exception:  # noqa: BLE001
            log.exception("web playback drain failed")
            return
        if not events:
            return
        state_arrived = False
        for event in events:
            kind = event.kind
            if kind is PlaybackEventKind.READY:
                log.info("in-app playback device registered: %s", web.device_id)
                if self._client is not None:
                    # The SDK device now appears in GET /me/player/devices.
                    self.worker.submit("poll-devices", self._job_poll_devices)
            elif kind is PlaybackEventKind.AUTH_ERROR:
                if not self._web_auth_failed:
                    self._web_auth_failed = True
                    self._toast("In-app playback sign-in failed — using Connect remote")
            elif kind is PlaybackEventKind.ACCOUNT_ERROR:
                self._toast("Spotify Premium is required for in-app playback")
            elif kind in (PlaybackEventKind.INIT_ERROR, PlaybackEventKind.PLAYBACK_ERROR):
                log.info("web playback %s: %s", kind.value, event.payload)
            elif kind in (PlaybackEventKind.STATE_CHANGED, PlaybackEventKind.STATE_SNAPSHOT):
                state_arrived = True
        if state_arrived and web.last_state is not None and self._web_is_active():
            self.player = web.last_state
            self._player_synced_at = time.monotonic()
        self.invalidate()

    def _end_session(self) -> None:
        self._stop_web_playback()
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
        self.search_expanded = False
        self.search_focused = False
        self._search_pre_expand_view = "home"
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
        """Playback snapshot + queue head. Devices are NOT fetched here —
        they change on human timescales, so they ride their own triggers.
        The queue fetch is gated on the granted scope (SL-32): the scope is
        no longer requested, so fresh tokens would 403 every poll. Legacy
        scope-holding tokens keep pre-staging, and a revoked-endpoint 403
        still degrades to None rather than sinking the snapshot."""
        assert self._client is not None
        player = self._client.player_state()
        granted = (self._tokens.scope if self._tokens is not None else "").split()
        if "user-read-playback-queue" not in granted:
            return (player, None)
        try:
            up_next = self._client.up_next()
        except sl_api.ApiError as exc:
            log.info("queue fetch degraded (%s); pre-staging off this poll", exc)
            up_next = None
        return (player, up_next)

    def _job_poll_devices(self):
        assert self._client is not None
        return self._client.devices()

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
        fn(self._transport_target())
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
            player, up_next = outcome
            self.player = player
            self.up_next = up_next
            self._player_synced_at = time.monotonic()
            self._schedule_player_poll()
            if player and player.device and player.device.volume_percent is not None:
                self.last_volume = player.device.volume_percent
            if self._pending_device_recovery and time.monotonic() >= self._rate_limited_until:
                # A rate limit earlier held the recovery fetch; take it now.
                self.worker.submit("poll-devices", self._job_poll_devices)
        elif label == "poll-devices":
            self.devices = outcome
            if self._pending_device_recovery:
                self._pending_device_recovery = False
                self._recover_device()
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
        if error.kind == sl_api.ErrorKind.RATE_LIMITED:
            # Any job can see the 429; whatever it was, the whole app quiets
            # down for the window — that is what lets the limit recover.
            self._enter_rate_limit(error.retry_after_secs)
            self.invalidate()
            return
        if error.kind == sl_api.ErrorKind.UNAUTHORIZED:
            self._toast("Session expired — please reconnect Spotify")
            self._end_session()
            return
        if error.kind == sl_api.ErrorKind.PREMIUM_REQUIRED:
            self._toast("Spotify Premium is required for playback control")
        elif error.kind == sl_api.ErrorKind.DEVICE_NOT_FOUND:
            if label == "player-action":
                # The cached device list led us astray — refetch, then decide.
                # While rate-limited we hold the flag; the next successful
                # player poll takes the recovery fetch instead of queueing up.
                self._pending_device_recovery = True
                if time.monotonic() >= self._rate_limited_until:
                    self.worker.submit("poll-devices", self._job_poll_devices)
            else:
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

    def _recover_device(self) -> None:
        """Decision after the fresh devices fetch for a NO_ACTIVE_DEVICE
        player action: auto-pick when obvious, prompt only when ambiguous."""
        if self._auto_pick_device():
            pass  # obvious target: transfer + retry, like the real app
        elif len(self.devices) > 1 and not any(d.is_active for d in self.devices):
            # Genuinely ambiguous — the only case that prompts.
            self.show_devices = True
            self._toast("Pick a device")
        elif not self.devices:
            self._toast("No devices found — open Spotify on a device first")
        else:
            self._toast("No active device — pick one under Devices")

    def _toast(self, message: str) -> None:
        self.status_message = message
        self._status_until = time.monotonic() + STATUS_TOAST_SECS

    def _enter_rate_limit(self, retry_after_secs: float | None) -> None:
        now = time.monotonic()
        duration = retry_after_secs if retry_after_secs and retry_after_secs > 0 else RATE_LIMIT_DEFAULT_SECS
        already_quiet = now < self._rate_limited_until
        self._rate_limited_until = now + duration
        # One resync the moment the window lifts — the app has been blind for
        # the whole backoff; boundary/heartbeat resume from that fresh state.
        self._next_player_poll = self._rate_limited_until
        if not already_quiet:
            # Once per limiting window, not once per failed poll.
            self._toast(f"Spotify rate limit hit — backing off {duration:g}s")

    # -- timers -----------------------------------------------------------------

    def _schedule_player_poll(self) -> None:
        """Next proactive poll: the heartbeat, or the track boundary when that
        lands sooner. Recomputed on every fresh player state, so an external
        seek/skip moves the boundary instead of being missed until a fixed
        interval expires."""
        now = time.monotonic()
        heartbeat = HEARTBEAT_PLAYING_SECS if (
            self.player and self.player.is_playing) else HEARTBEAT_PAUSED_SECS
        next_poll = now + heartbeat
        if self.player and self.player.is_playing and self.player.track:
            remaining = (self.player.track.duration_ms - self.progress_ms()) / 1000.0
            boundary = now + max(remaining - POLL_BOUNDARY_SKEW_SECS, POLL_MIN_INTERVAL_SECS)
            next_poll = min(next_poll, boundary)
        self._next_player_poll = next_poll

    def _handle_timers(self) -> None:
        now = time.monotonic()
        self.now_monotonic = now

        if (self.authenticated and self._client is not None
                and now >= self._next_player_poll and now >= self._rate_limited_until):
            self._schedule_player_poll()
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

        # SL-41: the gesture went quiet — one rebuild recentres the draw
        # window and refreshes hover/thumb, and the band DISENGAGES: the
        # resting frame is the pre-SL-41 bandless shape (round 67: non-scroll
        # frames must not pay the tier-split encode tax).
        if self._scroll_settle_due is not None and now >= self._scroll_settle_due:
            self._scroll_settle_due = None
            self._band_engaged = False
            self.invalidate()

    # -- input --------------------------------------------------------------------

    def _maybe_activity_resync(self) -> None:
        """Input after a stale stretch means the user is back at the window:
        resync now rather than waiting out the heartbeat. Stand-in for a
        window-focus event, which AppContext does not expose today."""
        now = time.monotonic()
        if not (self.authenticated and self._client is not None):
            return
        if now - self._player_synced_at < ACTIVITY_RESYNC_MIN_SECS:
            return  # fresh enough — ordinary interaction stays free
        if now - self._last_activity_resync < ACTIVITY_RESYNC_MIN_SECS:
            return  # throttle: at most one resync per stale window
        if now < self._rate_limited_until:
            return  # a rate-limit deadline suppresses every scheduled poll
        self._last_activity_resync = now
        self._next_player_poll = now

    def _handle_input(self, events) -> None:
        state = self.input.state
        self._mouse = (state.mouse_x, state.mouse_y)

        if events:
            self._maybe_activity_resync()

        for event in events:
            if getattr(event, "device", None) == "keyboard":
                self._handle_key(event)

        # Scrollbar drags get first claim on the mouse.
        list_top = sl_views.SIDEBAR_LIST_TOP
        track_x, track_y = sl_views.SIDEBAR_W - 10, list_top
        track_h = max(0.0, self.display.height_px - 64 - list_top)
        if self.search_expanded:
            # SL-39: the list lives in the docked panel — the thumb/drag
            # geometry tracks the panel's list region, not the vacated rail.
            px, py, pw, ph = sl_views.library_panel_rect(
                self, float(self.display.width_px), float(self.display.height_px))
            track_x = px + pw - 13
            track_y = py + sl_views.PANEL_LIST_TOP
            track_h = max(0.0, ph - sl_views.PANEL_CHIP_H - sl_views.PANEL_LIST_TOP)
        sidebar_update = self.scrollbar_sidebar.update(
            state,
            x=track_x,
            y=track_y,
            width=13,
            height=track_h,
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
            self._publish_content_scroll()
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
        if self.search_expanded:
            # SL-39: wheel over the docked panel scrolls the playlist list;
            # everywhere else (including the vacated left strip) is content.
            px, py, pw, ph = sl_views.library_panel_rect(
                self, float(self.display.width_px), float(self.display.height_px))
            if px <= mx <= px + pw and py <= my <= py + ph:
                self.sidebar_scroll = self._clamp_scroll(
                    self.sidebar_scroll - delta_y, 30.0 * len(self.playlists),
                    ph - sl_views.PANEL_CHIP_H - sl_views.PANEL_LIST_TOP,
                )
            else:
                viewport = self.display.height_px - sl_views.DOCK_H
                self.content_scroll = self._clamp_scroll(
                    self.content_scroll - delta_y, self._content_height, viewport
                )
                self._publish_content_scroll()
                return
            self.invalidate()
            return
        if mx < sl_views.SIDEBAR_W:
            self.sidebar_scroll = self._clamp_scroll(
                self.sidebar_scroll - delta_y, 30.0 * len(self.playlists),
                self.display.height_px - 64 - sl_views.SIDEBAR_LIST_TOP,
            )
            self.invalidate()
            return
        viewport = self.display.height_px - sl_views.DOCK_H
        self.content_scroll = self._clamp_scroll(
            self.content_scroll - delta_y, self._content_height, viewport
        )
        self._publish_content_scroll()

    def _publish_content_scroll(self) -> None:
        """Content offset moved (wheel / scrollbar drag). Band mode: the
        gesture's first visible tick ENGAGES the band with one banded
        rebuild; streak ticks publish transform-only; the settle render
        disengages back to a bandless resting frame. Clamped boundary ticks
        and sub-pixel jitter publish nothing — they must not churn renders
        or presents (round 67 idle-churn finding). Legacy targets re-render
        per tick as today."""
        if not self._band_mode():
            self.invalidate()
            return
        now = time.monotonic()
        if not self._band_engaged:
            if abs(self.content_scroll - self._last_scroll_published) < 0.1:
                return  # clamped / sub-pixel noise: nothing visible to show
            self._band_engaged = True
            self._scroll_settle_due = now + SCROLL_SETTLE_S
            self.invalidate()  # no banded frame exists yet: rebuild, then streak
            return
        if abs(self.content_scroll - self._last_scroll_published) < 0.1:
            return  # boundary wiggle mid-gesture: nothing new to publish
        self._scroll_settle_due = now + SCROLL_SETTLE_S
        if now - self._last_scroll_build_t >= SCROLL_REWINDOW_INTERVAL_S:
            self.invalidate()  # throttle window elapsed: rebuild the draw window
            return
        if self.ctx.set_scene_content_offset(0.0, self.content_scroll) is None:
            self.invalidate()  # no retained frame to transform yet
        else:
            self._last_scroll_published = self.content_scroll

    @staticmethod
    def _clamp_scroll(value: float, content: float, viewport: float) -> float:
        max_offset = max(0.0, content - viewport)
        return max(0.0, min(value, max_offset))

    def _dispatch_click(self, x: float, y: float) -> None:
        # Banded renders record content hits in content space; map the live
        # scroll offset onto the click so mid-gesture taps still land
        # (SL-41). The recorded frame's own coordinate space decides — a
        # click landing between an engage scroll tick and its rebuild must
        # not mis-map. Chrome regions stay screen-space. Legacy: identical.
        scroll = self.content_scroll if self._hits_content_space else 0.0
        for region in reversed(self._hits):
            hit_y = y + scroll if region.scrollable else y
            if region.contains(x, hit_y):
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

    def _expand_search(self) -> None:
        """SL-39: the search circle's click docks the library panel and grows
        the field. The content view switches to search so the existing flow's
        results keep the stage; the view we came from is remembered for the
        dismiss affordance."""
        if not self.search_expanded:
            self._search_pre_expand_view = self.view if self.view != "search" else "home"
        self.search_expanded = True
        self.search_focused = True
        self.client_id_focused = False
        self.view = "search"

    def _collapse_search(self, *, restore: bool) -> None:
        if restore:
            self.view = self._search_pre_expand_view
        self.search_expanded = False
        self.search_focused = False

    def _dispatch_action(self, action: str, payload, click_x: float) -> None:
        if action == "nav":
            if payload == "search":
                self._expand_search()
            else:
                if self.search_expanded:
                    self._collapse_search(restore=False)
                self.view = payload
            self.content_scroll = 0.0
            self.show_devices = False
            self.invalidate()
        elif action == "open_playlist":
            if self.search_expanded:
                # Picking from the docked library leaves search: collapse the
                # cluster and let the navigation below own the view.
                self._collapse_search(restore=False)
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
            if (self.show_devices and self.authenticated and self._client is not None
                    and time.monotonic() >= self._rate_limited_until):
                # Popup open is a devices trigger, not a player poll.
                self.worker.submit("poll-devices", self._job_poll_devices)
            self.invalidate()
        elif action == "pick_device":
            _transfer = lambda c: c.transfer(payload, play=True)  # noqa: E731
            # An explicit pick that fails must not auto-transfer elsewhere.
            _transfer._sl_device_retry = True  # type: ignore[attr-defined]
            self._player_action(_transfer)
            self.show_devices = False
        elif action == "focus_search":
            self.search_focused = True
            self.client_id_focused = False
            self.invalidate()
        elif action == "close_search":
            # SL-39 dismiss: the cap where the circle was restores the prior
            # layout — left rail back, view back to what search covered.
            self._collapse_search(restore=True)
            self.content_scroll = 0.0
            self.invalidate()
        elif action == "panel_plate":
            pass  # swallowed: dead panel space must not dismiss or blur
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
        elif action == "popup_plate":
            pass  # swallowed: clicking the panel must not dismiss it
        elif action == "scrollbar":
            pass  # handled by ScrollbarController.update above

    def _player_action(self, fn) -> None:
        if self._client is None:
            self._toast("Connect Spotify first")
            return
        self._last_player_action = fn
        self.worker.submit("player-action", lambda: self._job_player_action(fn))
        self._next_player_poll = time.monotonic() + POLL_AFTER_ACTION_SECS
        if time.monotonic() >= self._rate_limited_until:
            # Device reality may change with an action (transfer, wake); the
            # devices list rides actions, not the player tick.
            self.worker.submit("poll-devices", self._job_poll_devices)
        self.invalidate()

    def _auto_pick_device(self) -> bool:
        """Transfer to the obvious device and re-issue the failed action.

        The real Spotify app never asks which device to use when the answer
        is obvious: the active one, or the only one there is. Returns True
        when a transfer+retry was queued. A retry that itself failed is
        marked and never chains another, and an explicit pick_device
        transfer is marked too (it must not auto-transfer elsewhere).
        """
        action = self._last_player_action
        if action is None or getattr(action, "_sl_device_retry", False):
            return False
        active = [d for d in self.devices if d.is_active]
        if len(active) == 1:
            target = active[0]
        elif len(self.devices) == 1:
            target = self.devices[0]
        else:
            return False

        def _retry(client, _action=action, _device_id=target.id):
            client.transfer(_device_id, play=False)
            _action(client)

        _retry._sl_device_retry = True  # type: ignore[attr-defined]
        self._player_action(_retry)
        self._toast(f"No active device — switching to {target.name}")
        return True

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
                if self.search_expanded:
                    self._collapse_search(restore=True)
                else:
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

    def _pre_staged(self) -> bool:
        """True when the wall clock has run past the current track's end and
        the queue head is known — the pill shows the next track while the
        boundary poll is still in flight."""
        return bool(
            self.player and self.player.is_playing and self.player.track
            and self.up_next is not None
            and self.progress_ms_unstaged() >= self.player.track.duration_ms)

    def progress_ms_unstaged(self) -> int:
        if self.player is None:
            return 0
        duration = self.player.track.duration_ms if self.player.track else 0
        return sl_ui.interpolate_progress(
            base_ms=self.player.progress_ms,
            base_monotonic=self._player_synced_at,
            duration_ms=duration,
            playing=self.player.is_playing,
        )

    def progress_ms(self) -> int:
        if self._pre_staged():
            return 0
        return self.progress_ms_unstaged()

    def displayed_track(self):
        """Track the pill should show: the queue head once the current track's
        wall-clock duration has run out, otherwise the polled track."""
        if self._pre_staged():
            return self.up_next
        return self.player.track if self.player else None

    # -- native controls -------------------------------------------------------------

    def _sync_glass_surfaces(self, width: float, height: float, *,
                             want_login_field: bool,
                             want_save_button: bool = False,
                             want_connect_button: bool = False,
                             want_pill: bool = False,
                             want_backdrop: bool = False) -> None:
        """Create/update/destroy app-declared glass regions to match the layout.

        Login-wall capsules sit ABOVE the Metal layer behind native content.
        The pill plate (SL-36) sits UNDER it — scene glyphs stay crisp — and
        tracks the resolved pill rect and silhouette radius every frame,
        since layout nudges and the big-pill size rule move both.
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
            if want_pill:
                px, py, pw, ph = sl_views._layout(
                    self, "pill", sl_views.pill_rect(width, height), width, height)
                wanted["pill"] = dict(x=px, y=py, width=pw, height=ph,
                                      corner_radius=sl_views.glass_silhouette_radius(ph),
                                      style="regular", placement="under")
                self._pill_glass_rect = (px, py, pw, ph)
            if want_backdrop:
                # SL-38: one window-spanning behind-window material at the
                # very back — the scene's only base once it exists.
                wanted["backdrop"] = dict(x=0.0, y=0.0, width=width, height=height,
                                          corner_radius=0.0, style="regular",
                                          placement="backdrop")
        for key in list(self._glass_surfaces):
            if key not in wanted:
                self._glass_surfaces.pop(key).destroy()
                self._glass_specs.pop(key, None)
        for key, spec in wanted.items():
            surface = self._glass_surfaces.get(key)
            if surface is None:
                try:
                    self._glass_surfaces[key] = bridge.create_glass_surface(**spec)
                except RuntimeError as exc:
                    # Never let a native-plate failure hole the frame: latch
                    # off and fall back to the drawn plate next frame.
                    print(f"[spotify-light] glass surface {key!r} failed: {exc}",
                          file=sys.stderr, flush=True)
                    if key == "pill":
                        self._pill_glass_disabled = True
                    elif key == "backdrop":
                        self._backdrop_disabled = True
                    continue
            else:
                # Always re-apply: the bridge derives the AppKit frame from the
                # content view's current bounds, which can change under an
                # unchanged logical frame (window resize). Early-outing here
                # baked a stale offset into the native plate.
                surface.set_frame(spec["x"], spec["y"], spec["width"], spec["height"])
                prev = self._glass_specs.get(key) or {}
                if (spec.get("corner_radius") != prev.get("corner_radius")
                        and hasattr(surface, "set_corner_radius")):
                    surface.set_corner_radius(spec["corner_radius"])
            self._glass_specs[key] = spec

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
            "search_expanded": self.search_expanded,
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
            {
                "name": "layout_set",
                "description": (
                    "Move a chrome component on the running app — and persist it: the spec "
                    "is written through to the app's layout.toml, so the position survives "
                    "restart. Pass 'id' plus exactly one shape: 'rect' ({x, y, width, "
                    "height}) or 'anchor' (top-left/top-right/bottom-left/bottom-right/"
                    "center) with dx/dy offsets and optional width/height. Anchor offsets "
                    "measure inward from that window corner (or from the pill's corner for "
                    "interior ids); right/bottom anchors re-resolve when the window "
                    "resizes, so prefer them over raw rects. Rects clamp into the window. "
                    "Valid ids: pill, nav_home, nav_search, nav_more, sidebar — plus the "
                    "pill's interior in PILL-LOCAL space ((0,0) is the pill's top-left, "
                    "rects and anchors clamp into the pill, locals ride whole-pill moves): "
                    "pill.art (square tile, min(width,height)), pill.title (the "
                    "title/artist text column — the strip's alignment reference), "
                    "pill.progress (x/width; the time labels ride above the strip's "
                    "ends), pill.transport (positions by the rect's center; the 34pt "
                    "hits are fixed)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "anchor": {"type": "string"},
                        "dx": {"type": "number"},
                        "dy": {"type": "number"},
                        "width": {"type": "number"},
                        "height": {"type": "number"},
                        "rect": {"type": "object"},
                    },
                    "required": ["id"],
                },
            },
            {
                "name": "layout_align",
                "description": (
                    "Align one edge of a component to an edge of another component's "
                    "CURRENT rect (natural or overridden) — and persist the "
                    "RELATIONSHIP: the layout file gains an align spec that re-resolves "
                    "at layout time, so the edge tracks the reference if the reference "
                    "later moves, and the geometry stays resize-safe. Params: 'id', "
                    "'edge' (left/right/top/bottom/center_x/center_y), 'to' (reference "
                    "id), 'ref_edge' (defaults to edge), 'offset' in points (default "
                    "0, shifts the aligned edge along its axis), 'keep' ('size' makes "
                    "an edge rule a POSITION move — the named edge meets the reference "
                    "line and the extent holds — instead of the default, which keeps "
                    "the opposite edge fixed and changes the extent; center rules "
                    "always keep the size). Calls UPSERT one rule per axis: a second "
                    "call on the other axis adds to the relationship (two rules max), "
                    "a same-axis call replaces its rule, and any rect/anchor spec on "
                    "the id is replaced by the align form. References stay in one "
                    "frame: interior ids reference interior ids (or the pill frame "
                    "itself as 'pill'), window ids reference window ids. Examples — "
                    "SL-21: {id: \"pill.progress\", edge: \"left\", to: \"pill.title\", "
                    "ref_edge: \"left\"} pins the progress strip to the text column. "
                    "To move a component INSIDE another (SL-26 merged the overflow "
                    "circle into the pill), use layout_attach instead — containment "
                    "is its own relationship form."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "edge": {"type": "string"},
                        "to": {"type": "string"},
                        "ref_edge": {"type": "string"},
                        "offset": {"type": "number"},
                        "keep": {"type": "string"},
                    },
                    "required": ["id", "edge", "to"],
                },
            },
            {
                "name": "layout_attach",
                "description": (
                    "Attach a window-space component INTO a container at a named "
                    "slot — and persist the RELATIONSHIP: the layout file gains an "
                    "attach spec (id, container, slot, inset) that re-resolves at "
                    "layout time, so the component switches to container-local "
                    "space, rides the container like the pill's interior ids, "
                    "keeps its size, and stays resize-safe (never raw pixels). "
                    "Params: 'id', 'container', 'slot' (top-right/top-left/"
                    "bottom-right/bottom-left), 'inset' in points (default 0, "
                    "measured inward from the container's corner). The slot's "
                    "occupied region is queryable by the container's own layout: "
                    "the pill's text column yields a top-right attachment "
                    "(title/artist/bar narrow left of it). layout_clear detaches "
                    "back to the window-space natural; a rect/anchor spec "
                    "replaces the attachment. Validation rejects self-attach, "
                    "cycles, unknown containers, and unknown slots; the rect "
                    "clamps inside the container. Example — SL-26: {id: "
                    "\"nav_more\", container: \"pill\", slot: \"top-right\", "
                    "inset: 12} merges the overflow button into the pill's "
                    "top-right corner."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "container": {"type": "string"},
                        "slot": {"type": "string"},
                        "inset": {"type": "number"},
                    },
                    "required": ["id", "container", "slot"],
                },
            },
            {
                "name": "layout_list",
                "description": "List the valid layout ids and every active override with its resolved rect.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "layout_clear",
                "description": (
                    "Clear one override ('id') or, with no id, all of them; returns the "
                    "cleared ids. Also persists: the component's code natural returns and "
                    "survives restart."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                },
            },
            {
                "name": "layout_export",
                "description": (
                    "Dump the current overrides as JSON (specs + rects resolved at the "
                    "current window size) for inspection. Positions already persist via "
                    "layout_set; this is a read-only view."
                ),
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "effect_apply",
                "description": (
                    "Add or tune a visual effect on the running app — and persist it: the "
                    "spec writes through to the app's layout.toml as an effect table, so the "
                    "band survives restart. The one kind today is 'scrim' (default): a solid "
                    "backdrop band in from an 'edge' (top/bottom/left/right), then a smoothstep "
                    "fade. 'height' is the total thickness in points (band + fade), 'fade' the "
                    "gradient length (0 to height), 'alpha' the band opacity (0-255), 'margin' "
                    "an inset along the band's long axis (x for top/bottom edges, y for "
                    "left/right; 240 keeps a top/bottom scrim off the sidebar). A partial call "
                    "on an existing id TUNES — omitted knobs keep their stored values, e.g. "
                    "{id: \"scrim.dock\", alpha: 120} dims a dock dissolve. New ids need "
                    "edge + height. Nothing ships declared: both stock scrims were removed "
                    "(SL-33/SL-35), so effects exist only when applied live — recreate the old "
                    "dock idiom with {id: \"scrim.dock\", edge: \"bottom\", height: 148, "
                    "fade: 56, alpha: 240, margin: 240}. effect_remove deletes; "
                    "effect_list inspects."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "kind": {"type": "string"},
                        "edge": {"type": "string"},
                        "height": {"type": "number"},
                        "fade": {"type": "number"},
                        "alpha": {"type": "number"},
                        "margin": {"type": "number"},
                    },
                    "required": ["id"],
                },
            },
            {
                "name": "effect_remove",
                "description": (
                    "Remove a declared effect by id (all effects when id is omitted) and "
                    "persist the removal — the band disappears on the next frame and the "
                    "layout file drops the table."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                },
            },
            {
                "name": "effect_list",
                "description": (
                    "List the declared effects with their stored specs and each scrim's "
                    "region resolved at the current window size. Read-only."
                ),
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
        if name == "layout_set":
            args = dict(arguments or {})
            cid = sl_layout._check_id(args.get("id"))
            before = self.layout_overrides.specs()
            stored = self.layout_overrides.set(cid, args)
            self._persist_specs(before, self.effect_specs.specs())
            self.invalidate()
            width, height = self._window_size()
            return {"id": cid, "spec": stored, "persisted": True,
                    "rect": list(self._resolve_layout_rect(cid, width, height))}
        if name == "layout_align":
            args = dict(arguments or {})
            cid = sl_layout._check_id(args.get("id"))
            rule = {
                "edge": args.get("edge"),
                "to": args.get("to"),
                "ref_edge": args.get("ref_edge", args.get("edge")),
                "offset": args.get("offset", 0.0),
            }
            if "keep" in args:
                rule["keep"] = args["keep"]
            before = self.layout_overrides.specs()
            stored = self.layout_overrides.set_align(cid, rule)
            self._persist_specs(before, self.effect_specs.specs())
            self.invalidate()
            width, height = self._window_size()
            return {"id": cid, "spec": stored, "persisted": True,
                    "rect": list(self._resolve_layout_rect(cid, width, height))}
        if name == "layout_attach":
            args = dict(arguments or {})
            cid = sl_layout._check_id(args.get("id"))
            spec = {"attach": {
                "container": args.get("container"),
                "slot": args.get("slot"),
                "inset": args.get("inset", 0.0),
            }}
            before = self.layout_overrides.specs()
            stored = self.layout_overrides.set(cid, spec)
            self._persist_specs(before, self.effect_specs.specs())
            self.invalidate()
            width, height = self._window_size()
            return {"id": cid, "spec": stored, "persisted": True,
                    "rect": list(self._resolve_layout_rect(cid, width, height))}
        if name == "layout_list":
            width, height = self._window_size()
            return {
                "valid_ids": list(sl_layout.COMPONENT_IDS),
                "overrides": [
                    {"id": cid, "spec": spec,
                     "rect": list(self._resolve_layout_rect(cid, width, height))}
                    for cid, spec in sorted(self.layout_overrides.specs().items())
                ],
            }
        if name == "layout_clear":
            before = self.layout_overrides.specs()
            cleared = self.layout_overrides.clear((arguments or {}).get("id"))
            if cleared:
                self._persist_specs(before, self.effect_specs.specs())
                self.invalidate()
            return {"cleared": cleared}
        if name == "layout_export":
            width, height = self._window_size()
            _, _, pw, ph = self._resolved_pill_rect(width, height)
            naturals = self._layout_naturals(width, height)
            naturals.update(self._interior_naturals(pw, ph, width, height))
            frames = {iid: (pw, ph) for iid in sl_layout.INTERIOR_IDS}
            return self.layout_overrides.export(width=width, height=height,
                                                naturals=naturals, local_frames=frames)
        if name == "effect_apply":
            args = dict(arguments or {})
            eid = sl_layout._check_effect_id(args.pop("id", None))
            before = self.layout_overrides.specs()
            before_fx = self.effect_specs.specs()
            stored = self.effect_specs.set(eid, args)
            self._persist_specs(before, before_fx)
            self.invalidate()
            width, height = self._window_size()
            return {"id": eid, "spec": stored, "persisted": True,
                    "rect": list(self._resolve_effect_rect(stored, width, height))}
        if name == "effect_remove":
            before = self.layout_overrides.specs()
            before_fx = self.effect_specs.specs()
            cleared = self.effect_specs.clear((arguments or {}).get("id"))
            if cleared:
                self._persist_specs(before, before_fx)
                self.invalidate()
            return {"cleared": cleared}
        if name == "effect_list":
            width, height = self._window_size()
            specs = self.effect_specs.specs()
            return {
                "effects": [
                    {"id": eid, "spec": specs[eid],
                     "rect": list(self._resolve_effect_rect(specs[eid], width, height))}
                    for eid in sorted(specs)
                ],
            }
        raise KeyError(name)

    def _window_size(self) -> tuple[float, float]:
        return float(self.ctx.display_width_px), float(self.ctx.display_height_px)

    def _persist_specs(self, before_layout: dict, before_effects: dict) -> None:
        """Write BOTH registries through to the layout file (round 36, SL-34)
        — layout specs and effect tables share it. A failed write rolls both
        back and errors the tool call: a change that cannot persist must not
        pretend it did."""
        try:
            sl_layout.save(self.layout_overrides.specs(), sl_layout.default_path(),
                           effects=self.effect_specs.specs())
        except OSError as exc:
            self.layout_overrides = sl_layout.LayoutOverrides()
            for cid, spec in before_layout.items():
                self.layout_overrides.set(cid, spec)
            self.effect_specs = sl_layout.EffectSpecs()
            for eid, spec in before_effects.items():
                self.effect_specs.set(eid, spec)
            raise sl_layout.LayoutError(f"could not persist layout: {exc}") from exc

    @staticmethod
    def _resolve_effect_rect(spec: dict, width: float, height: float) -> tuple:
        """The window-space region a scrim spec covers at this window size."""
        total, margin = spec["height"], spec["margin"]
        edge = spec["edge"]
        if edge == "bottom":
            return (margin, height - total, width - margin, total)
        if edge == "top":
            return (margin, 0.0, width - margin, total)
        if edge == "left":
            return (0.0, margin, total, height - margin)
        return (width - total, margin, total, height - margin)

    def _resolved_pill_rect(self, width: float, height: float) -> tuple[float, float, float, float]:
        """The pill's rect with its own override applied — the frame the
        interior ids (pill.art/pill.progress/pill.transport) resolve inside."""
        return self.layout_overrides.resolve("pill", sl_views.pill_rect(width, height),
                                             width=width, height=height)

    def _interior_naturals(self, pw: float, ph: float,
                           width: float, height: float) -> dict:
        """Interior natural rects in PILL-LOCAL space at a pill size — the
        text column narrowed when an attachment occupies the pill's
        top-right slot (round 41, SL-27)."""
        reserve = sl_views.pill_slot_reserve_right(self, pw, ph, width, height)
        return sl_views.pill_frame_naturals(pw, ph, reserve_right=reserve)

    def _resolve_layout_rect(self, cid: str, width: float, height: float) -> tuple:
        """One resolution path for set/list: window ids resolve against the
        window; interior ids resolve in pill-local space against the pill's
        current (override-aware) rect, and report local coordinates. The
        frame's naturals map comes along so align specs can see their
        reference (round 37)."""
        if cid in sl_layout.INTERIOR_IDS:
            _, _, pw, ph = self._resolved_pill_rect(width, height)
            return self.layout_overrides.resolve(
                cid, self._interior_naturals(pw, ph, width, height)[cid],
                width=pw, height=ph,
                naturals=self._interior_naturals(pw, ph, width, height))
        naturals = self._layout_naturals(width, height)
        return self.layout_overrides.resolve(cid, naturals[cid], width=width,
                                             height=height, naturals=naturals)

    def _layout_naturals(self, width: float, height: float) -> dict:
        """Natural chrome rects at a window size — the layout the overrides sit on top of."""
        return sl_views.window_naturals(width, height)

    # -- app loop ---------------------------------------------------------------------

    @staticmethod
    def _pure_scroll_batch(events) -> bool:
        return bool(events) and all(getattr(e, "event_type", None) == "scroll" for e in events)

    def update(self, dt: float) -> None:
        events = self.input.raw_events()
        reset_transient_input(self.input.state)
        apply_hdi_events(self.input.state, events)
        if events and not (self._pure_scroll_batch(events) and self._band_mode()):
            # Band-mode wheel ticks publish the offset themselves
            # (transform-only, throttled re-window, settle render); every
            # other input invalidates as today.
            self.invalidate()
        self._handle_input(events)
        self._handle_worker_results()
        self._pump_web_playback()
        self._handle_timers()

    def _pill_glass_supported(self) -> bool:
        """Under-glass pill prerequisites: authed chrome on a window whose
        presenter can composite see-through (SL-36). Anything less — logged
        out, bridgeless, Vulkan, pre-Tahoe, or a failed creation — keeps the
        simulated plate and the opaque clear."""
        if not self.authenticated or self._pill_glass_disabled:
            return False
        return self._under_glass_capable()

    def _under_glass_capable(self) -> bool:
        bridge = native_controls()
        return bool(self.authenticated and bridge is not None and bridge.available
                    and getattr(bridge, "supports_under_glass", False))

    def _band_mode(self) -> bool:
        """SL-41 retained scroll hot path: only when the scene target can
        split the frame on a z band (content 1..4 scrolls by transform;
        chrome at 0 and 5+ stays put). Legacy targets keep translated draws."""
        return bool(self.ctx.supports_scene_graph
                    and getattr(self.ctx, "supports_scene_content_z_band", False))

    def render(self) -> None:
        self._pill_glass_active = self._pill_glass_supported()
        self._window_material_active = (self._under_glass_capable()
                                        and not self._backdrop_disabled)
        # Fully transparent clear is the presenter's cue to make the window
        # see-through — for the under-glass pill zone (SL-36) and the
        # whole-window material (SL-38). While the material is live the scene
        # paints no opaque base at all; the SL-36 tiles only backstop a
        # failed backdrop.
        clear = ((0, 0, 0, 0) if (self._pill_glass_active or self._window_material_active)
                 else sl_views.BG)
        if self.ctx.supports_scene_graph:
            if self._band_mode() and self._band_engaged:
                # Content lives at z 1..4 and draws un-translated; the target
                # applies content_offset as a transform on that band only.
                with self.scene_frame(clear=clear, retained=True,
                                      content_offset=(0.0, self.content_scroll),
                                      content_z_band=(1.0, 4.0)) as frame:
                    self._render_scene(frame)
            else:
                with self.scene_frame(clear=clear) as frame:
                    self._render_scene(frame)
        else:
            with self.matrix_frame(clear=clear) as frame:
                self._render_matrix(frame)

    def _render_scene(self, frame) -> None:
        width = float(self.ctx.display_width_px)
        height = float(self.ctx.display_height_px)
        out = sl_views.FrameOut()
        mouse = self._mouse
        banded = self._band_mode() and self._band_engaged
        self._render_scroll_sub = 0.0 if banded else self.content_scroll
        self._hits_content_space = banded
        self._last_scroll_published = self.content_scroll
        if banded:
            # Content draws in content space under the band: cull one window
            # of margin around the live scroll so off-screen cards/rows never
            # enter the frame, and give content views a content-space mouse
            # so hover keeps working mid-gesture. Chrome stays screen-space.
            self._render_cull_lo = self.content_scroll - height
            self._render_cull_hi = self.content_scroll + 2.0 * height
            self._last_scroll_build_t = time.monotonic()
            content_mouse = (mouse[0], mouse[1] + self.content_scroll)
        else:
            self._render_cull_lo = 0.0
            self._render_cull_hi = height
            content_mouse = mouse

        if not self.authenticated:
            bridge = native_controls()
            bridge_up = bridge is not None and bridge.available
            self.glass_active = False  # chrome glass is an authed-only concern
            self._pill_glass_live = False
            self._window_material_live = False
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
            self._sync_glass_surfaces(width, height, want_login_field=False,
                                      want_pill=self._pill_glass_active,
                                      want_backdrop=self._window_material_active)
            self._pill_glass_live = "pill" in self._glass_surfaces
            self._window_material_live = "backdrop" in self._glass_surfaces
            if (self._pill_glass_live and self._pill_glass_rect is not None
                    and not self._window_material_live):
                # Opaque base everywhere but the glass zone: the clear is
                # transparent now, so the window's near-black must come from
                # the scene — content still floats over the real material.
                # SL-38: only a backstop for a failed backdrop creation;
                # once the window material is live it IS the base.
                sl_views.draw_window_backdrop(frame, width=width, height=height,
                                              skip=self._pill_glass_rect)
            if self.view == "search":
                sl_views.draw_search(frame, self, out, width=width, height=height,
                                     mouse=content_mouse)
            elif self.view.startswith("playlist:"):
                sl_views.draw_playlist(frame, self, out, width=width, height=height,
                                       mouse=content_mouse)
            elif self.view == "library":
                sl_views.draw_library(frame, self, out, width=width, height=height,
                                      mouse=content_mouse)
            else:
                sl_views.draw_home(frame, self, out, width=width, height=height,
                                   mouse=content_mouse)

            # Content-area scrollbar for tall views. The extent publishes
            # right after the view draw (not at end-of-render) so the very
            # first frame of a tall view already carries an honest thumb.
            self._content_height = out.content_height
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

            effects = self.effect_specs.specs()
            sl_views.draw_scrims(frame, [effects[eid] for eid in sorted(effects)],
                                 width=width, height=height)
            # SL-39: expanded, the library component docks right-aligned above
            # the grown search field instead of drawing as the left rail. The
            # cluster draws before the player bar so the z=20 playback popup
            # keeps winning both the paint and the hit walk where they meet.
            if self.search_expanded:
                sl_views.draw_search_expansion(frame, self, out, width=width,
                                               height=height, mouse=mouse)
            else:
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
        self._glass_specs.clear()
        self.glass_active = False
        self._pill_glass_active = False
        self._pill_glass_live = False
        self._window_material_active = False
        self._window_material_live = False
        if self._login_receiver is not None:
            self._login_receiver.close()
        self.worker.shutdown()


def create() -> SpotifyLightApp:
    return SpotifyLightApp()
