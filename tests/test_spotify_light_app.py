"""Headless integration tests for the Spotify Light app UI (examples/spotify_light).

The app is driven through the real luvatrix runtime (manifest load, lifecycle,
scene frame submission) with a noop HDI source, and the emitted scene nodes
are asserted directly. No network access happens: unauthenticated views never
schedule jobs, and authenticated views are given in-memory state.
"""
from __future__ import annotations

import json
import math
import sys
import threading
import time
import urllib.parse
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "examples" / "spotify_light"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from luvatrix_core.core.app_runtime import AppRuntime  # noqa: E402
from luvatrix_core.core.hdi_thread import HDIEvent, HDIThread  # noqa: E402
from luvatrix_core.core.mcp_runtime import MCP_CAPABILITIES, McpRuntimeBridge  # noqa: E402
from luvatrix_core.core.scene_graph import (  # noqa: E402
    CircleNode,
    ClearNode,
    CpuLayerNode,
    RectNode,
    RoundedRectNode,
    SceneFrame,
    SceneGraphBuffer,
    TextNode,
)
from luvatrix_core.core.scene_rasterizer import rasterize_scene_frame  # noqa: E402
from luvatrix_core.core.sensor_manager import SensorManagerThread  # noqa: E402
from luvatrix_core.core.window_matrix import WindowMatrix  # noqa: E402

import app_main  # noqa: E402
import sl_api  # noqa: E402
import sl_art  # noqa: E402
import sl_layout  # noqa: E402
import sl_models  # noqa: E402
import sl_oauth  # noqa: E402
import sl_icons  # noqa: E402
import sl_store  # noqa: E402
import sl_ui  # noqa: E402
import sl_views  # noqa: E402

WIDTH, HEIGHT = 1280, 800


class _NoopHDISource:
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        return []


def _runtime(scene_buffer: SceneGraphBuffer) -> AppRuntime:
    # host_os="macos" mirrors the CLI: with a single platform_support entry the
    # headless target platform resolves to macOS even on a Linux host.
    return AppRuntime(
        matrix=WindowMatrix(HEIGHT, WIDTH),  # constructor is (height, width)
        hdi=HDIThread(source=_NoopHDISource()),
        sensor_manager=SensorManagerThread(providers={}),
        scene_buffer=scene_buffer,
        host_os="macos",
    )


def _texts(scene_buffer: SceneGraphBuffer) -> list[str]:
    frame = scene_buffer.latest_frame()
    assert frame is not None
    return [node.text for node in frame.nodes if isinstance(node, TextNode)]


def _nodes(scene_buffer: SceneGraphBuffer, node_type):
    frame = scene_buffer.latest_frame()
    assert frame is not None
    return [node for node in frame.nodes if isinstance(node, node_type)]


def _artist(name: str, suffix: str = "") -> sl_models.Artist:
    return sl_models.Artist(id=f"artist-{name}", name=name, uri=f"spotify:artist:{name}{suffix}")


def _album(name: str, artist: sl_models.Artist) -> sl_models.Album:
    return sl_models.Album(id=f"album-{name}", name=name, uri=f"spotify:album:{name}",
                           artists=(artist,))


def _track(name: str, artist: sl_models.Artist, album: sl_models.Album, *, ms: int = 200_000,
           n: int = 1) -> sl_models.Track:
    return sl_models.Track(id=f"track-{name}", name=name, uri=f"spotify:track:{name}",
                           duration_ms=ms, artists=(artist,), album=album, track_number=n)


def _playlist(name: str, count: int = 3) -> sl_models.Playlist:
    return sl_models.Playlist(id=f"pl-{name}", name=name, uri=f"spotify:playlist:{name}",
                              owner_name="alec", track_count=count)


@pytest.fixture
def app_ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("SPOTIFY_LIGHT_CONFIG_DIR", str(tmp_path))
    # Round 36: boots read the persisted layout file — point it at a tmp
    # copy of the shipped one so specs load but writes never touch the repo.
    layout_file = tmp_path / "layout.toml"
    shipped = getattr(sl_layout, "APP_LAYOUT_FILE", None)
    if shipped is not None and Path(shipped).exists():
        layout_file.write_text(Path(shipped).read_text())
    monkeypatch.setenv("SPOTIFY_LIGHT_LAYOUT_FILE", str(layout_file))
    scene_buffer = SceneGraphBuffer()
    runtime = _runtime(scene_buffer)
    ctx = runtime.build_context({"window.write", "hdi.keyboard", "hdi.mouse", "hdi.trackpad"})
    app = app_main.create()
    app.init(ctx)
    yield app, ctx, scene_buffer
    app.teardown()


def _tick(app, ctx, ticks: int = 1) -> None:
    for _ in range(ticks):
        app.loop(ctx, 1.0 / 60.0)


# ---------------------------------------------------------------------------
# Full runtime path: manifest -> lifecycle -> scene submission
# ---------------------------------------------------------------------------

class TestRuntimeIntegration:
    def test_manifest_loads(self):
        runtime = _runtime(SceneGraphBuffer())
        manifest = runtime.load_manifest(APP_DIR)
        assert manifest.app_id == "examples.spotify_light"
        assert manifest.platform_support == ["macos"]
        resolved = runtime.resolve_variant(APP_DIR, manifest)
        assert resolved.entrypoint == "app_main:create"

    def test_login_view_renders_scene_headless(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPOTIFY_LIGHT_CONFIG_DIR", str(tmp_path))
        scene_buffer = SceneGraphBuffer()
        _runtime(scene_buffer).run(APP_DIR, max_ticks=2, target_fps=1000)

        texts = _texts(scene_buffer)
        assert "Spotify Light" in texts
        # No client id configured yet: the login view walks through setup.
        assert any("developer.spotify.com/dashboard" in t for t in texts)
        assert "Client ID" in texts
        clears = _nodes(scene_buffer, ClearNode)
        assert clears and clears[0].color_rgba == sl_views.BG

    def test_connect_button_once_client_id_saved(self, tmp_path, monkeypatch):
        import sl_store

        monkeypatch.setenv("SPOTIFY_LIGHT_CONFIG_DIR", str(tmp_path))
        sl_store.save_client_id(tmp_path, "test-client-id")
        scene_buffer = SceneGraphBuffer()
        _runtime(scene_buffer).run(APP_DIR, max_ticks=2, target_fps=1000)

        texts = _texts(scene_buffer)
        assert "Connect Spotify" in texts
        assert any("Spotify Connect" in t for t in texts)


# ---------------------------------------------------------------------------
# Authenticated views (state injected; no network)
# ---------------------------------------------------------------------------

class TestHomeView:
    def test_sidebar_sections_cards_and_empty_player(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        artist = _artist("Nirvana")
        album = _album("Nevermind", artist)
        top = _track("Come As You Are", artist, album, ms=218_000)
        app.authenticated = True
        app.profile = sl_models.Profile(id="u1", display_name="Alec", email=None,
                                        image_url=None, product="premium")
        app.playlists = [_playlist("Roadtrip"), _playlist("Focus")]
        app.home_sections = sl_ui.build_home_sections(
            top_tracks=[top], new_releases=[album], playlists=app.playlists, top_artists=[artist],
        )

        _tick(app, ctx, 2)

        texts = _texts(scene_buffer)
        for expected in (
            "Top tracks", "New releases", "Your playlists", "Top artists",
            "Come As You Are", "Nevermind", "Nirvana",
            "Nothing playing", sl_icons.HOME, sl_icons.SEARCH,
        ):
            assert expected in texts, f"missing text: {expected!r}"
        # The library chrome exists only as the search-anchored popup (round
        # 67): no rail chrome texts on the collapsed home. (Playlist NAMES
        # legitimately appear as content cards in "Your playlists".)
        for rail_text in ("Your Library", "PLAYLISTS", "Log out"):
            assert rail_text not in texts, f"rail text leaked into collapsed home: {rail_text!r}"
        assert any(t.startswith("Good ") for t in texts)
        # Album art placeholders land as CpuLayerNode textures.
        assert _nodes(scene_buffer, CpuLayerNode)
        actions = {region.action for region in app._hits}
        assert {"nav", "open_card", "seek_bar",
                "toggle_play", "open_devices"} <= actions
        # Volume lives in the playback popup now (round 8) — hidden until the
        # overflow circle opens it.
        assert "volume_bar" not in actions

        # Expanded: the popup carries the library chrome the rail used to.
        app.search_expanded = True
        app.invalidate()
        _tick(app, ctx, 2)
        texts = _texts(scene_buffer)
        for expected in ("Spotify Light", "Your Library", "PLAYLISTS", "Roadtrip",
                         "Focus", "Alec", "Log out"):
            assert expected in texts, f"missing popup text: {expected!r}"
        actions = {region.action for region in app._hits}
        assert {"open_playlist", "logout"} <= actions

    def test_loading_line_until_bootstrap_completes(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True

        _tick(app, ctx, 2)

        texts = _texts(scene_buffer)
        assert any("Loading your music" in t for t in texts)
        assert app._bootstrap_done is False

    def test_bootstrap_api_error_surfaces_persistent_error(self, app_ctx):
        """Alec's live session: a non-401 bootstrap ApiError landed in a 6s
        toast and vanished, leaving 'Loading your music…' forever. Failures
        must persist as bootstrap_error, not a transient toast."""
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        error = sl_api.ApiError(sl_api.ErrorKind.API, "Insufficient client scope", status=403)

        app._apply_result("bootstrap", error)
        _tick(app, ctx, 2)

        assert "Insufficient client scope" in app.bootstrap_error
        assert app.status_message == ""  # NOT routed through the 6s toast
        assert app._bootstrap_done is True
        texts = _texts(scene_buffer)
        assert any("Insufficient client scope" in t for t in texts)
        assert not any("Loading your music" in t for t in texts)

    def test_bootstrap_oauth_error_surfaces_persistent_error(self, app_ctx):
        """A token-refresh OAuthError inside the bootstrap job must persist
        the same way — it took the same transient-toast path as ApiError."""
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True

        app._apply_result("bootstrap", sl_oauth.OAuthError("token refresh failed"))
        _tick(app, ctx, 2)

        assert "token refresh failed" in app.bootstrap_error
        assert app.status_message == ""
        assert app._bootstrap_done is True
        texts = _texts(scene_buffer)
        assert not any("Loading your music" in t for t in texts)

    def test_bootstrap_unauthorized_still_ends_session(self, app_ctx):
        """A 401 means the token is dead: keep the end-session path (back to
        the wall) rather than surfacing an inline error on the home view."""
        app, ctx, _ = app_ctx
        app.authenticated = True
        error = sl_api.ApiError(sl_api.ErrorKind.UNAUTHORIZED, "Unauthorized", status=401)

        app._apply_result("bootstrap", error)

        assert app.authenticated is False
        assert app._bootstrap_done is True

    def test_bootstrap_empty_library_shows_empty_state(self, app_ctx):
        """Fresh account: bootstrap SUCCEEDS with all-empty data — that is not
        'loading', it is an empty library and must say so."""
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        profile = sl_models.Profile(id="u1", display_name="Alec", email=None,
                                    image_url=None, product="premium")

        app._apply_result("bootstrap", (profile, [], [], [], [], []))
        _tick(app, ctx, 2)

        assert app._bootstrap_done is True
        assert app.home_sections == []
        texts = _texts(scene_buffer)
        assert any("Nothing here yet" in t for t in texts)
        assert not any("Loading your music" in t for t in texts)

    def test_bootstrap_section_403_degrades_to_named_note(self, app_ctx):
        """Spotify dev mode 403s whole endpoint families (Alec's live session):
        one restricted section must not block the rest of the library. The
        section degrades to an inline note NAMING the call; survivors load."""
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        profile = sl_models.Profile(id="u1", display_name="Alec", email=None,
                                    image_url=None, product="premium")
        album = _album("Nevermind", _artist("Nirvana"))

        class _Client:
            def me(self):
                return profile

            def my_playlists(self, *, limit=50):
                return [_playlist("Roadtrip")]

            def top_tracks(self, *, limit=20):
                raise sl_api.ApiError(sl_api.ErrorKind.API, "403: Forbidden", status=403)

            def new_releases(self, *, limit=20):
                return [album]

            def top_artists(self, *, limit=20):
                return []

        app._client = _Client()

        outcome = app._job_bootstrap()  # must NOT raise
        *_, notices = outcome
        # Round 13: notes speak human — the raw "403: Forbidden" goes to the
        # log, not the UI. The note still names the section that degraded.
        assert notices == ["Couldn't load top tracks right now"]

        app._apply_result("bootstrap", outcome)
        _tick(app, ctx, 2)

        assert app._bootstrap_done is True
        assert app.bootstrap_error == ""  # partial degradation is not a library failure
        texts = _texts(scene_buffer)
        assert any("Couldn't load top tracks right now" in t for t in texts)
        assert not any("403" in t or "Forbidden" in t for t in texts)
        assert "New releases" in texts  # surviving section still renders
        assert "Nevermind" in texts
        assert "Top tracks" not in texts  # degraded section title absent
        assert not any("Loading your music" in t for t in texts)

    def test_bootstrap_all_sections_degraded_shows_notes_not_empty_state(self, app_ctx):
        """If EVERY section 403s, the notes explain the empty library — the
        generic 'Nothing here yet' line alone would misread as a fresh account."""
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True

        class _Client:
            def _denied(self, *args, **kwargs):
                raise sl_api.ApiError(sl_api.ErrorKind.API, "403: Forbidden", status=403)

            me = my_playlists = top_tracks = new_releases = top_artists = _denied

        app._client = _Client()

        outcome = app._job_bootstrap()
        *_, notices = outcome
        assert len(notices) == 4  # top_artists degrades silently by design

        app._apply_result("bootstrap", outcome)
        _tick(app, ctx, 2)

        texts = _texts(scene_buffer)
        assert any("Couldn't load profile right now" in t for t in texts)
        assert any("Couldn't load new releases right now" in t for t in texts)
        assert not any("403" in t or "Forbidden" in t for t in texts)
        assert not any("Nothing here yet" in t for t in texts)
        assert not any("Loading your music" in t for t in texts)

    def test_bootstrap_401_wrap_preserves_unauthorized(self, app_ctx):
        """A 401 from any bootstrap call must keep ErrorKind.UNAUTHORIZED so
        the end-session path still fires — naming must not mask it."""
        app, ctx, _ = app_ctx

        class _Client:
            def me(self):
                raise sl_api.ApiError(sl_api.ErrorKind.UNAUTHORIZED, "401", status=401)

        app._client = _Client()

        with pytest.raises(sl_api.ApiError) as excinfo:
            app._job_bootstrap()
        assert "profile" in str(excinfo.value)
        assert excinfo.value.kind == sl_api.ErrorKind.UNAUTHORIZED

        app._apply_result("bootstrap", excinfo.value)
        assert app.authenticated is False  # end-session path intact

    def test_render_on_invalidation_only(self, app_ctx):
        app, ctx, _ = app_ctx
        assert app._continuous_render is False
        _tick(app, ctx, 1)
        assert app._render_requested is False
        app.invalidate()
        assert app._render_requested is True


class TestPlaylistView:
    def test_track_table_and_now_playing_highlight(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        artist = _artist("Nirvana")
        album = _album("Nevermind", artist)
        playing_track = _track("Lithium", artist, album, ms=257_000)
        tracks = [_track("Smells Like Teen Spirit", artist, album, ms=301_000), playing_track]
        playlist = _playlist("Roadtrip", count=2)
        device = sl_models.Device(id="d1", name="MacBook Pro", kind="Computer", is_active=True,
                                  is_restricted=False, volume_percent=65)
        app.authenticated = True
        app.playlists = [playlist]
        app.view = "playlist:pl-Roadtrip"
        app.playlist_detail = (playlist, tracks)
        app.player = sl_models.PlayerState(is_playing=True, progress_ms=61_000,
                                           track=playing_track, device=device,
                                           shuffle=False, repeat="off")
        app._player_synced_at = app.now_monotonic
        # Round 8: the device name lives in the playback popup (overflow
        # circle), not on the pill itself.
        app.devices = [device]
        app.show_devices = True

        _tick(app, ctx, 2)

        texts = _texts(scene_buffer)
        for expected in ("PLAYLIST", "Roadtrip", "Play", "Title", "Album", "Time",
                         "Smells Like Teen Spirit", "Lithium", "5:01", "4:17",
                         "MacBook Pro"):
            assert expected in texts, f"missing text: {expected!r}"
        # The playing track's row is highlighted in the accent color.
        assert any(
            node.text == "Lithium" and node.color_rgba == sl_views.ACCENT
            for node in _nodes(scene_buffer, TextNode)
        )
        actions = {region.action for region in app._hits}
        assert {"play_context", "play_track_in_context"} <= actions


class TestPlaylistErrorState:
    """Live Mac session (round 13): every playlist open 403'd and the view sat
    on "Loading playlist…" forever — the failure only produced a 6s toast with
    raw "403: Forbidden". A failed playlist load must land as a persistent
    inline error with a way to retry, the same contract bootstrap got."""

    def _open(self, app):
        app.authenticated = True
        playlist = _playlist("breaks")
        app.playlists = [playlist]
        app.view = f"playlist:{playlist.id}"
        return playlist

    def test_api_error_shows_inline_state_not_eternal_loading(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        playlist = self._open(app)
        error = sl_api.ApiError(sl_api.ErrorKind.API, "403: Forbidden", status=403)

        app._apply_result(f"playlist:{playlist.id}", error)
        _tick(app, ctx, 2)

        assert app.playlist_error
        assert app.status_message == ""  # inline state, not a vanishing toast
        texts = _texts(scene_buffer)
        assert any("Couldn't load this playlist" in t for t in texts)
        assert not any("Loading playlist" in t for t in texts)
        actions = {region.action for region in app._hits}
        assert "retry_playlist" in actions

    def test_generic_exception_also_shows_inline_state(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        playlist = self._open(app)

        app._apply_result(f"playlist:{playlist.id}", RuntimeError("connection reset"))
        _tick(app, ctx, 2)

        assert app.playlist_error
        texts = _texts(scene_buffer)
        assert any("Couldn't load this playlist" in t for t in texts)
        assert not any("Loading playlist" in t for t in texts)

    def test_retry_clears_error_and_resubmits(self, app_ctx, monkeypatch):
        app, ctx, scene_buffer = app_ctx
        playlist = self._open(app)
        app._apply_result(f"playlist:{playlist.id}",
                          sl_api.ApiError(sl_api.ErrorKind.API, "403: Forbidden", status=403))
        _tick(app, ctx, 2)
        submitted = []
        monkeypatch.setattr(app.worker, "submit", lambda label, fn: submitted.append(label))

        retry = next(r for r in app._hits if r.action == "retry_playlist")
        app._dispatch_action("retry_playlist", retry.payload, 0)
        _tick(app, ctx, 2)

        assert app.playlist_error == ""
        assert submitted == [f"playlist:{playlist.id}"]
        texts = _texts(scene_buffer)
        assert any("Loading playlist" in t for t in texts)  # loading again is honest now

    def test_open_playlist_clears_prior_error(self, app_ctx, monkeypatch):
        app, ctx, _ = app_ctx
        playlist = self._open(app)
        app.playlist_error = "403: Forbidden"
        monkeypatch.setattr(app.worker, "submit", lambda label, fn: None)

        app._dispatch_action("open_playlist", playlist.id, 0)

        assert app.playlist_error == ""

    def test_success_clears_error(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        playlist = self._open(app)
        app.playlist_error = "403: Forbidden"
        tracks = [_track("Lithium", _artist("Nirvana"), _album("Nevermind", _artist("Nirvana")))]

        app._apply_result(f"playlist:{playlist.id}", (playlist, tracks))
        _tick(app, ctx, 2)

        assert app.playlist_error == ""
        assert app.playlist_detail == (playlist, tracks)
        texts = _texts(scene_buffer)
        assert "Lithium" in texts

    def test_unauthorized_still_ends_session_not_inline(self, app_ctx):
        app, ctx, _ = app_ctx
        playlist = self._open(app)
        error = sl_api.ApiError(sl_api.ErrorKind.UNAUTHORIZED, "Unauthorized", status=401)

        app._apply_result(f"playlist:{playlist.id}", error)

        assert app.authenticated is False


class TestSansTypography:
    """The whole UI rendered in the renderer's monospace default because the
    public frame API exposed no font family. Spotify Light is a music app,
    not a terminal: every scene text node the app emits must use its chosen
    sans family, on every view. Dock/card icons are the one exception: they
    use the bundled Phosphor families (see sl_icons)."""

    def _assert_typography(self, scene_buffer) -> None:
        icon_chars = {ch for ch, _ in sl_icons.GLYPHS.values()}
        icon_fonts = {sl_icons.ICON_FONT, sl_icons.ICON_FONT_FILL}
        for node in _nodes(scene_buffer, TextNode):
            if node.text in icon_chars:
                assert node.font_family in icon_fonts, \
                    f"icon U+{ord(node.text):04X} in {node.font_family!r}"
            else:
                assert node.font_family == sl_views.FONT_FAMILY, \
                    f"prose {node.text!r} in {node.font_family!r}"

    def test_home_view_text_uses_sans_family(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        app._bootstrap_done = True
        _tick(app, ctx, 2)
        self._assert_typography(scene_buffer)

    def test_library_view_text_uses_sans_family(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        app.playlists = [_playlist("breaks")]
        app.view = "library"
        _tick(app, ctx, 2)
        self._assert_typography(scene_buffer)

    def test_search_view_text_uses_sans_family(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        app.view = "search"
        _tick(app, ctx, 2)
        self._assert_typography(scene_buffer)

    def test_playlist_view_text_uses_sans_family(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        playlist = _playlist("breaks", count=1)
        artist = _artist("Nirvana")
        app.authenticated = True
        app.playlists = [playlist]
        app.view = f"playlist:{playlist.id}"
        app.playlist_detail = (playlist, [_track("Lithium", artist, _album("Nevermind", artist))])
        _tick(app, ctx, 2)
        self._assert_typography(scene_buffer)

    def test_login_view_text_uses_sans_family(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        assert app.authenticated is False
        _tick(app, ctx, 2)
        self._assert_typography(scene_buffer)

    def test_toast_text_uses_sans_family(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        app._bootstrap_done = True
        app.status_message = "Saved"
        app._status_until = app.now_monotonic + 60
        _tick(app, ctx, 2)
        self._assert_typography(scene_buffer)
        assert "Saved" in _texts(scene_buffer)

    def test_family_is_a_sans_face(self):
        # Behavior lock: the design choice is a system sans, not another mono.
        assert sl_views.FONT_FAMILY == "Helvetica Neue"


class TestCardPlayButtonGeometry:
    """Hover play button hugged the art's bottom edge (4px) while sitting 16px
    from the right — asymmetric insets read as a mis-placed control. The
    button anchors 16px from BOTH art edges."""

    def test_play_button_inset_is_symmetric(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        artist = _artist("Nirvana")
        album = _album("Nevermind", artist)
        track = _track("Lithium", artist, album)
        app.authenticated = True
        app._bootstrap_done = True
        app.home_sections = sl_ui.build_home_sections(
            top_tracks=[track], new_releases=[], playlists=[], top_artists=[],
        )
        app.view = "home"
        _tick(app, ctx, 2)
        art = next(n for n in _nodes(scene_buffer, CpuLayerNode) if n.width == 156)
        # Hover the centre of the first card by driving the input state the
        # way real HDI pointer events do (the app re-reads it every tick).
        app.input.state.mouse_x = art.x + 78
        app.input.state.mouse_y = art.y + 78
        app.invalidate()
        _tick(app, ctx, 2)

        buttons = [n for n in _nodes(scene_buffer, CircleNode)
                   if tuple(n.fill_rgba) == tuple(sl_views.ACCENT)]
        assert len(buttons) == 1
        button = buttons[0]
        assert button.cx == pytest.approx(art.x + 156 - 16, abs=1.0)
        assert button.cy == pytest.approx(art.y + 156 - 16, abs=1.0)


class TestTransportAndOverflow:
    def test_pause_icon_is_drawn_bars_not_text_pipes(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        artist = _artist("Nirvana")
        track = _track("Lithium", artist, _album("Nevermind", artist))
        device = sl_models.Device(id="d1", name="Mac", kind="Computer", is_active=True,
                                  is_restricted=False, volume_percent=50)
        app.authenticated = True
        app._bootstrap_done = True
        app.player = sl_models.PlayerState(is_playing=True, progress_ms=1000, track=track,
                                           device=device, shuffle=False, repeat="off")
        app._player_synced_at = app.now_monotonic
        _tick(app, ctx, 2)

        assert "||" not in _texts(scene_buffer)
        # Two narrow dark bars inside the pause circle.
        circles = [n for n in _nodes(scene_buffer, CircleNode)
                   if tuple(n.fill_rgba) == (225, 225, 225, 255)]
        assert len(circles) == 1
        circle = circles[0]
        bars = [n for n in _nodes(scene_buffer, RectNode)
                if tuple(n.color_rgba) == (0, 0, 0, 255)
                and abs((n.x + n.width / 2) - circle.cx) < circle.radius
                and 3 <= n.width <= 6 and 10 <= n.height <= 18]
        assert len(bars) == 2

    def test_paused_icon_still_shows_play_glyph(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        app._bootstrap_done = True
        _tick(app, ctx, 2)
        assert sl_icons.PLAY in _texts(scene_buffer)

    def test_overflow_hit_region_matches_nav_circle_size(self, app_ctx):
        app, ctx, _ = app_ctx
        app.authenticated = True
        app._bootstrap_done = True
        _tick(app, ctx, 2)
        # Pill nav circles are the square "nav" hits (the sidebar's are wide).
        nav = next(r for r in app._hits if r.action == "nav" and r.w == r.h)
        overflow = next(r for r in app._hits if r.action == "open_devices")
        assert (overflow.w, overflow.h) == (nav.w, nav.h)


class TestSearchView:
    def test_caret_tracks_measured_proportional_width(self, app_ctx):
        """Round 15 (live pass on `670b15c`): the caret estimated advance as
        len * size * 0.52, which drifts badly under proportional Helvetica
        Neue (WWWWW ≈ 66pt, not 36). The caret must sit at the measured end
        of the query text."""
        from luvatrix_core.core import font_fallback as ff

        app, _, _ = app_ctx
        app.authenticated = True
        app.search_focused = True
        app.search_query = "WWWWW"
        app.now_monotonic = 0.25  # caret blink phase on

        class _Frame:
            def __init__(self):
                self.rects = []
                self.texts = []

            def rect(self, **kw):
                self.rects.append(kw)

            def text(self, *args, **kw):
                self.texts.append(kw)

            def __getattr__(self, name):
                return lambda *a, **kw: None

        capture = _Frame()
        sl_views.draw_search(capture, app, sl_views.FrameOut(),
                             width=1280, height=800, mouse=None)
        carets = [r for r in capture.rects if r["z_index"] == 4 and r["width"] <= 2.0]
        assert len(carets) == 1, f"expected one caret rect, got {carets}"

        chain = ff.get_font_chain(sl_views.FONT_FAMILY, 14.0)
        expected_w = ff.measure_runs(ff.split_runs(chain, "WWWWW"))[0]
        expected_x = sl_views.CONTENT_PAD + 18 + 2 + expected_w
        assert abs(carets[0]["x"] - expected_x) < 1.0, (
            f"caret x {carets[0]['x']} must track the measured proportional "
            f"width ({expected_x:.1f}), not a mono-width estimate")

    class _Capture:
        def __init__(self):
            self.rects = []
            self.texts = []

        def rect(self, **kw):
            self.rects.append(kw)

        def text(self, *args, **kw):
            kw = dict(kw)
            if args:
                kw["text"] = args[0]
            self.texts.append(kw)

        def __getattr__(self, name):
            return lambda *a, **kw: None

    def test_long_query_clips_the_head_and_keeps_the_caret_in_field(self, app_ctx):
        """Round 19 (overnight): the field drew the query with max_chars=52 —
        width-blind under proportional type (52 W's ≈ 670pt against a ~428pt
        text budget, overflowing the 460pt field), and the caret measured the
        FULL query, so it painted past the field's right edge — and the user
        couldn't see the last characters they typed. A text field shows the
        TAIL: clip the head with a leading ellipsis, caret inside the field."""
        app, _, _ = app_ctx
        app.authenticated = True
        app.search_focused = True
        app.search_query = "W" * 60
        app.now_monotonic = 0.25  # caret blink phase on

        capture = self._Capture()
        sl_views.draw_search(capture, app, sl_views.FrameOut(),
                             width=1280, height=800, mouse=None)

        shown = next(t["text"] for t in capture.texts if "W" in t.get("text", ""))
        assert shown.startswith("…"), "an overflowing query clips the head, not the tail"
        assert shown.endswith("WWWWW"), "the tail being typed stays visible"
        width = app.ctx.measure_text(shown, font_size_px=14.0,
                                     font_family=sl_views.FONT_FAMILY)
        budget = 460.0 - 18 - 14
        assert width <= budget + 1e-6, \
            f"shown text overflows the field: {width:.1f} > {budget:.1f}"

        carets = [r for r in capture.rects if r["z_index"] == 4 and r["width"] <= 2.0]
        assert len(carets) == 1
        inner_right = sl_views.CONTENT_PAD + 460.0 - 14.0
        assert carets[0]["x"] <= inner_right, \
            f"caret escapes the field: x={carets[0]['x']:.1f} > {inner_right:.1f}"

    def test_short_query_displays_whole_without_ellipsis(self, app_ctx):
        """Characterization: a query that fits is shown verbatim (no leading
        or trailing ellipsis) — the head-clip only fires on overflow."""
        app, _, _ = app_ctx
        app.authenticated = True
        app.search_focused = True
        app.search_query = "jazz"
        app.now_monotonic = 0.25

        capture = self._Capture()
        sl_views.draw_search(capture, app, sl_views.FrameOut(),
                             width=1280, height=800, mouse=None)

        shown = next(t["text"] for t in capture.texts if "jazz" in t.get("text", ""))
        assert shown == "jazz"

    def test_results_grouped_by_kind(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        artist = _artist("Nirvana")
        album = _album("Nevermind", artist)
        app.authenticated = True
        app.view = "search"
        app.search_query = "nirvana"
        app.search_results = sl_models.SearchResults(
            tracks=(_track("Lithium", artist, album),),
            albums=(album,),
            artists=(artist,),
            playlists=(_playlist("90s Rock"),),
        )

        _tick(app, ctx, 2)

        texts = _texts(scene_buffer)
        for expected in ("nirvana", "Songs", "Albums", "Artists", "Playlists",
                         "Lithium", "Nevermind", "Nirvana"):
            assert expected in texts, f"missing text: {expected!r}"
        # Track rows outside a playlist context play bare uris.
        assert any(region.action == "play_uris" for region in app._hits)

        # The playlist card sits below the fold at 1280x800; scroll to reveal it.
        app.content_scroll = 480.0
        app.invalidate()
        _tick(app, ctx, 2)
        assert "90s Rock" in _texts(scene_buffer)


# ---------------------------------------------------------------------------
# SL-39 (Alec, annotated mock): the bottom-dock search circle becomes an
# expanding search cluster — clicking it docks the library component as a
# floating panel right-aligned directly above the circle, and the circle
# itself grows horizontally into an editable query field wired to the
# existing debounced search flow (results keep rendering in the content
# area's search view). The circle's cap morphs into a dismiss affordance;
# Escape and navigating elsewhere also collapse back to the left rail.
# ---------------------------------------------------------------------------

class TestSearchExpand:
    # nav_search circle at 1280x800 (dock-cluster natural): (1008,730,44,44).
    CIRCLE = (1030.0, 752.0)
    CIRCLE_RIGHT = 1052.0

    @staticmethod
    def _click(app, ctx, x, y):
        events = [
            HDIEvent(event_id=1, ts_ns=1, window_id="w", device="mouse",
                     event_type="pointer_move", status="OK",
                     payload={"x": x, "y": y, "buttons_mask": 0}),
            HDIEvent(event_id=2, ts_ns=2, window_id="w", device="mouse",
                     event_type="click", status="OK",
                     payload={"x": x, "y": y, "button": 0, "phase": "down", "click_count": 1}),
            HDIEvent(event_id=3, ts_ns=3, window_id="w", device="mouse",
                     event_type="click", status="OK",
                     payload={"x": x, "y": y, "button": 0, "phase": "up", "click_count": 1}),
        ]
        app.input.raw_events = lambda *args, **kwargs: list(events)
        try:
            _tick(app, ctx, 1)
        finally:
            del app.input.raw_events

    @staticmethod
    def _authed(app, ctx, *, playlists=3):
        app.authenticated = True
        app._bootstrap_done = True
        app.playlists = [_playlist(f"Mix {i}") for i in range(playlists)]
        _tick(app, ctx, 2)

    def _expand(self, app, ctx):
        self._authed(app, ctx)
        self._click(app, ctx, *self.CIRCLE)
        _tick(app, ctx, 2)

    def test_circle_click_expands_and_focuses(self, app_ctx):
        app, ctx, _ = app_ctx
        self._authed(app, ctx)
        assert app.search_expanded is False
        self._click(app, ctx, *self.CIRCLE)
        assert app.search_expanded is True
        assert app.view == "search", "results render in the existing search view"
        assert app.search_focused is True, "the expanded field is ready to type"
        assert app.mcp_state()["search_expanded"] is True

    def test_field_anchors_to_circle_right_edge(self, app_ctx):
        app, ctx, _ = app_ctx
        self._expand(app, ctx)
        field = sl_views.search_expanded_field_rect(app, WIDTH, HEIGHT)
        fx, fy, fw, fh = field
        assert abs((fx + fw) - self.CIRCLE_RIGHT) < 1e-6, \
            "the field grows leftward from the circle's right edge"
        assert fw >= 300.0 and fh == 44.0
        focus = [r for r in app._hits if r.action == "focus_search"]
        assert len(focus) == 1, "the in-content field is gone while expanded"
        assert abs(focus[0].x - fx) < 1e-6 and focus[0].w == fw
        close = next(r for r in app._hits if r.action == "close_search")
        assert (close.x, close.y, close.w, close.h) == (1008.0, 730.0, 44.0, 44.0), \
            "the dismiss affordance sits exactly where the circle was"
        assert not any(r.action == "nav" and r.payload == "search" for r in app._hits), \
            "the nav circle is replaced by the field while expanded"

    def test_library_panel_docks_right_aligned_above_field(self, app_ctx):
        app, ctx, _ = app_ctx
        self._expand(app, ctx)
        px, py, pw, ph = sl_views.library_panel_rect(app, WIDTH, HEIGHT)
        fx, fy, fw, fh = sl_views.search_expanded_field_rect(app, WIDTH, HEIGHT)
        assert abs((px + pw) - (fx + fw)) < 1e-6, "panel is right-aligned with the field"
        assert abs((py + ph) - (fy - 12.0)) < 1e-6, "panel bottom sits 12pt above the field"
        pill_bottom = sl_views.pill_rect(WIDTH, HEIGHT)[1] + sl_views.pill_rect(WIDTH, HEIGHT)[3]
        assert py >= pill_bottom, "the panel clears the top-right pill"
        # The docked library component: title, playlist rows, account chip.
        texts = {n.text: n for n in _nodes(app_ctx[2], TextNode)}
        assert "Your Library" in texts and "PLAYLISTS" in texts
        assert texts["Your Library"].x >= px
        assert "Mix 0" in texts and texts["Mix 0"].x >= px
        assert "Log out" in texts and texts["Log out"].x >= px
        assert any(r.action == "open_playlist" and r.x >= px for r in app._hits)
        assert any(r.action == "logout" and r.x >= px for r in app._hits)

    def test_left_rail_hidden_while_expanded(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        self._expand(app, ctx)
        px, _py, _pw, _ph = sl_views.library_panel_rect(app, WIDTH, HEIGHT)
        texts = {n.text: n for n in _nodes(scene_buffer, TextNode)}
        assert "Spotify Light" in texts and texts["Spotify Light"].x >= px, \
            "the rail's brand relocated INTO the popup — there is no separate rail"
        library_texts = [n for n in _nodes(scene_buffer, TextNode)
                         if n.text == "Your Library"]
        assert library_texts and all(n.x > 600 for n in library_texts), \
            "the library lives in the right-docked panel, not the left rail"
        m = sl_views.SIDEBAR_GLASS_MARGIN
        old_rail = (m, m, sl_views.SIDEBAR_W - 2 * m, HEIGHT - 2 * m)
        rings = [n for n in _nodes(scene_buffer, RoundedRectNode)
                 if n.color_rgba == sl_views.GLASS_BORDER
                 and (n.x, n.y, n.width, n.height) == old_rail]
        assert rings == [], "nothing draws at the old rail footprint, even expanded"

    def test_results_render_in_content_area(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        self._expand(app, ctx)
        artist = _artist("Nirvana")
        album = _album("Nevermind", artist)
        app.search_query = "nirvana"
        app.search_results = sl_models.SearchResults(
            tracks=(_track("Lithium", artist, album),), albums=(album,),
            artists=(artist,), playlists=())
        app.invalidate()
        _tick(app, ctx, 2)
        texts = _texts(scene_buffer)
        assert "Songs" in texts and "Lithium" in texts, \
            "the existing search flow's results keep the content stage"

    def test_typing_and_enter_submit_the_query(self, app_ctx):
        app, ctx, _ = app_ctx
        self._expand(app, ctx)
        event = lambda key: type("E", (), {"payload": {"key": key, "phase": "down"}})()
        for ch in "jaz":
            app._handle_key(event(ch))
        assert app.search_query == "jaz"
        assert app._search_dirty_at is not None, "typing keeps the debounce armed"
        app._client = object()
        submitted = []
        app.worker.submit = lambda name, job: submitted.append(name)
        app._handle_key(event("enter"))
        assert submitted == ["search"], "the expanded field drives the existing search job"

    def test_close_cap_restores_prior_layout(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        self._expand(app, ctx)
        # Same point that opened the cluster: the cap is now the dismiss.
        self._click(app, ctx, *self.CIRCLE)
        assert app.search_expanded is False
        assert app.view == "home", "dismiss restores the pre-expand view"
        assert app.search_focused is False
        _tick(app, ctx, 2)
        assert "Spotify Light" not in _texts(scene_buffer), \
            "the library exists only as the popup — closing it leaves no rail behind"

    def test_escape_collapses_and_restores_view(self, app_ctx):
        app, ctx, _ = app_ctx
        app.authenticated = True
        app._bootstrap_done = True
        app.view = "library"
        _tick(app, ctx, 1)
        app._dispatch_action("nav", "search", 0.0)
        assert app.search_expanded is True and app.view == "search"
        event = type("E", (), {"payload": {"key": "escape", "phase": "down"}})()
        app._handle_key(event)
        assert app.search_expanded is False
        assert app.view == "library", "escape restores the view the user came from"
        assert app.search_focused is False

    def test_navigating_elsewhere_collapses_without_restore(self, app_ctx):
        app, ctx, _ = app_ctx
        self._expand(app, ctx)
        app._dispatch_action("nav", "home", 0.0)
        assert app.search_expanded is False and app.view == "home"

    def test_open_playlist_from_panel_collapses(self, app_ctx):
        app, ctx, _ = app_ctx
        self._expand(app, ctx)
        row = next(r for r in app._hits if r.action == "open_playlist")
        app._dispatch_action(row.action, row.payload, row.x)
        assert app.view == f"playlist:{row.payload}"
        assert app.search_expanded is False, "leaving search collapses the cluster"

    def test_panel_dead_space_swallows_clicks(self, app_ctx):
        app, ctx, _ = app_ctx
        self._expand(app, ctx)
        assert app.search_focused is True
        px, py, pw, ph = sl_views.library_panel_rect(app, WIDTH, HEIGHT)
        # Dead plate space: below the last playlist row, above the account chip.
        self._click(app, ctx, px + pw / 2, py + ph - 60)
        assert app.search_expanded is True and app.search_focused is True, \
            "clicks on the panel plate must not fall through to dismiss/blur"

    def test_layout_override_moves_the_expansion_anchor(self, app_ctx):
        app, ctx, _ = app_ctx
        self._authed(app, ctx)
        app.layout_overrides.set("nav_search",
                                 {"rect": {"x": 900, "y": 600, "width": 44, "height": 44}})
        app._dispatch_action("nav", "search", 0.0)
        _tick(app, ctx, 1)
        fx, fy, fw, fh = sl_views.search_expanded_field_rect(app, WIDTH, HEIGHT)
        assert abs((fx + fw) - 944.0) < 1e-6 and fy == 600.0, \
            "the expansion anchors to the OVERRIDDEN circle, not the natural"
        px, py, pw, ph = sl_views.library_panel_rect(app, WIDTH, HEIGHT)
        assert abs((px + pw) - 944.0) < 1e-6
        assert py + ph <= fy, "the panel still docks above the field"

    def test_wheel_scroll_tracks_the_panel_not_the_rail(self, app_ctx):
        app, ctx, _ = app_ctx
        app.authenticated = True
        app._bootstrap_done = True
        app.playlists = [_playlist(f"Mix {i}") for i in range(40)]
        app._dispatch_action("nav", "search", 0.0)
        _tick(app, ctx, 1)
        app._content_height = 4000.0  # after the tick: the frame recomputes it
        px, py, pw, ph = sl_views.library_panel_rect(app, WIDTH, HEIGHT)
        # Inside the panel: the playlist list scrolls (offset -= delta_y, the
        # app's natural-scroll sign convention).
        app._mouse = (px + pw / 2, py + ph / 2)
        app._apply_scroll(-120.0)
        assert app.sidebar_scroll == 120.0 and app.content_scroll == 0.0
        # The vacated left-rail strip is content now, not the sidebar list.
        app._mouse = (100.0, 400.0)
        app._apply_scroll(-60.0)
        assert app.sidebar_scroll == 120.0 and app.content_scroll == 60.0


class _FakeNativeField:
    def __init__(self, *, x, y, width, height, placeholder, value, on_change, on_submit,
                 within=None, bordered=True):
        self.frame = (x, y, width, height)
        self.placeholder = placeholder
        self.value = value
        self.on_change = on_change
        self.on_submit = on_submit
        self.within = within
        self.bordered = bordered
        self.is_visible = True
        self.destroyed = False
        self.set_frame_calls = 0

    def set_frame(self, x, y, width, height):
        self.frame = (x, y, width, height)
        self.set_frame_calls += 1

    def set_value(self, value):
        self.value = value
        if self.on_change is not None:
            self.on_change(value)

    def show(self):
        self.is_visible = True

    def hide(self):
        self.is_visible = False

    def focus(self):
        pass

    def resign(self):
        pass

    def destroy(self):
        self.destroyed = True


class _FakeGlassSurface:
    def __init__(self, *, x, y, width, height, corner_radius=0.0, style="regular",
                 placement="above"):
        self.frame = (x, y, width, height)
        self.set_frame_calls = 0
        self.corner_radius = corner_radius
        self.corner_radius_calls: list[float] = []
        self.style = style
        self.placement = placement
        self.is_visible = True
        self.destroyed = False

    def set_frame(self, x, y, width, height):
        self.frame = (x, y, width, height)
        self.set_frame_calls += 1

    def set_corner_radius(self, radius):
        self.corner_radius = radius
        self.corner_radius_calls.append(radius)

    def show(self):
        self.is_visible = True

    def hide(self):
        self.is_visible = False

    def destroy(self):
        self.destroyed = True


class _FakeNativeButton:
    def __init__(self, *, x, y, width, height, title, within=None, on_press=None):
        self.frame = (x, y, width, height)
        self.title = title
        self.within = within
        self.on_press = on_press
        self.enabled = True
        self.is_visible = True
        self.destroyed = False
        self.set_frame_calls = 0

    def set_frame(self, x, y, width, height):
        self.frame = (x, y, width, height)
        self.set_frame_calls += 1

    def show(self):
        self.is_visible = True

    def hide(self):
        self.is_visible = False

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)

    def destroy(self):
        self.destroyed = True


class _FakeWebView:
    def __init__(self, *, x, y, width, height, redirect_prefix="", on_redirect=None,
                 on_navigation_state=None):
        self.frame = (x, y, width, height)
        self.redirect_prefix = redirect_prefix
        self.on_redirect = on_redirect
        self.on_navigation_state = on_navigation_state
        self.loaded_urls: list[str] = []
        self.can_go_back = False
        self.went_back = 0
        self.is_visible = True
        self.destroyed = False

    def load_url(self, url):
        self.loaded_urls.append(url)

    def go_back(self):
        self.went_back += 1

    def set_frame(self, x, y, width, height):
        self.frame = (x, y, width, height)

    def show(self):
        self.is_visible = True

    def hide(self):
        self.is_visible = False

    def destroy(self):
        self.destroyed = True


class _FakeNativeBridge:
    def __init__(self):
        self.available = True
        self.supports_under_glass = False
        self.created: list[_FakeNativeField] = []
        self.buttons: list[_FakeNativeButton] = []
        self.web_views: list[_FakeWebView] = []
        self.glass: list[_FakeGlassSurface] = []
        self.web_view_error: Exception | None = None
        self.button_error: Exception | None = None
        self.backdrop_error: Exception | None = None

    def create_text_field(self, **kwargs):
        field = _FakeNativeField(**kwargs)
        self.created.append(field)
        return field

    def create_button(self, **kwargs):
        if self.button_error is not None:
            raise self.button_error
        button = _FakeNativeButton(**kwargs)
        self.buttons.append(button)
        return button

    def create_web_view(self, **kwargs):
        if self.web_view_error is not None:
            raise self.web_view_error
        view = _FakeWebView(**kwargs)
        self.web_views.append(view)
        return view

    def create_glass_surface(self, **kwargs):
        if self.backdrop_error is not None and kwargs.get("placement") == "backdrop":
            raise self.backdrop_error
        surface = _FakeGlassSurface(**kwargs)
        self.glass.append(surface)
        return surface

    def suppress_keyboard(self):
        return False

    def consume_point(self, x, y):
        return False

    def close(self):
        pass


class TestNativeClientIdField:
    def test_native_field_replaces_drawn_field(self, app_ctx, monkeypatch):
        app, ctx, scene_buffer = app_ctx
        bridge = _FakeNativeBridge()
        monkeypatch.setattr(app_main, "native_controls", lambda: bridge)

        _tick(app, ctx, 2)

        assert len(bridge.created) == 1
        field = bridge.created[0]
        # Field insets inside its 380x40 glass capsule (450,420): 14pt sides,
        # vertically centered in a 20pt-high editor so the placeholder and
        # text sit mid-plate instead of top-aligned.
        assert field.frame == (464.0, 430.0, 352.0, 20.0)
        texts = _texts(scene_buffer)
        assert "Client ID" not in texts  # drawn placeholder replaced by the native field
        assert any("developer.spotify.com/dashboard" in t for t in texts)  # instructions stay
        actions = {region.action for region in app._hits}
        assert "focus_client_id" not in actions
        assert "save_client_id" not in actions  # native Save owns the click; disabled pre-draft
        save = bridge.buttons[0]
        assert save.enabled is False

        # Typing into the native field flows into the app draft and arms Save.
        field.set_value("abc-123")
        assert app.client_id_draft == "abc-123"
        _tick(app, ctx, 1)
        assert save.enabled is True
        assert "save_client_id" not in {region.action for region in app._hits}

    def test_native_frames_reapply_each_render(self, app_ctx, monkeypatch):
        """Mac evidence: the native plate drifted above its design position
        because the syncs early-outed on an unchanged logical frame while the
        content view had resized underneath. Frames must re-apply every render
        so the AppKit frame always derives from the current bounds."""
        app, ctx, _ = app_ctx
        bridge = _FakeNativeBridge()
        monkeypatch.setattr(app_main, "native_controls", lambda: bridge)

        _tick(app, ctx, 2)
        field = bridge.created[0]
        save = bridge.buttons[0]
        surfaces = list(bridge.glass)
        assert surfaces and field.set_frame_calls >= 1
        before = (field.set_frame_calls, save.set_frame_calls,
                  [g.set_frame_calls for g in surfaces])

        # A state change (or window resize) invalidates and re-renders; every
        # re-render must re-apply the native frames against current bounds.
        app.invalidate()
        _tick(app, ctx, 2)

        assert field.set_frame_calls > before[0]
        assert save.set_frame_calls > before[1]
        for surface, prev in zip(surfaces, before[2]):
            assert surface.set_frame_calls > prev

    def test_field_destroyed_once_client_id_saved(self, app_ctx, monkeypatch):
        app, ctx, _ = app_ctx
        bridge = _FakeNativeBridge()
        monkeypatch.setattr(app_main, "native_controls", lambda: bridge)
        _tick(app, ctx, 1)
        field = bridge.created[0]
        field.set_value("abc-123")
        app._dispatch_action("save_client_id", None, 0.0)
        assert app.client_id == "abc-123"

        _tick(app, ctx, 1)

        assert field.destroyed is True
        assert len(bridge.created) == 1  # not recreated for the Connect view

    def test_no_field_when_bridge_unavailable(self, app_ctx, monkeypatch):
        app, ctx, scene_buffer = app_ctx
        monkeypatch.setattr(app_main, "native_controls", lambda: None)
        _tick(app, ctx, 2)
        assert "Client ID" in _texts(scene_buffer)
        assert app._native_client_id_field is None

    def test_keyboard_events_do_not_edit_draft_while_native_active(self, app_ctx, monkeypatch):
        app, ctx, _ = app_ctx
        bridge = _FakeNativeBridge()
        monkeypatch.setattr(app_main, "native_controls", lambda: bridge)
        _tick(app, ctx, 1)
        app._handle_key(type("E", (), {"payload": {"key": "x", "code": 7, "phase": "down"}})())
        assert app.client_id_draft == ""


class TestControlKeyNames:
    """Synthetic keyboards (the MCP tunnel, accessibility drivers) name
    control keys instead of sending macOS keycodes: the payload carries
    key="backspace"/"enter"/"escape" with no `code`. The HDI keyboard
    normalizer also rebuilds key_down payloads as {phase, key, active_keys}
    — `code` never survives the tunnel. Key names must act exactly like
    their keycode equivalents or remote drivers cannot edit text."""

    @staticmethod
    def _event(key: str):
        return type("E", (), {"payload": {"key": key, "phase": "down"}})()

    def test_backspace_name_deletes_a_character(self, app_ctx):
        app, _, _ = app_ctx
        app.authenticated = True
        app.search_focused = True
        app.search_query = "blue"
        app._handle_key(self._event("backspace"))
        assert app.search_query == "blu"

    def test_escape_name_unfocuses_the_field(self, app_ctx):
        app, _, _ = app_ctx
        app.authenticated = True
        app.search_focused = True
        app._handle_key(self._event("escape"))
        assert app.search_focused is False

    def test_enter_name_submits_the_search(self, app_ctx):
        app, _, _ = app_ctx
        app.authenticated = True
        app.search_focused = True
        app.search_query = "blue"
        app._client = object()
        submitted = []
        app.worker.submit = lambda name, job: submitted.append(name)
        app._handle_key(self._event("enter"))
        assert submitted == ["search"]


class TestPlayerBar:
    def test_transport_and_device_popup(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        artist = _artist("Nirvana")
        album = _album("Nevermind", artist)
        track = _track("Lithium", artist, album, ms=257_000)
        app.authenticated = True
        app.devices = [
            sl_models.Device(id="d1", name="MacBook Pro", kind="Computer", is_active=True,
                             is_restricted=False, volume_percent=65),
            sl_models.Device(id="d2", name="Kitchen Speaker", kind="Speaker", is_active=False,
                             is_restricted=False, volume_percent=None),
        ]
        app.player = sl_models.PlayerState(is_playing=True, progress_ms=30_500, track=track,
                                           device=app.devices[0], shuffle=True, repeat="context")
        app._player_synced_at = app.now_monotonic
        app.show_devices = True

        _tick(app, ctx, 2)

        texts = _texts(scene_buffer)
        for expected in ("Lithium", "Nirvana", "4:17", "Connect to a device",
                         "MacBook Pro", "Kitchen Speaker", "Speaker"):
            assert expected in texts, f"missing text: {expected!r}"
        # Round 13: pause is two drawn bars now, not text pipes.
        assert "||" not in texts
        # Elapsed-time label reflects interpolated progress near 0:30/0:31.
        assert any(t in ("0:30", "0:31") for t in texts)
        actions = {region.action for region in app._hits}
        assert {"toggle_shuffle", "prev", "next", "cycle_repeat", "pick_device"} <= actions


class TestFloatingPill:
    """Round 8: the full-width player bar becomes a centered floating glass
    capsule (liquid-glass music pill reference), flanked by circular
    Home/Search nav buttons. Volume/shuffle/repeat/devices move into a
    playback popup opened from an overflow circle at the bottom-right."""

    def _with_track(self, app, ctx, *, show_devices=False):
        app.authenticated = True
        nirvana = _artist("Nirvana")
        track = _track("Lithium", nirvana, _album("Nevermind", nirvana), ms=257_000)
        app.devices = [
            sl_models.Device(id="d1", name="MacBook Pro", kind="Computer", is_active=True,
                             is_restricted=False, volume_percent=40),
        ]
        app.player = sl_models.PlayerState(is_playing=True, progress_ms=30_500, track=track,
                                           device=app.devices[0], shuffle=True, repeat="context")
        app._player_synced_at = app.now_monotonic
        app.show_devices = show_devices
        _tick(app, ctx, 2)

    def test_player_chrome_is_a_top_right_floating_capsule(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        self._with_track(app, ctx)

        px, py, pw, ph = sl_views.pill_rect(1280, 800)
        # Round 30 (Alec): the pill left the bottom dock for the window's
        # TOP-RIGHT corner — right edge pinned at width - PILL_FLOAT, top at
        # the same 16pt float margin the dock used; round 32: 108pt tall, so
        # the right-edge anchor grows the capsule leftward; round 38 (SL-23):
        # 692 = 1280-16-572, the width derived from the transport center.
        assert (px, py, pw, ph) == (692.0, 16.0, 572.0, 108.0)
        rrects = _nodes(scene_buffer, RoundedRectNode)
        rings = [n for n in rrects
                 if n.color_rgba == sl_views.GLASS_BORDER and n.x == px and n.y == py
                 and n.width == pw and n.height == ph
                 and n.radius == sl_views.glass_silhouette_radius(ph)]
        assert len(rings) == 1, \
            "pill must be one glass plate; at 108pt the size rule makes it a rounded rect"
        # The full-width bar is gone: nothing spans the window at the bottom.
        assert [n for n in rrects if n.width == 1280] == []
        rects = _nodes(scene_buffer, RectNode)
        assert [n for n in rects if n.width == 1280 and n.y >= 700] == []

    def test_pill_shows_art_metadata_transport_and_seek(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        self._with_track(app, ctx)
        px, py, _, _ = sl_views.pill_rect(1280, 800)

        texts = _texts(scene_buffer)
        for expected in ("Lithium", "Nirvana", "4:17"):
            assert expected in texts, f"missing text: {expected!r}"
        assert "||" not in texts, "pause is drawn bars, not text pipes"
        assert any(t in ("0:30", "0:31") for t in texts), "elapsed time stays in the pill"
        art = [n for n in _nodes(scene_buffer, CpuLayerNode)
               if n.x == px + 12 and n.y == py + 12 and n.width == 84]
        assert len(art) == 1, "album art thumb sits at the pill's left"
        hits = {(r.action, r.payload if isinstance(r.payload, str) else None): r
                for r in app._hits}
        for action in ("toggle_play", "prev", "next"):
            assert any(r.action == action for r in app._hits), f"missing hit: {action}"
        seek = [r for r in app._hits if r.action == "seek_bar"]
        assert len(seek) == 1 and seek[0].y > py, "seek strip lives inside the pill"

    def test_nav_circles_hold_the_bottom_dock(self, app_ctx):
        """Round 30: the pill moved top-right WITHOUT the nav circles — Home
        and Search keep the exact bottom-dock coordinates the flanking
        cluster gave them."""
        app, ctx, scene_buffer = app_ctx
        self._with_track(app, ctx)
        app.view = "home"
        _tick(app, ctx, 1)

        dpx, dpy, _, _ = sl_views.dock_cluster_rect(1280, 800)
        cy = dpy + 32
        home = [r for r in app._hits if r.action == "nav" and r.payload == "home"]
        search = [r for r in app._hits if r.action == "nav" and r.payload == "search"]
        assert len(home) == 1 and len(search) == 1
        assert (home[0].x, home[0].y, home[0].w, home[0].h) == (468.0, cy - 22, 44.0, 44.0)
        assert (search[0].x, search[0].y) == (dpx + 460 + 18, cy - 22)
        assert home[0].x >= sl_views.SIDEBAR_W + sl_views.PILL_FLOAT, \
            "the home circle never crosses the sidebar"
        texts = _texts(scene_buffer)
        assert sl_icons.HOME in texts and sl_icons.SEARCH in texts, \
            "nav circles carry icon glyphs"
        frame = scene_buffer.latest_frame()
        home_glyph = [n for n in frame.nodes
                      if isinstance(n, TextNode) and n.text == sl_icons.HOME]
        assert home_glyph and home_glyph[0].color_rgba == sl_views.ACCENT, \
            "the active view's circle glyph lights up"

    def test_overflow_circle_hosts_playback_popup(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        self._with_track(app, ctx, show_devices=True)

        overflow = [r for r in app._hits if r.action == "open_devices"]
        assert len(overflow) == 1
        # Round 41: the circle is attached to the pill's top-right slot (the
        # shipped layout.toml relationship); placement itself is pinned by
        # TestOverflowPersistsLeftOfPill. This test owns the popup's
        # contents and its menu-style anchoring: right edge on the circle,
        # top edge 12pt below the pill's bottom.
        texts = _texts(scene_buffer)
        for expected in ("Volume", "Shuffle", "Repeat", "Connect to a device", "MacBook Pro"):
            assert expected in texts, f"missing popup text: {expected!r}"
        actions = {r.action for r in app._hits}
        assert {"volume_bar", "toggle_shuffle", "cycle_repeat", "pick_device"} <= actions
        _, py, _, ph = sl_views.pill_rect(1280, 800)
        plates = [n for n in _nodes(scene_buffer, RoundedRectNode)
                  if n.color_rgba == (18, 18, 18, 234) and n.width == 298]
        assert plates and all(n.y - 1 == py + ph + 12
                              and n.x + n.width + 1 == overflow[0].x + overflow[0].w
                              for n in plates), \
            "playback popup drops from the pill's bottom, right-aligned to the ⋯"

    def test_sidebar_keeps_library_and_account(self, app_ctx):
        """Round 67: the library/account component is the search-anchored
        popup — collapsed there is no rail chrome at all; expanded, the
        panel carries the nav row and the account chip."""
        app, ctx, scene_buffer = app_ctx
        self._with_track(app, ctx)

        assert not any(r.action == "nav" and r.x < sl_views.SIDEBAR_W for r in app._hits), \
            "Home/Search moved to the pill's flanking circles — and the rail is gone"
        app.search_expanded = True
        app.invalidate()
        _tick(app, ctx, 2)
        px, _py, pw, _ph = sl_views.library_panel_rect(app, WIDTH, HEIGHT)
        popup_nav = [r for r in app._hits
                     if r.action == "nav" and px <= r.x < px + pw]
        assert {r.payload for r in popup_nav} == {"library"}, \
            "the library nav row lives in the popup"
        texts = _texts(scene_buffer)
        assert "Your Library" in texts and "Log out" in texts

    def test_empty_pill_state(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        _tick(app, ctx, 2)

        texts = _texts(scene_buffer)
        assert "Nothing playing" in texts
        actions = {r.action for r in app._hits}
        assert {"toggle_play", "seek_bar", "open_devices"} <= actions

    def test_empty_thumb_is_a_calm_note_tile_not_a_hash_placeholder(self, app_ctx):
        """Round 17 (overnight live pass on `670b15c`): the idle pill rendered
        a saturated hash-colored placeholder tile (a bright green square in
        the live screenshots) — the loudest element of the idle chrome.
        Spotify's own idle state is a neutral tile with a note glyph."""
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        _tick(app, ctx, 2)

        px, py, _, _ = sl_views.pill_rect(1280, 800)
        thumb_layers = [n for n in _nodes(scene_buffer, CpuLayerNode)
                        if n.x == px + 12 and n.y == py + 12]
        assert not thumb_layers, \
            "the empty pill must not render a hash-colored placeholder tile"
        notes = [n for n in _nodes(scene_buffer, TextNode) if n.text == sl_icons.NOTE]
        assert notes, "the empty thumb shows a calm note glyph"
        note = notes[0]
        cx, cy = px + 12 + 42, py + 12 + 42
        assert abs(note.x - cx) < 20 and abs(note.y - cy) < 22, \
            f"note glyph should sit at the thumb's center, got ({note.x}, {note.y})"

    @staticmethod
    def _meta_budget(pw: float) -> float:
        col_x, col_w, _ = sl_views.pill_column(pw, sl_views.PILL_H)
        return col_w

    def test_idle_hint_shows_the_full_sentence_at_design_width(self, app_ctx):
        """Round 18 (overnight live pass on `670b15c`): the idle pill subtext
        was char-truncated at 40 and rendered "Pick a device, or start
        something from …" — cut mid-phrase on every idle screen. The full
        sentence measures ~230pt at size 11 and the design-width metadata
        budget is ~246pt: it fits, so show it whole."""
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        _tick(app, ctx, 2)

        assert "Pick a device, or start something from a playlist" in _texts(scene_buffer)

    def test_idle_hint_truncates_to_measured_width_when_the_pill_shrinks(self, app_ctx):
        """Char-count truncation is width-blind: at 560pt the pill sits at its
        320pt floor and 40 chars (~194pt) overflows the ~192pt column
        budget. Truncation must be driven by the measured width, ending in
        an ellipsis when it cuts."""
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        ctx.logical_width_px = 560.0
        _tick(app, ctx, 2)

        px, _, pw, _ = sl_views.pill_rect(560.0, 800.0)
        budget = self._meta_budget(pw)
        hints = [n for n in _nodes(scene_buffer, TextNode)
                 if n.text.startswith("Pick a device")]
        assert hints, "idle hint missing"
        hint = hints[0]
        width = ctx.measure_text(hint.text, font_size_px=11.0,
                                 font_family=sl_views.FONT_FAMILY)
        assert width <= budget + 1e-6, \
            f"hint overflows the metadata budget: {width:.1f} > {budget:.1f}"
        assert hint.text.endswith("…"), "a cut hint should say so"
        assert hint.x == px + 110

    def test_track_metadata_truncates_to_measured_width_not_char_count(self, app_ctx):
        """Same width-blindness in the playing state: 32 chars of a wide
        string at size 13 far exceeds the metadata budget and paints into
        the transport; 32 chars of a narrow string over-truncates. The cap
        must be the measured width."""
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        artist = _artist("Nirvana")
        album = _album("Nevermind", artist)
        wide = "W" * 40
        app.player = sl_models.PlayerState(
            is_playing=True, progress_ms=1000,
            track=_track(wide, artist, album), device=None, shuffle=False,
            repeat="off", timestamp_ms=0)
        _tick(app, ctx, 2)

        px, _, pw, _ = sl_views.pill_rect(1280.0, 800.0)
        budget = self._meta_budget(pw)
        titles = [n for n in _nodes(scene_buffer, TextNode)
                  if n.text.startswith("WWWW")]
        assert titles, "track title missing"
        title = titles[0]
        width = ctx.measure_text(title.text, font_size_px=13.0,
                                 font_family=sl_views.FONT_FAMILY)
        assert width <= budget + 1e-6, \
            f"wide title overflows the metadata budget: {width:.1f} > {budget:.1f}"
        assert title.text.endswith("…")


class TestBigPillTransportRow:
    """Round 32 (Alec, pill-v2.png): the pill grows — taller capsule, album
    tile scaled to match with the same inset idiom — and the transport row
    leaves the pill's right side for a spot UNDER the progress bar. The
    right column reads top-to-bottom: title/artist, bar with times, then
    prev/play/next centered under the column. Idle and playing share one
    geometry so nothing jumps when a track starts."""

    def _playing(self, app, ctx):
        app.authenticated = True
        nirvana = _artist("Nirvana")
        track = _track("Lithium", nirvana, _album("Nevermind", nirvana), ms=257_000)
        app.player = sl_models.PlayerState(is_playing=True, progress_ms=30_500, track=track,
                                           device=None, shuffle=False, repeat="off")
        app._player_synced_at = app.now_monotonic
        _tick(app, ctx, 2)

    @staticmethod
    def _hit(app, action):
        hits = [r for r in app._hits if r.action == action]
        assert len(hits) == 1, f"expected exactly one {action} hit region"
        return hits[0]

    def test_pill_rect_grows_and_keeps_the_320_floor(self):
        px, py, pw, ph = sl_views.pill_rect(1280, 800)
        assert (pw, ph) == (572.0, 108.0), "the capsule scales up (SL-23: 2 x the transport center)"
        assert py == sl_views.PILL_FLOAT, "the top float margin is unchanged"
        assert px + pw == 1280.0 - sl_views.PILL_FLOAT, \
            "right edge pinned — the growth goes leftward"
        _, _, pw_narrow, _ = sl_views.pill_rect(560.0, 800.0)
        assert pw_narrow == sl_views.PILL_MIN_W == 320.0, "the 320pt floor still holds"
        _, _, pw_mid, _ = sl_views.pill_rect(940.0, 800.0)
        assert pw_mid == 572.0, "940pt still fits the design-width pill"

    def test_art_tile_scales_up_with_the_pill(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        self._playing(app, ctx)
        px, py, _, ph = sl_views.pill_rect(1280, 800)
        art_size = ph - 24.0
        art = [n for n in _nodes(scene_buffer, CpuLayerNode)
               if n.x == px + 12 and n.y == py + 12 and n.width == art_size]
        assert len(art) == 1, \
            "the album tile grows with the pill height, same 12pt inset idiom"
        rings = [n for n in _nodes(scene_buffer, RoundedRectNode)
                 if n.color_rgba == (255, 255, 255, 24)
                 and n.x == px + 11 and n.y == py + 11 and n.width == art_size + 2]
        assert len(rings) == 1, "the hairline ring hugs the bigger tile"

    def test_metadata_column_starts_right_of_the_bigger_art(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        self._playing(app, ctx)
        px, _, _, _ = sl_views.pill_rect(1280, 800)
        title = [n for n in _nodes(scene_buffer, TextNode) if n.text == "Lithium"]
        artist = [n for n in _nodes(scene_buffer, TextNode) if n.text == "Nirvana"]
        assert title and artist
        assert title[0].x == px + 110.0, \
            "the text column starts right of the bigger tile + gap"
        assert title[0].y < artist[0].y, "title over artist"
        seek = self._hit(app, "seek_bar")
        assert artist[0].y < seek.y, "the bar sits below the text rows"

    def test_transport_row_sits_under_the_bar_centered_on_the_pill(self, app_ctx):
        """Round 38 (SL-23) re-axes this round-32 pin: the transport centers
        on the PILL, not the text column — the play button IS the plate's
        geometric center, and the strip keeps its own column alignment."""
        app, ctx, scene_buffer = app_ctx
        self._playing(app, ctx)
        px, _, pw, _ = sl_views.pill_rect(1280, 800)
        seek = self._hit(app, "seek_bar")
        toggle = self._hit(app, "toggle_play")
        prev = self._hit(app, "prev")
        nxt = self._hit(app, "next")
        assert toggle.y >= seek.y + seek.h, \
            "the transport row lives strictly under the progress bar"
        play_cx = toggle.x + toggle.w / 2
        assert abs(play_cx - (px + pw / 2)) < 1e-6, \
            "play centers on the PILL (SL-23), not the column"
        assert prev.x + prev.w / 2 < play_cx < nxt.x + nxt.w / 2, \
            "prev / play / next reading order"

    def test_play_keeps_its_white_circle_and_hits_stay_generous(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        self._playing(app, ctx)
        toggle = self._hit(app, "toggle_play")
        cx, cy = toggle.x + toggle.w / 2, toggle.y + toggle.h / 2
        discs = [n for n in _nodes(scene_buffer, CircleNode)
                 if abs(n.cx - cx) < 1e-6 and abs(n.cy - cy) < 1e-6
                 and n.fill_rgba[0] >= 225 and n.radius >= 16.0]
        assert discs, "the white play disc keeps its prominence at the row center"
        for action in ("prev", "next"):
            r = self._hit(app, action)
            assert r.w >= 34.0 and r.h >= 34.0, f"{action} hit shrank below today's 34pt"
        assert toggle.w >= 36.0 and toggle.h >= 36.0, "the play hit grows with the disc"

    def test_idle_and_playing_share_the_same_row_geometry(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        _tick(app, ctx, 2)
        idle = {a: (self._hit(app, a).x, self._hit(app, a).y,
                    self._hit(app, a).w, self._hit(app, a).h)
                for a in ("seek_bar", "toggle_play", "prev", "next")}
        strip_idle = [(n.x, n.y, n.width) for n in _nodes(scene_buffer, RoundedRectNode)
                      if n.color_rgba == (70, 70, 70, 255) and n.height == 3]
        self._playing(app, ctx)
        playing = {a: (self._hit(app, a).x, self._hit(app, a).y,
                       self._hit(app, a).w, self._hit(app, a).h)
                   for a in ("seek_bar", "toggle_play", "prev", "next")}
        strip_playing = [(n.x, n.y, n.width) for n in _nodes(scene_buffer, RoundedRectNode)
                         if n.color_rgba == (70, 70, 70, 255) and n.height == 3]
        assert idle == playing, "the bar and transport row must not jump between states"
        assert strip_idle == strip_playing, "the strip itself holds still too"

    def test_times_appear_only_with_a_track_but_the_bar_is_always_there(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        _tick(app, ctx, 2)
        texts = _texts(scene_buffer)
        assert "Nothing playing" in texts
        assert not any(t[:1].isdigit() and ":" in t and len(t) <= 5 for t in texts), \
            "idle shows no time labels"
        strips = [n for n in _nodes(scene_buffer, RoundedRectNode)
                  if n.color_rgba == (70, 70, 70, 255) and n.height == 3]
        assert strips, "the idle pill still shows the (empty) bar"


class TestProgressAlignsWithText:
    """Round 37 (Alec, SL-21 on the SL-22 tool): the progress strip's left
    edge aligns with the title text column, baked via layout_align as a
    persisted RELATIONSHIP in the shipped layout.toml — not resolved pixels.
    At 1280x800 on the round-41 plate the strip sits at pill-local
    (110, 59, 394, 3): left edge on the text column's left, right edge ON
    the narrowed column's right — the bar spans exactly the column, which
    yields the merged ⋯ menu's slot (menu.left − 12, SL-26/27). The time
    labels moved above the strip's ends, so the widened strip never
    paints them over the art tile."""

    def _playing(self, app, ctx):
        app.authenticated = True
        nirvana = _artist("Nirvana")
        track = _track("Lithium", nirvana, _album("Nevermind", nirvana), ms=257_000)
        app.player = sl_models.PlayerState(is_playing=True, progress_ms=30_500, track=track,
                                           device=None, shuffle=False, repeat="off")
        app._player_synced_at = app.now_monotonic
        _tick(app, ctx, 2)

    def _strip(self, scene_buffer):
        strips = [n for n in _nodes(scene_buffer, RoundedRectNode)
                  if n.color_rgba == (70, 70, 70, 255) and n.height == 3]
        assert len(strips) == 1, "exactly one progress strip"
        return strips[0]

    def test_strip_left_edge_meets_the_text_column(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        self._playing(app, ctx)
        px, py, _, _ = sl_views.pill_rect(1280, 800)
        title = [n for n in _nodes(scene_buffer, TextNode) if n.text == "Lithium"]
        seek = [r for r in app._hits if r.action == "seek_bar"]
        assert title and seek
        assert seek[0].x == title[0].x == px + 110.0, \
            "strip left == text column left — the SL-21 alignment"
        assert seek[0].w == 394.0 and seek[0].x + seek[0].w == px + 504.0, \
            "the right edge meets the narrowed column's right edge (SL-26/27)"
        strip = self._strip(scene_buffer)
        assert (strip.x, strip.y, strip.width) == (px + 110.0, py + 59.0, 394.0)

    def test_the_alignment_holds_idle(self, app_ctx):
        """The strip geometry is identical with or without a track (the
        no-jump invariant) — so the alignment shows on a fresh idle boot."""
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        _tick(app, ctx, 2)
        px, py, _, _ = sl_views.pill_rect(1280, 800)
        strip = self._strip(scene_buffer)
        assert (strip.x, strip.y, strip.width) == (px + 110.0, py + 59.0, 394.0)

    def test_time_labels_sit_above_the_strip_clear_of_the_art(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        self._playing(app, ctx)
        px, py, _, _ = sl_views.pill_rect(1280, 800)
        frame = scene_buffer.latest_frame()
        elapsed = [n for n in frame.nodes
                   if isinstance(n, TextNode) and n.text in ("0:30", "0:31")]
        duration = [n for n in frame.nodes if isinstance(n, TextNode) and n.text == "4:17"]
        assert elapsed and elapsed[0].x == px + 110.0, \
            "the elapsed label left-aligns with the strip (and the text column)"
        assert elapsed[0].x >= px + 12 + 84, \
            "the label never paints over the art tile (12..96 pill-local)"
        assert elapsed[0].y == py + 59.0 - 11, "the labels float above the strip"
        dur_w = ctx.measure_text("4:17", font_size_px=9.0,
                                 font_family=sl_views.FONT_FAMILY)
        assert duration and duration[0].x == pytest.approx(px + 504.0 - dur_w), \
            "the duration's right edge meets the strip's right end"
        assert duration[0].y == py + 59.0 - 11


class TestDockScrimRemoved:
    """SL-35 (Alec): "i wanna get rid of the bottom one too" — the round-8b
    dock scrim follows the top one (SL-33) out. Content renders at natural
    brightness all the way to the window's bottom edge; the dock's glass
    circles keep their own material, with no dissolve layer in between.
    (History: round 8b added the scrim for text-on-text clashes under the
    translucent dock; the liquid-glass chrome reads fine without it.) The
    bottom scroll inset stays: the last row still clears the dock CHROME."""

    def test_window_bottom_is_clear_of_scrim(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        _tick(app, ctx, 2)
        strips = [n for n in _nodes(scene_buffer, RectNode)
                  if n.x == sl_views.SIDEBAR_W and n.width == 1280 - sl_views.SIDEBAR_W
                  and n.color_rgba[:3] == sl_views.BG[:3]
                  and n.y >= 800.0 - 160.0]  # the round-8b scrim's footprint + margin
        assert strips == [], f"dock scrim strips linger over content: {strips[:3]}"

    def test_scroll_inset_lets_last_row_clear_the_dock(self, app_ctx):
        app, ctx, _ = app_ctx
        _, dock_top, _, _ = sl_views.dock_cluster_rect(1280, 800)
        viewport = 800.0 - sl_views.DOCK_H
        assert viewport <= dock_top - 8.0, \
            "content viewport bottom must clear the dock with margin"
        max_offset = app._clamp_scroll(1e9, 3000.0, viewport)
        assert 3000.0 - max_offset <= dock_top - 8.0, \
            "at max scroll the last content row sits fully above the dock"


class TestDockContentAnchor:
    """Round 10 (Alec live on `ae7fcc2`): the bottom cluster centered on the
    FULL WINDOW, so the home circle and the cluster's left edge sat over the
    sidebar — obscuring the account/Log out row, in the one region the scrim
    deliberately does not cover. The cluster now anchors to the content
    region (x from SIDEBAR_W), same as the scrim; crossing the sidebar is
    structurally impossible, and the cluster slot shrinks below its design
    width only as a last resort. Round 30: the pill left this slot for the
    top-right corner, but the nav/overflow circles and the playback popup
    still anchor here."""

    _CLUSTER_PAD = sl_views.NAV_CIRCLE_GAP + 2 * sl_views.NAV_CIRCLE_R

    def test_cluster_centers_on_content_region_at_design_width(self):
        for w in (1280.0, 1440.0):
            px, _, pw, _ = sl_views.dock_cluster_rect(w, 800)
            assert pw == sl_views.DOCK_SLOT_W, \
                "the slot keeps the vacated pill's footprint, not the grown pill's"
            cluster_left = px - self._CLUSTER_PAD
            cluster_right = px + pw + self._CLUSTER_PAD
            content_cx = (sl_views.SIDEBAR_W + w) / 2.0
            assert (cluster_left + cluster_right) / 2.0 == pytest.approx(content_cx), \
                f"cluster not centered on the content region at width {w}"

    def test_cluster_never_crosses_the_sidebar(self):
        for w in (1440.0, 1280.0, 940.0, 856.0, 800.0, 760.0):
            px, _, _, _ = sl_views.dock_cluster_rect(w, 800)
            home_left = px - self._CLUSTER_PAD
            assert home_left >= sl_views.SIDEBAR_W + sl_views.PILL_FLOAT - 1e-6, \
                f"home circle crosses the sidebar at width {w}"

    def test_cluster_shrinks_only_as_last_resort(self):
        _, _, pw_940, _ = sl_views.dock_cluster_rect(940, 800)
        assert pw_940 == sl_views.DOCK_SLOT_W, "940pt still fits the design-width cluster"
        px8, _, pw8, _ = sl_views.dock_cluster_rect(800, 800)
        assert pw8 < sl_views.DOCK_SLOT_W, "800pt is where the cluster starts shrinking"
        search_right = px8 + pw8 + self._CLUSTER_PAD
        assert search_right <= 800.0 - sl_views.PILL_FLOAT + 1e-6, \
            "shrunk cluster keeps the right float margin"


class TestGlassSurfaces:
    """Liquid Glass: app-declared glass regions via the native-controls bridge."""

    def test_login_field_glass_container_borderless_field(self, app_ctx, monkeypatch):
        app, ctx, _ = app_ctx
        bridge = _FakeNativeBridge()
        monkeypatch.setattr(app_main, "native_controls", lambda: bridge)

        _tick(app, ctx, 2)

        containers = [g for g in bridge.glass
                      if g.frame == (450.0, 420.0, 380.0, 40.0) and g.style == "regular"]
        assert len(containers) == 1
        container = containers[0]
        assert container.corner_radius == 20.0
        field = bridge.created[0]
        assert field.within is container
        assert field.bordered is False

    def test_authed_chrome_uses_scene_tint_not_native_glass(self, app_ctx, monkeypatch):
        """Live bug: NSGlassEffectView plates composite ABOVE the Metal scene,
        so every scene glyph under them was backdrop-blurred — sidebar nav and
        player controls unreadable. Text-bearing chrome now draws its material
        as a scene tint plate (same layer as the text → crisp by
        construction). Native glass stays only behind NATIVE content (login
        capsules, sheet controls)."""
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        bridge = _FakeNativeBridge()
        monkeypatch.setattr(app_main, "native_controls", lambda: bridge)

        _tick(app, ctx, 2)

        assert bridge.glass == []  # no native plates for sidebar/player pill
        assert app.glass_active is True
        # Round 67: the library plate is the search-anchored popup — its
        # scene-drawn border ring + translucent fill ARE the material
        # (TestSidebarLiquidGlass pins the full construction).
        app.search_expanded = True
        app.invalidate()
        _tick(app, ctx, 1)
        rects = _nodes(scene_buffer, RectNode)
        px, py, pw, ph = sl_views.library_panel_rect(app, 1280.0, 800.0)
        rrects = _nodes(scene_buffer, RoundedRectNode)
        assert any((n.x, n.y, n.width, n.height) == (px, py, pw, ph)
                   and n.color_rgba == sl_views.GLASS_BORDER for n in rrects), \
            "the library popup needs its scene-drawn glass plate"
        # Round 8: the full-width bar is a centered floating capsule — its
        # border ring is a rounded rect at the pill rect, radius from the
        # Liquid Glass size rule (round 34), with the glass specular highlight
        # just inside its top edge and a soft shadow.
        px, py, pw, ph = sl_views.pill_rect(1280, 800)
        rrects = _nodes(scene_buffer, RoundedRectNode)
        assert any(n.color_rgba == sl_views.GLASS_BORDER and n.x == px and n.y == py
                   and n.width == pw and n.height == ph
                   and n.radius == sl_views.glass_silhouette_radius(ph)
                   for n in rrects), "player pill needs its silhouette border ring"
        assert any(n.color_rgba == sl_views.GLASS_HIGHLIGHT and n.y == py + 1
                   and px < n.x < px + pw and n.height == 1 for n in rects), \
            "player pill needs its specular top highlight"
        assert any(n.color_rgba[0] == 0 and n.color_rgba[3] > 0
                   and n.width == pw and py < n.y <= py + 5 for n in rrects), \
            "player pill needs its soft shadow plates"
        # No opaque or full-width chrome backgrounds under the floating pill,
        # and no opaque sidebar backing behind the glass rail.
        assert [n for n in rects if n.color_rgba == (9, 9, 9, 255)
                and n.width == sl_views.SIDEBAR_W] == []
        assert [n for n in rects if n.width == 1280 and n.y >= 700] == []

    def test_glass_active_suppresses_drawn_backgrounds(self, app_ctx, monkeypatch):
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        monkeypatch.setattr(app_main, "native_controls", lambda: _FakeNativeBridge())

        _tick(app, ctx, 2)

        rects = _nodes(scene_buffer, RectNode)
        sidebar_bg = [n for n in rects if n.color_rgba == (9, 9, 9, 255)
                      and n.width == sl_views.SIDEBAR_W and n.height == 800]
        bar_bg = [n for n in rects if n.width == 1280 and n.y >= 700]
        assert sidebar_bg == []
        assert bar_bg == []

    def test_glass_material_renders_without_bridge(self, app_ctx, monkeypatch):
        """Round 7: the simulated-glass material is scene-drawn, so bridgeless
        hosts (Linux/headless) get the same sidebar/bar plates — no opaque
        fallback blocks."""
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        monkeypatch.setattr(app_main, "native_controls", lambda: None)

        _tick(app, ctx, 2)

        app.search_expanded = True
        app.invalidate()
        _tick(app, ctx, 1)
        rects = _nodes(scene_buffer, RectNode)
        lx, ly, lw, lh = sl_views.library_panel_rect(app, 1280.0, 800.0)
        assert any((n.x, n.y, n.width, n.height) == (lx, ly, lw, lh)
                   and n.color_rgba == sl_views.GLASS_BORDER
                   for n in _nodes(scene_buffer, RoundedRectNode)), \
            "bridgeless hosts get the same glass library popup"
        px, py, pw, ph = sl_views.pill_rect(1280, 800)
        assert any(n.color_rgba == sl_views.GLASS_BORDER and n.x == px and n.y == py
                   and n.width == pw and n.height == ph
                   for n in _nodes(scene_buffer, RoundedRectNode)), \
            "bridgeless hosts get the same floating pill"
        assert [n for n in rects if n.color_rgba == (9, 9, 9, 255)
                and n.width == sl_views.SIDEBAR_W] == []
        assert [n for n in rects if n.width == 1280 and n.y >= 700] == []
        assert app.glass_active is False

    def test_content_flows_under_floating_pill(self, app_ctx, monkeypatch):
        """The player pill is simulated glass on every host, so content flows
        under it everywhere (no opaque bridgeless bar to cull against)."""
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        app.view = "library"
        app.playlists = tuple(_playlist(f"Mix {i:02d}") for i in range(48))
        app.content_scroll = 400.0
        monkeypatch.setattr(app_main, "native_controls", lambda: None)

        _tick(app, ctx, 2)

        frame = scene_buffer.latest_frame()
        assert frame is not None
        card_bottoms = [node.y + node.height for node in frame.nodes
                        if isinstance(node, RoundedRectNode)
                        and node.width == sl_views.CARD_W and node.height == sl_views.CARD_H
                        and node.x >= sl_views.SIDEBAR_W]
        assert card_bottoms
        assert max(card_bottoms) > 800.0 - sl_views.DOCK_H

    def test_save_button_native_glass_replaces_drawn(self, app_ctx, monkeypatch):
        app, ctx, scene_buffer = app_ctx
        bridge = _FakeNativeBridge()
        monkeypatch.setattr(app_main, "native_controls", lambda: bridge)

        _tick(app, ctx, 2)

        capsules = [g for g in bridge.glass if g.frame == (580.0, 476.0, 120.0, 40.0)]
        assert len(capsules) == 1
        assert capsules[0].corner_radius == 20.0
        save = [b for b in bridge.buttons if b.title == "Save"]
        assert len(save) == 1
        assert save[0].within is capsules[0]
        assert "Save" not in _texts(scene_buffer)  # drawn label replaced by the NSButton
        actions = {region.action for region in app._hits}
        assert "save_client_id" not in actions  # native button owns the click now

    def test_save_button_enabled_follows_draft(self, app_ctx, monkeypatch):
        app, ctx, _ = app_ctx
        bridge = _FakeNativeBridge()
        monkeypatch.setattr(app_main, "native_controls", lambda: bridge)

        _tick(app, ctx, 2)
        save = bridge.buttons[0]
        assert save.enabled is False  # empty draft

        app.client_id_draft = "abc123"
        app.invalidate()
        _tick(app, ctx, 2)
        assert save.enabled is True

    def test_connect_button_native_glass_when_client_id_saved(self, app_ctx, monkeypatch):
        app, ctx, scene_buffer = app_ctx
        app.client_id = "cid-123"
        bridge = _FakeNativeBridge()
        monkeypatch.setattr(app_main, "native_controls", lambda: bridge)

        _tick(app, ctx, 2)

        capsules = [g for g in bridge.glass if g.frame == (530.0, 336.0, 220.0, 48.0)]
        assert len(capsules) == 1
        assert capsules[0].corner_radius == 24.0
        connect = [b for b in bridge.buttons if b.title == "Connect Spotify"]
        assert len(connect) == 1
        assert connect[0].within is capsules[0]
        assert connect[0].enabled is True
        assert "Connect Spotify" not in _texts(scene_buffer)
        assert "start_login" not in {region.action for region in app._hits}

    def test_capsule_tint_lifts_glass_on_dark_backdrop(self, app_ctx, monkeypatch):
        app, ctx, scene_buffer = app_ctx
        bridge = _FakeNativeBridge()
        monkeypatch.setattr(app_main, "native_controls", lambda: bridge)

        _tick(app, ctx, 2)

        tints = [n for n in _nodes(scene_buffer, RoundedRectNode)
                 if n.color_rgba == sl_views.GLASS_TINT
                 and (n.x, n.y, n.width, n.height) == (450.0, 420.0, 380.0, 40.0)]
        assert len(tints) == 1
        assert tints[0].radius == 20.0

    def test_no_capsule_tint_in_drawn_fallback(self, app_ctx, monkeypatch):
        app, ctx, scene_buffer = app_ctx
        monkeypatch.setattr(app_main, "native_controls", lambda: None)

        _tick(app, ctx, 2)

        tints = [n for n in _nodes(scene_buffer, RoundedRectNode)
                 if n.color_rgba == sl_views.GLASS_TINT]
        assert tints == []
        assert "Save" in _texts(scene_buffer)  # drawn fallback intact

    def test_glass_destroyed_when_bridge_goes_away(self, app_ctx, monkeypatch):
        """Bridge loss must destroy live native surfaces. Authed chrome no
        longer creates any (scene tint plates replaced it), so this pins the
        contract on the login wall's capsules, which stay native."""
        app, ctx, _ = app_ctx
        app.client_id = "cid-123"  # connect capsule lives on the login wall
        bridge = _FakeNativeBridge()
        monkeypatch.setattr(app_main, "native_controls", lambda: bridge)
        _tick(app, ctx, 2)
        surfaces = list(bridge.glass)
        assert surfaces

        bridge.available = False
        app.invalidate()
        _tick(app, ctx, 2)

        assert all(surface.destroyed for surface in surfaces)
        assert app.glass_active is False


class _FakeFrame:
    """Records the scene calls the glass recipe makes (frame API surface only)."""

    def __init__(self) -> None:
        self.rects: list[tuple] = []
        self.rounded: list[tuple] = []

    def rect(self, *, x, y, width, height, color, z_index):
        self.rects.append((x, y, width, height, color, z_index))

    def rounded_rect(self, *, x, y, width, height, radius, color, z_index):
        self.rounded.append((x, y, width, height, radius, color, z_index))


class TestSimulatedGlass:
    """Round 7: native glass blurs Metal scene text, so glass over content is
    SIMULATED in-scene — translucent fill, hairline border, specular top
    highlight, soft shadow. `_glass_plate` is the one canonical recipe."""

    def test_glass_plate_composition(self):
        f = _FakeFrame()
        sl_views._glass_plate(f, 100.0, 50.0, 180.0, 236.0, radius=14.0, z=2)

        shadows = [r for r in f.rounded
                   if r[5][:3] == (0, 0, 0) and r[5][3] > 0]
        assert len(shadows) == 2, "soft shadow = two stacked dark plates"
        assert all(s[1] > 50.0 for s in shadows), "shadows offset downward"
        assert all(s[4] == 14.0 for s in shadows)

        border = [r for r in f.rounded
                  if (r[0], r[1], r[2], r[3], r[4]) == (100.0, 50.0, 180.0, 236.0, 14.0)]
        assert len(border) == 1, "hairline border ring at the plate rect"
        assert border[0][5][:3] == (255, 255, 255)
        assert 16 <= border[0][5][3] <= 64

        fill = [r for r in f.rounded
                if (r[0], r[1], r[2], r[3], r[4]) == (101.0, 51.0, 178.0, 234.0, 13.0)]
        assert len(fill) == 1, "translucent fill inset 1px inside the border"
        assert fill[0][5][:3] == (255, 255, 255)
        assert 8 <= fill[0][5][3] <= 40

        highlight = [r for r in f.rects
                     if r[3] <= 1.5 and r[4][:3] == (255, 255, 255) and r[4][3] >= 40]
        assert highlight, "specular 1px top highlight"
        # Round 27: the sheen is a silhouette-clipped falloff (thin rows
        # fading to zero), not one hard-edged slab.
        sheen = [r for r in f.rects
                 if r[4][:3] == (255, 255, 255) and 0 < r[4][3] <= 20]
        assert sheen, "subtle sheen falloff under the top edge"
        assert all(r[3] <= 6 for r in sheen), "sheen is thin rows, not a slab"
        assert sum(r[3] for r in sheen) >= 20, "rows cover the sheen band"

    def test_glass_plate_hover_lifts(self):
        resting, hovering = _FakeFrame(), _FakeFrame()
        sl_views._glass_plate(resting, 0.0, 0.0, 100.0, 100.0, radius=12.0, z=2, hovering=False)
        sl_views._glass_plate(hovering, 0.0, 0.0, 100.0, 100.0, radius=12.0, z=2, hovering=True)

        def alphas(f):
            border = [r for r in f.rounded if (r[0], r[1]) == (0.0, 0.0) and r[5][:3] == (255, 255, 255)]
            fill = [r for r in f.rounded if r[0] == 1.0 and r[5][:3] == (255, 255, 255)]
            return border[0][5][3], fill[0][5][3]

        rest_border, rest_fill = alphas(resting)
        hov_border, hov_fill = alphas(hovering)
        assert hov_fill > rest_fill, "hover raises the fill (the light lift)"
        assert hov_border > rest_border, "hover sharpens the hairline"

    def test_glass_plate_shadow_optional(self):
        f = _FakeFrame()
        sl_views._glass_plate(f, 0.0, 0.0, 100.0, 40.0, radius=8.0, z=2, shadow=False)
        assert [r for r in f.rounded if r[5][:3] == (0, 0, 0)] == []
        assert any(r[5][:3] == (255, 255, 255) for r in f.rounded)

    def test_cards_are_glass_plates_not_flat_blocks(self, app_ctx):
        """The round-6c screenshot: cards read as opaque dark slabs. They are
        now simulated-glass plates (radius 14) with shadow + hairline."""
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        profile = sl_models.Profile(id="u1", display_name="Alec", email=None,
                                    image_url=None, product="premium")
        track = _track("Song One", _artist("Artist One"), _album("Album", _artist("Artist One")))

        class _Client:
            def me(self): return profile
            def my_playlists(self, *, limit=50): return []
            def top_tracks(self, *, limit=20): return [track]
            def new_releases(self, *, limit=20): return []
            def top_artists(self, *, limit=20): return []

        app._client = _Client()
        app._apply_result("bootstrap", app._job_bootstrap())
        _tick(app, ctx, 2)

        x0 = sl_views.CONTENT_PAD
        card_y = 24.0 + 46 + 32  # greeting, then "Top tracks" section title
        cards = [n for n in _nodes(scene_buffer, RoundedRectNode)
                 if (n.x, n.y, n.width, n.height) == (x0, card_y, sl_views.CARD_W, sl_views.CARD_H)]
        assert len(cards) == 1, "card hairline border ring"
        border = cards[0]
        assert border.radius == sl_views.CARD_RADIUS
        assert border.color_rgba[:3] == (255, 255, 255)
        assert border.color_rgba[3] <= 64, "glass hairline, not an opaque slab"
        fills = [n for n in _nodes(scene_buffer, RoundedRectNode)
                 if (n.x, n.y) == (x0 + 1, card_y + 1)
                 and n.width == sl_views.CARD_W - 2 and n.height == sl_views.CARD_H - 2]
        assert len(fills) == 1, "card translucent fill"
        assert fills[0].color_rgba[:3] == (255, 255, 255)
        assert fills[0].color_rgba[3] <= 40
        shadows = [n for n in _nodes(scene_buffer, RoundedRectNode)
                   if n.color_rgba[:3] == (0, 0, 0) and n.color_rgba[3] > 0
                   and n.y > card_y and n.width == sl_views.CARD_W]
        assert shadows, "card soft shadow"
        # The flat-block era is over: no opaque card-colored plate at the rect.
        assert [n for n in _nodes(scene_buffer, RoundedRectNode)
                if (n.x, n.y) == (x0, card_y)
                and n.color_rgba in (sl_views.CARD_BG, sl_views.CARD_HOVER_BG)] == []

    def test_notices_stay_readable_over_glass(self, app_ctx):
        """Degraded-section notes (round 6c) sit on the backdrop above the
        greeting; the glass recipe must not swallow them."""
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True

        class _Client:
            def _denied(self, *args, **kwargs):
                raise sl_api.ApiError(sl_api.ErrorKind.API, "403: Forbidden", status=403)
            me = my_playlists = top_tracks = new_releases = top_artists = _denied

        app._client = _Client()
        app._apply_result("bootstrap", app._job_bootstrap())
        _tick(app, ctx, 2)

        texts = _texts(scene_buffer)
        assert any("Couldn't load new releases right now" in t for t in texts)


class TestEmbeddedLogin:
    """Embedded Spotify authorize flow: WKWebView in-app, redirect intercepted."""

    def _tokens(self):
        body = json.dumps({
            "access_token": "at-1", "token_type": "Bearer", "expires_in": 3600,
            "refresh_token": "rt-1", "scope": "user-read-private",
        })
        return sl_oauth.parse_token_response(body, now=time.time())

    def _start(self, app_ctx, monkeypatch):
        app, ctx, scene_buffer = app_ctx
        app.client_id = "cid-123"
        bridge = _FakeNativeBridge()
        monkeypatch.setattr(app_main, "native_controls", lambda: bridge)
        _tick(app, ctx, 2)
        app._dispatch_action("start_login", None, 0.0)
        return app, ctx, scene_buffer, bridge

    def _pump(self, app, ctx, predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            _tick(app, ctx, 1)
            if predicate():
                return True
            time.sleep(0.005)
        return predicate()

    def test_connect_opens_embedded_web_view(self, app_ctx, monkeypatch):
        app, ctx, scene_buffer, bridge = self._start(app_ctx, monkeypatch)

        assert len(bridge.web_views) == 1
        view = bridge.web_views[0]
        assert view.frame == (0.0, 0.0, 1280.0, 800.0)
        assert view.redirect_prefix == "http://127.0.0.1:8888/callback"
        assert len(view.loaded_urls) == 1
        url = view.loaded_urls[0]
        assert url.startswith("https://accounts.spotify.com/authorize?")
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        assert params["client_id"] == ["cid-123"]
        assert params["code_challenge_method"] == ["S256"]
        assert app.auth_working is True
        assert app._login_receiver is None  # loopback receiver not needed in-app
        cancel = [b for b in bridge.buttons if b.title == "Cancel"]
        assert len(cancel) == 1

        _tick(app, ctx, 1)
        # Embedded view owns the screen; the drawn browser-wait UI stays undrawn.
        assert not any("Waiting for sign-in" in t for t in _texts(scene_buffer))
        connect = [b for b in bridge.buttons if b.title == "Connect Spotify"]
        assert connect[0].destroyed is True

    def test_embedded_redirect_completes_pkce_and_logs_in(self, app_ctx, monkeypatch):
        app, ctx, _, bridge = self._start(app_ctx, monkeypatch)
        monkeypatch.setattr(app, "_begin_session",
                            lambda tokens: setattr(app, "authenticated", True))
        captured = {}

        def fake_exchange(*, client_id, redirect_uri, code, verifier, **_kw):
            captured.update(client_id=client_id, redirect_uri=redirect_uri,
                            code=code, verifier=verifier)
            return self._tokens()

        monkeypatch.setattr(sl_oauth, "exchange_code", fake_exchange)
        view = bridge.web_views[0]
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(view.loaded_urls[0]).query)["state"][0]

        view.on_redirect(f"http://127.0.0.1:8888/callback?code=CODE42&state={state}")

        assert self._pump(app, ctx, lambda: app.authenticated)
        assert captured == {"client_id": "cid-123",
                            "redirect_uri": "http://127.0.0.1:8888/callback",
                            "code": "CODE42",
                            "verifier": captured["verifier"]}
        assert captured["verifier"]  # PKCE verifier carried through
        assert view.destroyed is True
        assert app.auth_working is False
        assert app.auth_error == ""

    def test_embedded_state_mismatch_rejected(self, app_ctx, monkeypatch):
        app, ctx, _, bridge = self._start(app_ctx, monkeypatch)
        called = []
        monkeypatch.setattr(sl_oauth, "exchange_code",
                            lambda **kw: called.append(kw) or self._tokens())
        view = bridge.web_views[0]

        view.on_redirect("http://127.0.0.1:8888/callback?code=x&state=forged")

        assert self._pump(app, ctx, lambda: not app.auth_working)
        assert app.authenticated is False
        assert "state" in app.auth_error.lower()
        assert called == []  # token exchange never runs on a forged callback
        assert view.destroyed is True

    def test_native_cancel_button_dismisses(self, app_ctx, monkeypatch):
        app, ctx, _, bridge = self._start(app_ctx, monkeypatch)
        view = bridge.web_views[0]
        cancel = [b for b in bridge.buttons if b.title == "Cancel"][0]
        capsule = [g for g in bridge.glass if g.frame == (1174.0, 16.0, 90.0, 36.0)][0]

        cancel.on_press()

        assert view.destroyed is True
        assert cancel.destroyed is True
        assert capsule.destroyed is True
        assert app.auth_working is False
        assert app.authenticated is False

    def test_cancel_without_redirect_leaves_inline_hint(self, app_ctx, monkeypatch):
        """Alec's round-3 dummy-id run: Spotify dead-ended on its own plain-text
        `client_id: Invalid` page (its authorize page defers client validation
        until after IdP sign-in) and Cancel returned to a SILENT wall. A sheet
        that closes without a redirect intercept leaves a one-line hint
        instead — the most likely culprit is the Client ID."""
        app, ctx, _, bridge = self._start(app_ctx, monkeypatch)
        cancel = [b for b in bridge.buttons if b.title == "Cancel"][0]

        cancel.on_press()

        assert "didn't complete" in app.auth_error
        assert "Client ID" in app.auth_error

    def test_hint_cleared_on_next_login_attempt(self, app_ctx, monkeypatch):
        """The hint must not poison the retry: starting login again clears it."""
        app, ctx, _, bridge = self._start(app_ctx, monkeypatch)
        cancel = [b for b in bridge.buttons if b.title == "Cancel"][0]
        cancel.on_press()
        assert app.auth_error

        app._dispatch_action("start_login", None, 0.0)

        assert app.auth_error == ""

    def test_successful_redirect_leaves_no_hint(self, app_ctx, monkeypatch):
        """The hint is only for a redirect-less close: a completed intercept
        that then fails PKCE keeps the SPECIFIC exchange error instead."""
        app, ctx, _, bridge = self._start(app_ctx, monkeypatch)
        monkeypatch.setattr(sl_oauth, "exchange_code",
                            lambda **kw: (_ for _ in ()).throw(
                                sl_oauth.OAuthError("invalid_client")))
        view = bridge.web_views[0]
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(view.loaded_urls[0]).query)["state"][0]

        view.on_redirect(f"http://127.0.0.1:8888/callback?code=CODE42&state={state}")

        assert self._pump(app, ctx, lambda: not app.auth_working)
        assert app.auth_error == "invalid_client"

    def test_cancel_discards_pending_redirect_callback(self, app_ctx, monkeypatch):
        """A redirect intercepted in the same tick window as a Cancel must not
        still fire the token exchange afterwards: cancel wins and discards the
        stashed callback. Without the guard, the next tick's worker-results
        pass picks the callback up and logs the user in AFTER they bailed."""
        app, ctx, _, bridge = self._start(app_ctx, monkeypatch)
        submitted = []
        monkeypatch.setattr(app.worker, "submit",
                            lambda label, fn: submitted.append(label))
        view = bridge.web_views[0]
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(view.loaded_urls[0]).query)["state"][0]
        cancel = [b for b in bridge.buttons if b.title == "Cancel"][0]

        view.on_redirect(f"http://127.0.0.1:8888/callback?code=CODE42&state={state}")
        cancel.on_press()  # same tick window: cancel must win
        _tick(app, ctx, 2)

        assert app._embedded_callback is None
        assert submitted == []  # exchange never submitted after cancel
        assert app.authenticated is False

    def test_cancel_rides_glass_capsule(self, app_ctx, monkeypatch):
        """Cancel must be visible over arbitrary page content: it rides its own
        frosted capsule (same construction as Save/Connect) instead of floating
        as bare text over the web view."""
        app, ctx, _, bridge = self._start(app_ctx, monkeypatch)

        capsules = [g for g in bridge.glass if g.frame == (1174.0, 16.0, 90.0, 36.0)]
        assert len(capsules) == 1
        assert capsules[0].corner_radius == 18.0
        cancel = [b for b in bridge.buttons if b.title == "Cancel"]
        assert len(cancel) == 1
        assert cancel[0].within is capsules[0]

    def test_back_button_top_left_in_own_capsule(self, app_ctx, monkeypatch):
        """Back sits top-LEFT (Cancel keeps top-right), same frosted-capsule
        family, and starts quiet — there is no history to go back to yet."""
        app, ctx, _, bridge = self._start(app_ctx, monkeypatch)

        capsules = [g for g in bridge.glass if g.frame == (16.0, 16.0, 90.0, 36.0)]
        assert len(capsules) == 1
        assert capsules[0].corner_radius == 18.0
        back = [b for b in bridge.buttons if b.title == "Back"]
        assert len(back) == 1
        assert back[0].within is capsules[0]
        assert back[0].enabled is False

    def test_back_enabled_follows_can_go_back(self, app_ctx, monkeypatch):
        app, ctx, _, bridge = self._start(app_ctx, monkeypatch)
        back = [b for b in bridge.buttons if b.title == "Back"][0]
        view = bridge.web_views[0]

        view.can_go_back = True
        view.on_navigation_state()
        assert back.enabled is True

        view.can_go_back = False
        view.on_navigation_state()
        assert back.enabled is False

    def test_back_press_goes_back_in_web_view(self, app_ctx, monkeypatch):
        app, ctx, _, bridge = self._start(app_ctx, monkeypatch)
        back = [b for b in bridge.buttons if b.title == "Back"][0]
        view = bridge.web_views[0]

        back.on_press()

        assert view.went_back == 1

    def test_back_destroyed_with_the_sheet(self, app_ctx, monkeypatch):
        app, ctx, _, bridge = self._start(app_ctx, monkeypatch)
        back = [b for b in bridge.buttons if b.title == "Back"][0]
        capsule = [g for g in bridge.glass if g.frame == (16.0, 16.0, 90.0, 36.0)][0]
        cancel = [b for b in bridge.buttons if b.title == "Cancel"][0]

        cancel.on_press()

        assert back.destroyed is True
        assert capsule.destroyed is True

    def test_sheet_controls_follow_window_resize(self, app_ctx, monkeypatch):
        """Mac round-3: Cancel rendered ~22pt right of its design frame — the
        sheet geometry is baked at creation and never re-applied on window
        resize (the web view and its capsules sit outside the per-render
        syncs). Re-apply every render like the other native frames."""
        app, ctx, _, bridge = self._start(app_ctx, monkeypatch)
        view = bridge.web_views[0]
        cancel_capsule = [g for g in bridge.glass
                          if g.frame == (1174.0, 16.0, 90.0, 36.0)][0]
        cancel = [b for b in bridge.buttons if b.title == "Cancel"][0]
        back = [b for b in bridge.buttons if b.title == "Back"][0]
        back_capsule = [g for g in bridge.glass if g.frame == (16.0, 16.0, 90.0, 36.0)][0]

        ctx.logical_width_px = 1000.0
        app.invalidate()
        _tick(app, ctx, 2)

        assert view.frame == (0.0, 0.0, 1000.0, 800.0)
        assert cancel_capsule.frame == (894.0, 16.0, 90.0, 36.0)
        assert cancel.frame == (894.0, 16.0, 90.0, 36.0)
        assert back_capsule.frame == (16.0, 16.0, 90.0, 36.0)
        assert back.frame == (16.0, 16.0, 90.0, 36.0)

    def test_cancel_button_failure_falls_back_to_browser_job(self, app_ctx, monkeypatch):
        """Escape is suppressed by design while the sheet is live, so a Cancel
        that cannot be created leaves no way out: tear the web view down and
        use the browser flow, which has its own cancel path."""
        app, ctx, _ = app_ctx
        app.client_id = "cid-123"
        bridge = _FakeNativeBridge()
        bridge.button_error = RuntimeError("boom")
        monkeypatch.setattr(app_main, "native_controls", lambda: bridge)
        submitted = []
        monkeypatch.setattr(app.worker, "submit", lambda label, fn: submitted.append(label))

        app._dispatch_action("start_login", None, 0.0)

        assert submitted == ["login"]
        assert app.auth_working is True
        assert app._login_web_view is None
        assert bridge.web_views[0].destroyed is True  # sheet torn down, not orphaned

    def test_fallback_to_browser_job_without_bridge(self, app_ctx, monkeypatch):
        app, ctx, _ = app_ctx
        app.client_id = "cid-123"
        monkeypatch.setattr(app_main, "native_controls", lambda: None)
        submitted = []
        monkeypatch.setattr(app.worker, "submit", lambda label, fn: submitted.append(label))

        app._dispatch_action("start_login", None, 0.0)

        assert submitted == ["login"]
        assert app.auth_working is True

    def test_fallback_to_browser_job_when_web_view_fails(self, app_ctx, monkeypatch):
        app, ctx, _ = app_ctx
        app.client_id = "cid-123"
        bridge = _FakeNativeBridge()
        bridge.web_view_error = RuntimeError("native web view requires pyobjc-framework-WebKit")
        monkeypatch.setattr(app_main, "native_controls", lambda: bridge)
        submitted = []
        monkeypatch.setattr(app.worker, "submit", lambda label, fn: submitted.append(label))

        app._dispatch_action("start_login", None, 0.0)

        assert submitted == ["login"]
        assert bridge.web_views == []
        assert app.auth_working is True


class TestMcpHooks:
    """Agent-facing MCP surface: mcp_state snapshot + sl_* app tools."""

    def test_mcp_state_exposes_agent_surface(self, app_ctx):
        app, ctx, _ = app_ctx
        _tick(app, ctx, 2)

        state = app.mcp_state()
        assert state["view"] == "home"
        assert state["authenticated"] is False
        assert state["client_id_configured"] is False
        assert state["client_id_draft_len"] == 0  # length only, never the value
        assert state["native_field_active"] is False
        assert state["search_query"] == ""
        assert state["content_scroll"] == 0.0
        assert state["now_playing"] is None
        # Affordance discovery: the login view's actionable hit regions.
        assert "focus_client_id" in state["hit_actions"]

    def test_mcp_state_now_playing_summary(self, app_ctx):
        app, ctx, _ = app_ctx
        artist = _artist("Nirvana")
        album = _album("Nevermind", artist)
        device = sl_models.Device(id="d1", name="MacBook Pro", kind="Computer",
                                  is_active=True, is_restricted=False, volume_percent=65)
        app.player = sl_models.PlayerState(
            is_playing=True, progress_ms=61_000,
            track=_track("Lithium", artist, album, ms=257_000),
            device=device, shuffle=False, repeat="off")

        summary = app.mcp_state()["now_playing"]
        assert summary == {
            "track": "Lithium",
            "artists": "Nirvana",
            "duration_ms": 257_000,
            "progress_ms": 61_000,
            "is_playing": True,
            "device": "MacBook Pro",
        }

    def test_set_client_id_drawn_fallback(self, app_ctx):
        app, _, _ = app_ctx
        result = app.mcp_call("sl_set_client_id", {"value": "abc-123"})
        assert app.client_id_draft == "abc-123"
        assert result == {"client_id_draft_len": 7, "native_field_active": False}

    def test_set_client_id_native_field(self, app_ctx, monkeypatch):
        app, ctx, _ = app_ctx
        bridge = _FakeNativeBridge()
        monkeypatch.setattr(app_main, "native_controls", lambda: bridge)
        _tick(app, ctx, 1)
        field = bridge.created[0]

        result = app.mcp_call("sl_set_client_id", {"value": "abc-123"})
        assert field.value == "abc-123"
        assert app.client_id_draft == "abc-123"
        assert result["native_field_active"] is True

    def test_submit_client_id_saves_and_reports(self, app_ctx):
        app, _, _ = app_ctx
        app.mcp_call("sl_set_client_id", {"value": "  abc-123  "})
        result = app.mcp_call("sl_submit_client_id", {})
        assert app.client_id == "abc-123"
        assert sl_store.load_client_id(app.cfg_dir) == "abc-123"
        assert result == {"client_id_configured": True}

    def test_hooks_register_list_and_call_via_bridge(self, app_ctx):
        app, _, _ = app_ctx
        bridge = McpRuntimeBridge(
            app_id="test.spotify-light",
            granted_capabilities=set(MCP_CAPABILITIES),
            state_provider=lambda: {},
            app_call_timeout_s=5.0,
        )
        assert bridge.register_app_hooks(app) == 11, \
            "client-id pair, layout_set/align/attach/list/clear/export (rounds 31+37+41), " \
            "and effect_apply/remove/list (SL-34)"

        listing = bridge.dispatcher().handle_payload(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        wire = {tool["name"]: tool for tool in listing["result"]["tools"]}
        assert "sl_set_client_id" in wire and "sl_submit_client_id" in wire
        schema = wire["sl_set_client_id"]["inputSchema"]
        assert schema["required"] == ["value"]
        assert schema["properties"]["value"]["type"] == "string"

        stop = threading.Event()

        def _drain() -> None:
            import time

            while not stop.is_set():
                bridge.drain_app_calls()
                time.sleep(0.005)

        thread = threading.Thread(target=_drain, daemon=True)
        thread.start()
        try:
            response = bridge.dispatcher().handle_payload(
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "sl_set_client_id", "arguments": {"value": "abc-123"}}})
        finally:
            stop.set()
        payload = json.loads(response["result"]["content"][0]["text"])
        assert payload == {"client_id_draft_len": 7, "native_field_active": False}
        assert app.client_id_draft == "abc-123"

        bridge.drain_app_calls()  # refreshes the cached mcp_state snapshot
        state_response = bridge.dispatcher().handle_payload(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "app_state", "arguments": {}}})
        app_state = json.loads(state_response["result"]["content"][0]["text"])
        assert app_state["app"]["client_id_draft_len"] == 7
        assert app_state["app"]["view"] == "home"


# ---------------------------------------------------------------------------
# Retina art: decode at device pixels, not points
# ---------------------------------------------------------------------------


def _png_bytes(size: int, color=(200, 30, 30, 255)) -> bytes:
    import io

    from PIL import Image as _Image

    buf = io.BytesIO()
    _Image.new("RGBA", (size, size), color).save(buf, format="PNG")
    return buf.getvalue()


class TestRetinaArt:
    """On a 2x display a 132pt art slot needs 264px of decoded pixels; the
    scene node's point size is unchanged (the renderer stretches the payload
    over the node geometry)."""

    def test_art_fetch_decodes_at_backing_scale(self, app_ctx, monkeypatch):
        app, ctx, _buffer = app_ctx
        ctx.set_backing_scale_provider(lambda: 2.0)
        submitted: dict[str, object] = {}
        monkeypatch.setattr(app.worker, "submit", lambda name, fn: submitted.__setitem__(name, fn))

        url = "https://i.scdn.co/image/test640"
        assert app.art_for(url, 132) is None  # cache miss schedules a worker fetch

        job = submitted[f"art:{url}|264"]
        monkeypatch.setattr(sl_art, "_default_http_get", lambda _url: _png_bytes(640))
        _url, size, rgba = job()
        assert size == 264
        assert rgba.shape == (264, 264, 4)

        cached = app.art_for(url, 132)
        assert cached is not None
        assert cached.shape == (264, 264, 4)

    def test_art_fetch_defaults_to_point_size(self, app_ctx, monkeypatch):
        app, _ctx, _buffer = app_ctx
        submitted: dict[str, object] = {}
        monkeypatch.setattr(app.worker, "submit", lambda name, fn: submitted.__setitem__(name, fn))

        url = "https://i.scdn.co/image/test300"
        assert app.art_for(url, 132) is None
        assert f"art:{url}|132" in submitted

    def test_art_pick_target_scales_with_backing_scale(self, app_ctx):
        app, ctx, _buffer = app_ctx
        assert app._art_pick_target(180) == 180
        ctx.set_backing_scale_provider(lambda: 2.0)
        assert app._art_pick_target(180) == 360


class TestArtFailureBackoff:
    """Round 16 (overnight library-screenshot review): two cards sat on flat
    placeholder tiles. For art-less items that's the honest state — but a
    permanently failing image URL looked identical AND `art_for` re-submitted
    a network fetch on every redraw forever (the failure path only cleared
    the in-flight marker, so the next frame scheduled it again). Failures
    must back off for a TTL, then allow a retry; success clears the backoff."""

    def test_failed_fetch_backs_off_then_retries_after_ttl(self, app_ctx, monkeypatch):
        app, _ctx, _buffer = app_ctx
        submitted: dict[str, object] = {}
        monkeypatch.setattr(app.worker, "submit",
                            lambda name, fn: submitted.__setitem__(name, fn))
        url = "https://i.scdn.co/image/dead"
        assert app.art_for(url, 132) is None
        key = f"{url}|132"
        job = f"art:{key}"
        assert job in submitted, "first miss schedules the fetch"

        app._apply_result(job, sl_art.ArtError("404"))
        submitted.clear()
        assert app.art_for(url, 132) is None
        assert not submitted, "a fresh failure must not resubmit on the next redraw"

        app._art_failures[key] -= app_main.ART_FAIL_TTL_SECS + 1.0
        assert app.art_for(url, 132) is None
        assert job in submitted, "after the backoff TTL exactly one retry is allowed"

    def test_successful_fetch_clears_the_backoff(self, app_ctx, monkeypatch):
        app, _ctx, _buffer = app_ctx
        submitted: dict[str, object] = {}
        monkeypatch.setattr(app.worker, "submit",
                            lambda name, fn: submitted.__setitem__(name, fn))
        url = "https://i.scdn.co/image/flaky"
        assert app.art_for(url, 132) is None
        key = f"{url}|132"
        job = f"art:{key}"
        app._apply_result(job, sl_art.ArtError("boom"))
        assert key in app._art_failures

        monkeypatch.setattr(sl_art, "_default_http_get", lambda _u: _png_bytes(300))
        _u, size, rgba = submitted[job]()
        app._apply_result(job, (_u, size, rgba))
        assert key not in app._art_failures, "a landed fetch clears the backoff"
        assert app.art_for(url, 132) is not None


# ---------------------------------------------------------------------------
# Icon switch (Alec-approved): dock glyphs are Phosphor icons from the bundled
# TTFs — regular weight for nav/search/more/note, Phosphor-Fill for the
# transport play/prev/next — rendered through the same text path as prose, so
# macOS Metal and the headless CI rasterizer draw identical pixels. The
# round-23 ink-centroid contract carries over: each icon's INK centroid lands
# on its target center.
class TestIconFontResolution:
    """The bundled Phosphor fonts must be what the resolver picks — a missing
    file would silently fall back to a system font and draw .notdef boxes."""

    @staticmethod
    def _resolved(family: str) -> str:
        from luvatrix_core.core.ui_frame_renderer import _resolve_system_font_path
        return _resolve_system_font_path(family) or ""

    def test_phosphor_regular_resolves_to_the_bundled_file(self):
        path = self._resolved(sl_icons.ICON_FONT).replace("\\", "/")
        assert path.endswith("assets/fonts/Phosphor.ttf"), path

    def test_phosphor_fill_resolves_to_the_bundled_file(self):
        path = self._resolved(sl_icons.ICON_FONT_FILL).replace("\\", "/")
        assert path.endswith("assets/fonts/Phosphor-Fill.ttf"), path

    def test_every_dock_icon_is_covered_by_its_primary_font(self):
        from luvatrix_core.core import font_fallback
        for name, (ch, family) in sl_icons.GLYPHS.items():
            chain = font_fallback.get_font_chain(family, 17.0)
            assert chain.font_for(ch) is chain.primary, \
                f"{name} U+{ord(ch):04X} falls off the {family} primary"


class TestDockIconCentering:
    TOL = 1.5

    def _render_idle_dock(self, app, ctx, scene_buffer):
        app.authenticated = True
        app.view = "library"  # neither nav circle active → uniform SUBTEXT ink
        app.player = None
        _tick(app, ctx, 2)
        frame = scene_buffer.latest_frame()
        assert frame is not None
        return rasterize_scene_frame(frame), frame

    def _ink_centroid(self, img, box, mask):
        x0, y0, x1, y1 = box
        xs, ys = [], []
        for y in range(y0, y1):
            for x in range(x0, x1):
                r, g, b = (int(v) for v in img[y, x, :3])
                if mask(r, g, b, x, y):
                    xs.append(x)
                    ys.append(y)
        assert xs, f"no ink pixels found in {box}"
        return sum(xs) / len(xs), sum(ys) / len(ys)

    def _assert_centered(self, img, box, mask, target, label):
        cx, cy = self._ink_centroid(img, box, mask)
        tx, ty = target
        assert abs(cx - tx) <= self.TOL and abs(cy - ty) <= self.TOL, \
            f"{label} ink centroid ({cx:.2f}, {cy:.2f}) off target ({tx}, {ty})"

    @staticmethod
    def _bright(r, g, b, _x, _y) -> bool:
        return (r + g + b) / 3 >= 140

    def test_dock_icons_are_phosphor_glyphs(self, app_ctx):
        """Every dock glyph is the Phosphor icon char in its approved family,
        and no legacy text glyph survives the switch."""
        app, ctx, scene_buffer = app_ctx
        _, frame = self._render_idle_dock(app, ctx, scene_buffer)
        nodes = {n.text: n for n in frame.nodes
                 if isinstance(n, TextNode) and len(n.text) == 1}
        for name, (ch, family) in sl_icons.GLYPHS.items():
            node = nodes.get(ch)
            assert node is not None, f"{name} icon missing from the dock"
            assert node.font_family == family, \
                f"{name} icon renders in {node.font_family!r}, want {family!r}"
        legacy = {"⌂", "⚲", "…", "♪", ">"} & set(nodes)
        assert not legacy, f"legacy text glyphs still present: {legacy}"
        wide = [n.text for n in frame.nodes
                if isinstance(n, TextNode) and n.text in ("<<", ">>")]
        assert not wide, f"legacy transport glyphs still present: {wide}"

    def test_nav_circle_icons_center_on_their_circles(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        img, _ = self._render_idle_dock(app, ctx, scene_buffer)
        dpx, dpy, dpw, dph = sl_views.dock_cluster_rect(1280, 800)
        cy = dpy + dph / 2
        home_cx = dpx - sl_views.NAV_CIRCLE_GAP - sl_views.NAV_CIRCLE_R
        search_cx = dpx + dpw + sl_views.NAV_CIRCLE_GAP + sl_views.NAV_CIRCLE_R
        self._assert_centered(img, (int(home_cx) - 20, int(cy) - 20, int(home_cx) + 20,
                                    int(cy) + 20), self._bright, (home_cx, cy), "home")
        self._assert_centered(img, (int(search_cx) - 20, int(cy) - 20, int(search_cx) + 20,
                                    int(cy) + 20), self._bright, (search_cx, cy), "search")

    def test_overflow_icon_centers_on_its_circle(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        img, _ = self._render_idle_dock(app, ctx, scene_buffer)
        # Round 36: the circle lives at the shipped layout.toml position —
        # read its resolved rect rather than recomputing a natural.
        overflow = next(r for r in app._hits if r.action == "open_devices")
        ocx, cy = overflow.x + overflow.w / 2, overflow.y + overflow.h / 2
        self._assert_centered(img, (int(ocx) - 20, int(cy) - 20, int(ocx) + 20, int(cy) + 20),
                              self._bright, (ocx, cy), "overflow more")

    def test_transport_icons_center_on_their_hit_regions(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        img, _ = self._render_idle_dock(app, ctx, scene_buffer)
        hits = {r.action: r for r in app._hits}
        for action, label in (("prev", "skip-back"), ("next", "skip-forward")):
            r = hits[action]
            target = (r.x + r.w / 2, r.y + r.h / 2)
            self._assert_centered(img, (int(r.x), int(r.y), int(r.x + r.w), int(r.y + r.h)),
                                  self._bright, target, f"transport {label}")

    def test_play_icon_centers_on_its_circle(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        img, _ = self._render_idle_dock(app, ctx, scene_buffer)
        px, py, pw, ph = sl_views.pill_rect(1280, 800)
        play_cx, cy = px + pw - 72, py + ph / 2

        def dark_ink_in_disc(r, g, b, x, y):
            return ((r + g + b) / 3 < 80
                    and (x - play_cx) ** 2 + (y - cy) ** 2 <= 13 ** 2)

        self._assert_centered(img, (int(play_cx) - 14, int(cy) - 14, int(play_cx) + 14,
                                    int(cy) + 14), dark_ink_in_disc, (play_cx, cy), "play")

    def test_idle_note_icon_centers_on_its_tile(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        img, _ = self._render_idle_dock(app, ctx, scene_buffer)
        px, py, _, ph = sl_views.pill_rect(1280, 800)
        art = ph - 2 * sl_views.PILL_ART_INSET
        tile_c = (px + sl_views.PILL_ART_INSET + art / 2,
                  py + sl_views.PILL_ART_INSET + art / 2)
        # The note carries an intentional upward optical bias (round 28: it
        # read ~2px low): its centroid pin targets the biased placement,
        # not the geometric tile centre. The glyph is 36pt on the 84pt tile.
        _bias_x, bias_y = sl_views._ICON_OPTICAL_BIAS_EM[sl_icons.NOTE]
        target = (tile_c[0], tile_c[1] + bias_y * 36)
        self._assert_centered(img, (int(tile_c[0]) - 25, int(tile_c[1]) - 25,
                                    int(tile_c[0]) + 25, int(tile_c[1]) + 25),
                              self._bright, target, "idle note")

    def test_card_play_fab_uses_the_fill_icon(self, app_ctx):
        """Hovering a card shows the play FAB as the Phosphor-Fill play icon
        on the art's bottom-right corner (it was the text ">" glyph)."""
        app, ctx, scene_buffer = app_ctx
        artist = _artist("Nirvana")
        album = _album("Nevermind", artist)
        app.authenticated = True
        app.home_sections = sl_ui.build_home_sections(
            top_tracks=[], new_releases=[album], playlists=[], top_artists=[])
        _tick(app, ctx, 1)
        arts = [n for n in _nodes(scene_buffer, CpuLayerNode)
                if abs(n.width - (sl_views.CARD_ART - 24)) < 1.0]
        assert arts, "card art rendered"
        card_x, card_y = arts[0].x - 12.0, arts[0].y - 12.0
        app.input.state.mouse_x = card_x + 20.0
        app.input.state.mouse_y = card_y + 20.0
        app.invalidate()  # a real mousemove event would invalidate on its own
        _tick(app, ctx, 1)
        frame = scene_buffer.latest_frame()
        fabs = [n for n in frame.nodes
                if isinstance(n, TextNode) and n.text == sl_icons.PLAY
                and n.font_size_px == 18]
        assert fabs, "hovering a card shows the play FAB"
        assert fabs[0].font_family == sl_icons.ICON_FONT_FILL, \
            f"FAB renders in {fabs[0].font_family!r}"
        fx = card_x + sl_views.CARD_W - 28
        fy = card_y + sl_views.CARD_ART - 28
        assert abs(fabs[0].x - fx) < 16 and abs(fabs[0].y - fy) < 16, \
            f"FAB should sit at ({fx}, {fy}), got ({fabs[0].x}, {fabs[0].y})"


# ---------------------------------------------------------------------------
# Round 24 (Alec's eyeball pass on 1b71bac): "ghost corners" on the glass
# plates. The sheen band in _glass_plate is a SQUARE rect starting 2px inside
# the plate, so at rounded corners it pokes past the rounded silhouette and
# reads as bright nubs floating off the plate. The contract: pixels outside
# the rounded silhouette keep backdrop luminance; the sheen still reads
# along the straight top edge.
class TestGlassPlateSheen:

    class _Capture:
        def __init__(self):
            self.rrects = []
            self.rects = []

        def rounded_rect(self, **kw):
            self.rrects.append(kw)

        def rect(self, **kw):
            self.rects.append(kw)

    def _rasterize_plate(self, radius):
        cap = self._Capture()
        sl_views._glass_plate(cap, 100.0, 100.0, 200.0, 100.0, radius=radius, z=2)
        nodes = [RectNode(x=0, y=0, width=400, height=300,
                          color_rgba=(16, 16, 16, 255), z_index=0)]
        nodes += [RoundedRectNode(x=n["x"], y=n["y"], width=n["width"], height=n["height"],
                                  radius=n["radius"], color_rgba=n["color"],
                                  z_index=n["z_index"]) for n in cap.rrects]
        nodes += [RectNode(x=n["x"], y=n["y"], width=n["width"], height=n["height"],
                           color_rgba=n["color"], z_index=n["z_index"]) for n in cap.rects]
        frame = SceneFrame(revision=1, logical_width=400, logical_height=300,
                           display_width=400, display_height=300, ts_ns=0, nodes=tuple(nodes))
        return rasterize_scene_frame(frame)

    def test_sheen_stays_inside_rounded_silhouette(self):
        img = self._rasterize_plate(22.0)
        # Outside the r=22 arc (corner center (122,122)) but inside the old
        # square sheen band: no plate pixel may brighten these over backdrop.
        for x, y in ((102, 102), (103, 103), (104, 102), (102, 104), (105, 103),
                     (297, 102), (296, 103), (298, 104)):
            lum = int(img[y, x, :3].sum()) / 3
            assert lum <= 20, f"sheen leaks past the rounded corner at {(x, y)}: lum {lum}"
        # The sheen must still read along the straight top edge.
        top = int(img[103, 200, :3].sum()) / 3
        assert top >= 64, f"sheen band missing at the top edge: lum {top}"

    def test_sheen_inset_scales_with_corner_radius(self):
        # Pill-radius plate (r=32): the arc cuts deeper, so the leak points
        # sit further from the corner. Same contract.
        img = self._rasterize_plate(32.0)
        for x, y in ((104, 102), (106, 103), (108, 104), (110, 105)):
            lum = int(img[y, x, :3].sum()) / 3
            assert lum <= 20, f"r=32 sheen leaks at {(x, y)}: lum {lum}"
        top = int(img[103, 200, :3].sum()) / 3
        assert top >= 64, f"r=32 sheen missing at the top edge: lum {top}"


# ---------------------------------------------------------------------------
# Round 27 (Alec's eyeball pass on the icon build 0580d52): "looks like
# there's rectangles behind the pills." The r24 fix kept the square sheen
# band from poking PAST the silhouette, but the band itself is one hard-edged
# rect floating inside the plate interior — 14x18 inside the 44px nav
# circles, 414x27 across the pill — and reads as a rectangle behind the
# glyph. The contract: the sheen is a silhouette-clipped falloff — thin rows
# chord-clipped inside the corner arc, alpha ramping to zero — so no edge
# inside the plate can read as a rectangle.
class TestGlassSheenSilhouette:

    class _Capture:
        def __init__(self):
            self.rrects = []
            self.rects = []

        def rounded_rect(self, **kw):
            self.rrects.append(kw)

        def rect(self, **kw):
            self.rects.append(kw)

    def _sheen_rows(self, cap):
        # Round 28: the specular top highlight is now a segmented falloff
        # whose faded end segments share this alpha range; it occupies the
        # y+1 row (plates here are constructed at y=100), the sheen starts
        # at y+2 — keep the two elements separate.
        return [n for n in cap.rects
                if n["color"][:3] == (255, 255, 255)
                and 0 < n["color"][3] <= sl_views.GLASS_SHEEN[3]
                and n["y"] != 101.0]

    def test_sheen_is_thin_rows_fading_to_zero(self):
        cap = self._Capture()
        sl_views._glass_plate(cap, 100.0, 100.0, 44.0, 44.0, radius=22.0, z=2)
        rows = self._sheen_rows(cap)
        assert rows, "sheen missing"
        assert max(n["height"] for n in rows) <= 2, \
            "the sheen must be thin rows, not one hard-edged slab"
        rows.sort(key=lambda n: n["y"])
        alphas = [n["color"][3] for n in rows]
        assert alphas == sorted(alphas, reverse=True), \
            f"sheen alpha must fall monotonically, got {alphas}"
        assert alphas[-1] <= 2, \
            f"the sheen's bottom must fade out (last alpha {alphas[-1]}), " \
            "a hard bottom edge is the rectangle Alec sees"

    def test_sheen_rows_follow_the_corner_chord(self):
        cap = self._Capture()
        sl_views._glass_plate(cap, 100.0, 100.0, 44.0, 44.0, radius=22.0, z=2)
        for n in self._sheen_rows(cap):
            cy = n["y"] + n["height"] / 2 - 100.0
            if cy >= 22.0:
                continue
            chord = 22.0 - math.sqrt(max(0.0, 22.0 * 22.0 - (22.0 - cy) ** 2))
            assert n["x"] >= 100.0 + chord - 0.6, \
                f"row at depth {cy:.1f} starts at {n['x']}, left of the chord"
            assert n["x"] + n["width"] <= 100.0 + 44.0 - chord + 0.6, \
                f"row at depth {cy:.1f} ends past the chord"

    def _rasterize_plate(self, w, h, radius):
        cap = self._Capture()
        sl_views._glass_plate(cap, 100.0, 100.0, w, h, radius=radius, z=2)
        nodes = [RectNode(x=0, y=0, width=400, height=400,
                          color_rgba=(16, 16, 16, 255), z_index=0)]
        nodes += [RoundedRectNode(x=n["x"], y=n["y"], width=n["width"], height=n["height"],
                                  radius=n["radius"], color_rgba=n["color"],
                                  z_index=n["z_index"]) for n in cap.rrects]
        nodes += [RectNode(x=n["x"], y=n["y"], width=n["width"], height=n["height"],
                           color_rgba=n["color"], z_index=n["z_index"]) for n in cap.rects]
        frame = SceneFrame(revision=1, logical_width=400, logical_height=400,
                           display_width=400, display_height=400, ts_ns=0,
                           nodes=tuple(nodes))
        return rasterize_scene_frame(frame)

    def _max_steps(self, img, w, h):
        cy = 100 + int(h * 0.2)
        hstep = max(
            abs(int(img[cy, x + 1, :3].sum()) / 3 - int(img[cy, x, :3].sum()) / 3)
            for x in range(105 + 6, 105 + int(w) - 16))
        cx = 100 + int(w / 2)
        # Start below the specular top highlight: its 1px crisp line is
        # intentional; the rectangle comes from edges floating deeper down.
        vstep = max(
            abs(int(img[y + 1, cx, :3].sum()) / 3 - int(img[y, cx, :3].sum()) / 3)
            for y in range(106, 100 + int(h * 0.6)))
        return hstep, vstep

    def test_no_hard_sheen_edges_inside_the_plate(self):
        # A floating sheen edge steps ~9 lum (measured on the r26 build); a
        # clipped falloff steps <=1 per row.
        for w, h, r in ((200.0, 100.0, 22.0), (200.0, 100.0, 32.0), (44.0, 44.0, 22.0)):
            img = self._rasterize_plate(w, h, r)
            hstep, vstep = self._max_steps(img, w, h)
            assert hstep <= 3, f"{w}x{h} r={r}: horizontal sheen edge step {hstep}"
            assert vstep <= 2, f"{w}x{h} r={r}: vertical sheen edge step {vstep}"

    def test_sheen_still_reads_at_the_top(self):
        img = self._rasterize_plate(200.0, 100.0, 22.0)
        top = int(img[103, 200, :3].sum()) / 3
        assert top >= 64, f"sheen band missing at the top edge: lum {top}"


# ---------------------------------------------------------------------------
# Round 34 (Alec, Apple's Liquid Glass size-rule reference): big plates are
# NOT capsules. At small sizes the corner radius is h/2 (nav circles, the
# 64pt pill — full semicircular ends); past a height threshold the radius
# caps at a fixed value and the plate reads as a rounded rectangle with the
# reference's continuous-corner feel. The 108pt pill crosses the threshold;
# the sheen chord-clip and the specular must follow the capped arc (same
# construction, new radius — the round-24/27 pixel discipline still holds).
class TestGlassSizeRule:

    class _Capture:
        def __init__(self):
            self.rrects = []
            self.rects = []

        def rounded_rect(self, **kw):
            self.rrects.append(kw)

        def rect(self, **kw):
            self.rects.append(kw)

    def _rasterize_plate(self, w, h, radius):
        cap = self._Capture()
        sl_views._glass_plate(cap, 100.0, 100.0, w, h, radius=radius, z=2)
        nodes = [RectNode(x=0, y=0, width=400, height=400,
                          color_rgba=(16, 16, 16, 255), z_index=0)]
        nodes += [RoundedRectNode(x=n["x"], y=n["y"], width=n["width"], height=n["height"],
                                  radius=n["radius"], color_rgba=n["color"],
                                  z_index=n["z_index"]) for n in cap.rrects]
        nodes += [RectNode(x=n["x"], y=n["y"], width=n["width"], height=n["height"],
                           color_rgba=n["color"], z_index=n["z_index"]) for n in cap.rects]
        frame = SceneFrame(revision=1, logical_width=400, logical_height=400,
                           display_width=400, display_height=400, ts_ns=0,
                           nodes=tuple(nodes))
        return rasterize_scene_frame(frame)

    def _sheen_rows(self, cap):
        return [n for n in cap.rects
                if n["color"][:3] == (255, 255, 255)
                and 0 < n["color"][3] <= sl_views.GLASS_SHEEN[3]
                and n["y"] != 101.0]

    def test_rule_constants_come_from_the_reference(self):
        assert 24.0 <= sl_views.GLASS_RECT_RADIUS <= 32.0, \
            "the capped corner is the reference's r24-r32 continuous corner"
        assert 64.0 < sl_views.GLASS_CAPSULE_MAX_H < 108.0, \
            "the 64pt pill stays capsule; the round-32 108pt pill crosses"

    def test_capsule_at_and_below_the_threshold(self):
        rule = sl_views.glass_silhouette_radius
        assert rule(44.0) == 22.0, "nav circles keep r = h/2"
        assert rule(64.0) == 32.0, "the current pill keeps r = h/2"
        assert rule(sl_views.GLASS_CAPSULE_MAX_H) == sl_views.GLASS_CAPSULE_MAX_H / 2, \
            "the boundary itself is still a capsule"

    def test_capped_above_the_threshold(self):
        rule = sl_views.glass_silhouette_radius
        assert rule(sl_views.GLASS_CAPSULE_MAX_H + 0.5) == sl_views.GLASS_RECT_RADIUS
        assert rule(108.0) == sl_views.GLASS_RECT_RADIUS, "the big pill becomes a rect"
        assert rule(400.0) == sl_views.GLASS_RECT_RADIUS, "the cap never grows"

    def test_pill_silhouette_follows_the_rule_in_both_states(self, app_ctx):
        app, ctx, buf = app_ctx
        app.authenticated = True
        _tick(app, ctx, 2)
        px, py, pw, ph = sl_views.pill_rect(1280, 800)
        want = sl_views.glass_silhouette_radius(ph)
        rings = [n for n in _nodes(buf, RoundedRectNode)
                 if n.color_rgba == sl_views.GLASS_BORDER
                 and (n.x, n.y, n.width, n.height) == (px, py, pw, ph)]
        assert rings and all(n.radius == want for n in rings), "idle pill ring obeys the rule"
        nirvana = _artist("Nirvana")
        track = _track("Lithium", nirvana, _album("Nevermind", nirvana), ms=257_000)
        app.player = sl_models.PlayerState(is_playing=True, progress_ms=30_500,
                                           track=track, device=None, shuffle=False, repeat="off")
        app._player_synced_at = app.now_monotonic
        _tick(app, ctx, 2)
        rings = [n for n in _nodes(buf, RoundedRectNode)
                 if n.color_rgba == sl_views.GLASS_BORDER
                 and (n.x, n.y, n.width, n.height) == (px, py, pw, ph)]
        assert rings and all(n.radius == want for n in rings), \
            "playing pill ring obeys the same rule"

    def test_small_plates_do_not_cross(self, app_ctx):
        """Only the (big) pill's silhouette may change: the nav circles stay
        full capsules (r = h/2 = 22), the popup keeps r14. Round 42 (SL-28):
        the overflow ⋯ is a BARE glyph now — no capsule on its slot."""
        app, ctx, buf = app_ctx
        app.authenticated = True
        nirvana = _artist("Nirvana")
        track = _track("Lithium", nirvana, _album("Nevermind", nirvana), ms=257_000)
        app.devices = [
            sl_models.Device(id="d1", name="MacBook Pro", kind="Computer", is_active=True,
                             is_restricted=False, volume_percent=40),
        ]
        app.player = sl_models.PlayerState(is_playing=True, progress_ms=30_500,
                                           track=track, device=app.devices[0],
                                           shuffle=False, repeat="off")
        app._player_synced_at = app.now_monotonic
        app.show_devices = True
        _tick(app, ctx, 2)
        circles = [n for n in _nodes(buf, RoundedRectNode)
                   if n.width == 44.0 and n.height == 44.0 and n.radius == 22.0]
        assert len(circles) >= 2, "home/search circles stay capsule (r = h/2)"
        assert not any(n.x == 1208.0 and n.y == 28.0 for n in circles), \
            "SL-28: the overflow slot hosts no capsule — the ⋯ is a bare icon"
        popup = [n for n in _nodes(buf, RoundedRectNode)
                 if n.color_rgba == (18, 18, 18, 234) and n.width == 298]
        assert popup and {n.radius for n in popup} == {13.0}, \
            "the popup fill keeps r13 (its explicit r14 ring minus the 1px inset)"

    def test_capped_corner_keeps_the_sheen_discipline(self):
        """Pixel contract (round-24 discipline) on the capped arc: outside it
        the backdrop is untouched, and a point the capsule arc would leave
        empty now carries plate fill — that difference IS the rectangle."""
        radius = sl_views.glass_silhouette_radius(108.0)
        img = self._rasterize_plate(200.0, 108.0, radius)
        for x, y in ((102, 102), (103, 103), (104, 102), (105, 104), (297, 102), (296, 103)):
            lum = int(img[y, x, :3].sum()) / 3
            assert lum <= 20, f"sheen leaks past the capped corner at {(x, y)}: lum {lum}"
        # (114, 106): outside a capsule arc (center (154, 154), distance ~62.5
        # > 54) but inside the capped arc (center (128, 128), distance ~26.1
        # < 28) — the plate must be present here, or it is still a capsule.
        lum = int(img[106, 114, :3].sum()) / 3
        assert lum > 20, "the capped corner fills where the capsule would not"
        top = int(img[103, 200, :3].sum()) / 3
        assert top >= 64, f"sheen band missing at the top edge: lum {top}"

    def test_sheen_and_specular_follow_the_capped_arc(self):
        """Same chord-clip construction, new arc: rows above the corner clip
        against the r-cap, and the specular span insets from the r-cap."""
        radius = sl_views.glass_silhouette_radius(108.0)
        cap = self._Capture()
        sl_views._glass_plate(cap, 100.0, 100.0, 200.0, 108.0, radius=radius, z=2)
        for n in self._sheen_rows(cap):
            cy = n["y"] + n["height"] / 2 - 100.0
            if cy >= radius:
                continue
            chord = radius - math.sqrt(max(0.0, radius * radius - (radius - cy) ** 2))
            assert n["x"] >= 100.0 + chord - 0.6, \
                f"row at depth {cy:.1f} starts at {n['x']}, left of the capped chord"
            assert n["x"] + n["width"] <= 100.0 + 200.0 - chord + 0.6, \
                f"row at depth {cy:.1f} ends past the capped chord"
        specular = [n for n in cap.rects if n["y"] == 101.0 and n["color"][3] > 0]
        assert specular, "specular missing"
        assert min(n["x"] for n in specular) == pytest.approx(100.0 + radius * 0.7), \
            "the specular span insets from the capped arc, not the capsule's"


# ---------------------------------------------------------------------------
# Round 25 (Alec's eyeball pass on 1b71bac): the playback popup "doesn't work
# properly" — clicking its padding, gaps, or labels dismisses it. Root cause:
# the popup's glass plate registers no hit region, so clicks on dead space
# fall through _dispatch_click to the empty-space branch that closes the
# popup (and can bleed into content hits underneath the panel). The contract:
# clicks inside the plate are swallowed; only a click truly outside closes.
class TestPopupPlateSwallow:

    def _with_track(self, app, ctx, *, show_devices=False):
        app.authenticated = True
        nirvana = _artist("Nirvana")
        track = _track("Lithium", nirvana, _album("Nevermind", nirvana), ms=257_000)
        app.devices = [
            sl_models.Device(id="d1", name="MacBook Pro", kind="Computer", is_active=True,
                             is_restricted=False, volume_percent=40),
        ]
        app.player = sl_models.PlayerState(is_playing=True, progress_ms=30_500, track=track,
                                           device=app.devices[0], shuffle=True, repeat="context")
        app._player_synced_at = app.now_monotonic
        app.show_devices = show_devices
        _tick(app, ctx, 2)

    def test_clicks_on_popup_dead_space_do_not_dismiss_it(self, app_ctx):
        app, ctx, _buffer = app_ctx
        self._with_track(app, ctx, show_devices=True)

        popup_w, row_h, head_h = 300.0, 40.0, 148.0
        popup_h = head_h + row_h * 1 + 12  # one device
        # Round 41: the popup drops from the pill's bottom, right-aligned
        # to the attached overflow circle, menu-style.
        circle = next(r for r in app._hits if r.action == "open_devices")
        _, py, _, ph = sl_views.pill_rect(1280, 800)
        popup_x = circle.x + circle.w - popup_w
        popup_y = py + ph + 12.0

        # Bottom padding below the last device row: inside the plate, on no control.
        app._dispatch_click(popup_x + popup_w / 2, popup_y + popup_h - 4)
        assert app.show_devices is True, "clicking the popup's padding must not dismiss it"
        # The "Connect to a device" section title: a label, not a control.
        app._dispatch_click(popup_x + popup_w / 2, popup_y + 132)
        assert app.show_devices is True, "clicking a popup label must not dismiss it"
        # The gap between the volume bar and the Shuffle row.
        app._dispatch_click(popup_x + popup_w / 2, popup_y + 48)
        assert app.show_devices is True, "clicking a popup gap must not dismiss it"

        # A click truly outside the popup still dismisses it (round 41: the
        # dead strip between the sidebar and the popup, which now drops
        # from the pill's bottom edge).
        app._dispatch_click(350, 300)
        assert app.show_devices is False

    def test_popup_controls_still_win_over_the_plate(self, app_ctx, monkeypatch):
        app, ctx, _buffer = app_ctx
        self._with_track(app, ctx, show_devices=True)
        actions: list[str] = []
        monkeypatch.setattr(app, "_player_action", lambda fn: actions.append("player"))

        # Shuffle row hit: (popup_x+8, y1-5, popup_w-16, 30), y1 = popup_y + 48.
        circle = next(r for r in app._hits if r.action == "open_devices")
        _, py, _, ph = sl_views.pill_rect(1280, 800)
        popup_x = circle.x + circle.w - 300.0
        popup_y = py + ph + 12.0
        app._dispatch_click(popup_x + 40, popup_y + 48 + 10)
        assert actions == ["player"], "toggling Shuffle must still reach its control"
        assert app.show_devices is True, "toggles never dismiss the popup"


# ---------------------------------------------------------------------------
# Round 28, finding 1 (Alec on the #362 build): the overflow (⋯) button
# "needs several clicks" before the playback popup opens. These tests drive
# the exact click sequence through the real update path — synthetic HDI
# events → apply_hdi_events → _handle_input → _dispatch_click — to
# reproduce it. They pin the contract end-to-end: every click inside the
# circle toggles the popup, poll results that regrow the popup never close
# it, and the popup's hit regions can never cover the circle (so the r25
# dead-space swallow cannot eat the toggle) at any device count.
# ---------------------------------------------------------------------------

class TestOverflowClickSequence:
    # Overflow circle centre at 1280x800 (round 41: the shipped layout.toml
    # attach relationship parks it in the pill's top-right — (1208,28,44,44)).
    CIRCLE = (1230.0, 50.0)

    def _with_track(self, app, ctx, monkeypatch, *, devices=1, show_devices=False):
        app.authenticated = True
        artist = _artist("ANOTR")
        track = _track("Relax My Eyes", artist, _album("The Reset", artist), ms=243_000)
        app.devices = [
            sl_models.Device(id=f"d{i}", name=f"Device {i}", kind="Computer",
                             is_active=(i == 0), is_restricted=False, volume_percent=40)
            for i in range(devices)
        ]
        app.player = sl_models.PlayerState(
            is_playing=True, progress_ms=30_500, track=track,
            device=app.devices[0] if app.devices else None, shuffle=False, repeat="off")
        app._player_synced_at = app.now_monotonic
        app.show_devices = show_devices
        # Keep the worker out of the way: open_devices submits a poll, which
        # is irrelevant to the toggle contract.
        monkeypatch.setattr(app.worker, "submit", lambda label, job: None)
        _tick(app, ctx, 2)

    @staticmethod
    def _click(app, ctx, x, y):
        events = [
            HDIEvent(event_id=1, ts_ns=1, window_id="w", device="mouse",
                     event_type="pointer_move", status="OK",
                     payload={"x": x, "y": y, "buttons_mask": 0}),
            HDIEvent(event_id=2, ts_ns=2, window_id="w", device="mouse",
                     event_type="click", status="OK",
                     payload={"x": x, "y": y, "button": 0, "phase": "down", "click_count": 1}),
            HDIEvent(event_id=3, ts_ns=3, window_id="w", device="mouse",
                     event_type="click", status="OK",
                     payload={"x": x, "y": y, "button": 0, "phase": "up", "click_count": 1}),
        ]
        app.input.raw_events = lambda *args, **kwargs: list(events)
        try:
            _tick(app, ctx, 1)
        finally:
            del app.input.raw_events  # back to the class-level method

    def test_circle_click_toggles_popup_each_time(self, app_ctx, monkeypatch):
        app, ctx, _buffer = app_ctx
        self._with_track(app, ctx, monkeypatch)
        assert app.show_devices is False
        self._click(app, ctx, *self.CIRCLE)
        assert app.show_devices is True, "first click opens"
        _tick(app, ctx, 2)  # popup renders; hit list now includes its regions
        self._click(app, ctx, *self.CIRCLE)
        assert app.show_devices is False, "second click closes"
        _tick(app, ctx, 2)
        self._click(app, ctx, *self.CIRCLE)
        assert app.show_devices is True, "third click reopens"

    def test_every_point_inside_the_circle_registers(self, app_ctx, monkeypatch):
        app, ctx, _buffer = app_ctx
        self._with_track(app, ctx, monkeypatch)
        cx, cy = self.CIRCLE
        expected = True
        for point in ((cx, cy), (cx, cy - 16), (cx, cy + 16), (cx - 16, cy), (cx + 16, cy)):
            self._click(app, ctx, *point)
            assert app.show_devices is expected, f"click at {point} did not toggle"
            _tick(app, ctx, 1)
            expected = not expected

    def test_poll_result_regrowing_popup_keeps_it_open(self, app_ctx, monkeypatch):
        app, ctx, _buffer = app_ctx
        self._with_track(app, ctx, monkeypatch, devices=1)
        self._click(app, ctx, *self.CIRCLE)
        assert app.show_devices is True
        # The open's poll lands with MORE devices than the last render: the
        # popup grows taller, must stay open, and the circle must still
        # toggle it closed.
        more_devices = [
            sl_models.Device(id=f"e{i}", name=f"Extra {i}", kind="Speaker",
                             is_active=False, is_restricted=False, volume_percent=None)
            for i in range(5)
        ]
        app._apply_result("poll-player", (app.player, None))
        app._apply_result("poll-devices", more_devices)
        _tick(app, ctx, 2)
        assert app.show_devices is True, "a poll result must not dismiss the popup"
        self._click(app, ctx, *self.CIRCLE)
        assert app.show_devices is False

    def test_popup_hit_never_covers_the_circle(self, app_ctx, monkeypatch):
        app, ctx, _buffer = app_ctx
        for device_count in (0, 1, 5):
            self._with_track(app, ctx, monkeypatch, devices=device_count, show_devices=True)
            hits = {r.action: r for r in app._hits}
            plate = hits["popup_plate"]
            circle = hits["open_devices"]
            overlap = not (plate.x + plate.w <= circle.x or circle.x + circle.w <= plate.x
                           or plate.y + plate.h <= circle.y or circle.y + circle.h <= plate.y)
            assert not overlap, (
                f"{device_count} devices: popup plate {plate.x, plate.y, plate.w, plate.h} "
                f"covers the overflow circle {circle.x, circle.y, circle.w, circle.h}")
            # The reversed hit walk must pick open_devices at the circle
            # centre — the same selection _dispatch_click makes.
            cx, cy = self.CIRCLE
            winner = next(r for r in reversed(app._hits) if r.contains(cx, cy))
            assert winner.action == "open_devices", \
                f"{device_count} devices: circle centre dispatches {winner.action}"


# ---------------------------------------------------------------------------
# Round 28, findings 2+3 (Alec on the #362 build): the app toasted "No active
# device — pick one under Devices", and pressing play errored 403. The real
# Spotify app never prompts when the target is obvious: it plays on the
# active device, or the only device there is. The contract: a
# no-active-device failure on a player action transfers to the obvious
# device and re-issues the action silently; the picker only opens when the
# choice is genuinely ambiguous (multiple devices, none active). The 403
# body is classified by its reason token, and any other 403 reaches the
# toast verbatim so the true cause is reportable.
# ---------------------------------------------------------------------------

class TestDeviceAutoPick:

    @staticmethod
    def _device(name, *, active=False):
        return sl_models.Device(id=name, name=name, kind="Computer", is_active=active,
                                is_restricted=False, volume_percent=50)

    @staticmethod
    def _no_active_error():
        return sl_api.classify_error(403, {"error": {"status": 403,
                                           "message": "Player command failed: No active device found",
                                           "reason": "NO_ACTIVE_DEVICE"}})

    def _base(self, app, ctx, monkeypatch, devices):
        app.authenticated = True
        app.view = "home"
        app.devices = list(devices)
        app.player = None
        submits: list = []
        monkeypatch.setattr(app.worker, "submit", lambda label, job: submits.append((label, job)))
        calls: list = []

        class _Client:
            def transfer(self, device_id, *, play=True):
                calls.append(("transfer", device_id, play))

            def play(self, **kwargs):
                calls.append(("play", kwargs))

            def devices(self):
                return list(app.devices)

        app._client = _Client()
        _tick(app, ctx, 1)

        class _PlayerSubmits:
            """Live view of the player-action jobs (the poll timer keeps
            appending its own submits to the underlying list)."""

            def _jobs(self):
                return [job for label, job in submits if label == "player-action"]

            def __len__(self):
                return len(self._jobs())

            def __getitem__(self, index):
                return self._jobs()[index]

        return _PlayerSubmits(), calls, submits

    @staticmethod
    def _recover(app, raw_submits):
        """Drive the two-phase device recovery: a NO_ACTIVE_DEVICE action
        error queues a fresh devices fetch; its result runs the decision."""
        entry = next((label, job) for label, job in raw_submits if label == "poll-devices")
        raw_submits.remove(entry)
        app._apply_result("poll-devices", entry[1]())

    def test_single_device_transfers_and_reissues_without_prompting(self, app_ctx, monkeypatch):
        app, ctx, _buffer = app_ctx
        submits, calls, raw = self._base(app, ctx, monkeypatch, [self._device("d1")])
        app._dispatch_action("toggle_play", None, 0.0)
        assert len(submits) == 1, "the user's play action is queued"

        app._apply_api_error("player-action", self._no_active_error())
        self._recover(app, raw)
        assert len(submits) == 2, "an obvious device means transfer + retry, not a prompt"
        submits[1]()  # run the queued retry job against the fake client
        assert calls == [("transfer", "d1", False), ("play", {})]
        assert app.show_devices is False, "no picker when the choice is obvious"
        assert "d1" in app.status_message, "the switch is announced, not silent"

    def test_active_device_wins_among_many(self, app_ctx, monkeypatch):
        app, ctx, _buffer = app_ctx
        submits, calls, raw = self._base(app, ctx, monkeypatch,
                                         [self._device("d1"), self._device("d2", active=True)])
        app._dispatch_action("toggle_play", None, 0.0)
        app._apply_api_error("player-action", self._no_active_error())
        self._recover(app, raw)
        assert len(submits) == 2
        submits[1]()
        assert calls[0] == ("transfer", "d2", False), "the active device is the target"
        assert app.show_devices is False

    def test_multiple_inactive_devices_is_the_only_prompt(self, app_ctx, monkeypatch):
        app, ctx, _buffer = app_ctx
        submits, _calls, raw = self._base(app, ctx, monkeypatch,
                                          [self._device("d1"), self._device("d2")])
        app._dispatch_action("toggle_play", None, 0.0)
        app._apply_api_error("player-action", self._no_active_error())
        self._recover(app, raw)
        assert len(submits) == 1, "ambiguous means no silent transfer"
        assert app.show_devices is True, "the picker opens — this is the only prompt"
        assert app.status_message == "Pick a device"

    def test_zero_devices_explains_without_prompting(self, app_ctx, monkeypatch):
        app, ctx, _buffer = app_ctx
        submits, _calls, raw = self._base(app, ctx, monkeypatch, [])
        app._dispatch_action("toggle_play", None, 0.0)
        app._apply_api_error("player-action", self._no_active_error())
        self._recover(app, raw)
        assert len(submits) == 1
        assert app.show_devices is False
        assert "No devices found" in app.status_message

    def test_retry_failure_does_not_loop(self, app_ctx, monkeypatch):
        app, ctx, _buffer = app_ctx
        submits, _calls, raw = self._base(app, ctx, monkeypatch, [self._device("d1")])
        app._dispatch_action("toggle_play", None, 0.0)
        app._apply_api_error("player-action", self._no_active_error())
        self._recover(app, raw)
        assert len(submits) == 2
        # The transfer+retry fails the same way (device vanished): stop
        # retrying and say so — never loop transfers across worker trips.
        app._apply_api_error("player-action", self._no_active_error())
        self._recover(app, raw)
        assert len(submits) == 2, "a failed auto-retry must not chain another"
        assert "pick one under Devices" in app.status_message

    def test_pick_device_transfer_does_not_chain(self, app_ctx, monkeypatch):
        app, ctx, _buffer = app_ctx
        submits, _calls, raw = self._base(app, ctx, monkeypatch, [self._device("d1")])
        app._dispatch_action("pick_device", "d1", 0.0)
        assert len(submits) == 1
        app._apply_api_error("player-action", self._no_active_error())
        self._recover(app, raw)
        assert len(submits) == 1, "a failed explicit transfer must not auto-transfer again"

    def test_other_403s_reach_the_toast_verbatim(self, app_ctx, monkeypatch):
        """If the 403 is Spotify's development-mode restriction (not a device
        problem), the body must surface as-is — that string is Alec's report,
        not something to code around."""
        app, ctx, _buffer = app_ctx
        self._base(app, ctx, monkeypatch, [self._device("d1")])
        error = sl_api.classify_error(403, {"error": {"status": 403,
                                            "message": "Player command failed: app is in development mode",
                                            "reason": "DEVELOPMENT_MODE"}})
        app._apply_api_error("player-action", error)
        assert "app is in development mode" in app.status_message
        assert "DEVELOPMENT_MODE" in app.status_message
        assert app.show_devices is False


# ---------------------------------------------------------------------------
# Rate limiting (Alec, round-28 build): a spontaneous 429 while idling. The
# app must honor Retry-After — pause the poll loop for the window, say so
# once, and resume on schedule — never keep hammering through the limit.
# ---------------------------------------------------------------------------

class TestRateLimitBackoff:

    class _Clock:
        def __init__(self):
            self.now = 1_000.0

        def __call__(self):
            return self.now

    def _base(self, app, ctx, monkeypatch, *, playing=False):
        app.authenticated = True
        app.view = "home"
        app._client = object()  # jobs never run; only the timer submits
        if playing:
            app.player = sl_models.PlayerState(is_playing=True, progress_ms=0,
                                               track=None, device=None, shuffle=False,
                                               repeat="off")
            app._player_synced_at = 0.0
        submits: list = []
        monkeypatch.setattr(app.worker, "submit", lambda label, job: submits.append(label))
        toasts: list = []
        monkeypatch.setattr(app, "_toast", lambda message: toasts.append(message))
        clock = self._Clock()
        monkeypatch.setattr(app_main.time, "monotonic", clock)
        return submits, toasts, clock

    @staticmethod
    def _rate_error(retry_after=30.0):
        return sl_api.ApiError(sl_api.ErrorKind.RATE_LIMITED,
                               "429: API rate limit exceeded", 429,
                               retry_after_secs=retry_after)

    def test_poll_429_pauses_polling_for_the_retry_after_window(self, app_ctx, monkeypatch):
        app, ctx, _buffer = app_ctx
        submits, toasts, clock = self._base(app, ctx, monkeypatch)
        _tick(app, ctx, 2)
        assert submits == ["poll-player"], "the steady-state poll fires on schedule"

        app._apply_result("poll-player", self._rate_error(30.0))
        clock.now += 29.0
        _tick(app, ctx, 5)
        assert submits == ["poll-player"], "no polls inside the Retry-After window"

        clock.now += 2.0
        _tick(app, ctx, 2)
        assert submits == ["poll-player", "poll-player"], "polling resumes after the window"
        assert toasts and "rate limit" in toasts[0].lower(), "the pause is announced once"

    def test_repeated_429s_extend_the_window_but_toast_once(self, app_ctx, monkeypatch):
        app, ctx, _buffer = app_ctx
        submits, toasts, clock = self._base(app, ctx, monkeypatch)
        app._apply_result("poll-player", self._rate_error(30.0))
        clock.now += 20.0
        app._apply_result("poll-player", self._rate_error(30.0))
        assert toasts == [toasts[0]] and len(toasts) == 1, \
            "already backing off: extend the deadline, don't re-toast"
        clock.now += 25.0
        _tick(app, ctx, 3)
        assert submits == [], "the second 429 restarted the window"
        clock.now += 6.0
        _tick(app, ctx, 2)
        assert submits == ["poll-player"], "resume 30s after the LAST 429"

    def test_429_without_retry_after_uses_the_default_backoff(self, app_ctx, monkeypatch):
        app, ctx, _buffer = app_ctx
        submits, toasts, clock = self._base(app, ctx, monkeypatch)
        app._apply_result("poll-player", self._rate_error(None))
        clock.now += app_main.POLL_MIN_INTERVAL_SECS + 1.0
        _tick(app, ctx, 3)
        assert submits == [], "missing header must not mean 'no backoff'"
        assert toasts and "rate limit" in toasts[0].lower()

    def test_player_action_429_also_pauses_the_poll_loop(self, app_ctx, monkeypatch):
        app, ctx, _buffer = app_ctx
        submits, toasts, clock = self._base(app, ctx, monkeypatch)
        app._apply_result("player-action", self._rate_error(20.0))
        clock.now += 10.0
        _tick(app, ctx, 3)
        assert submits == [], "a limited player action quiets polling too"

    def test_cadence_resumes_at_the_normal_interval_after_recovery(self, app_ctx, monkeypatch):
        app, ctx, _buffer = app_ctx
        submits, toasts, clock = self._base(app, ctx, monkeypatch, playing=True)
        app._apply_result("poll-player", self._rate_error(10.0))
        clock.now += 11.0
        _tick(app, ctx, 1)
        assert submits == ["poll-player"], "first poll right after the window"
        playing = sl_models.PlayerState(is_playing=True, progress_ms=0, track=None,
                                        device=None, shuffle=False, repeat="off")
        app._apply_result("poll-player", (playing, None))  # a clean success
        clock.now += app_main.HEARTBEAT_PLAYING_SECS + 0.1
        _tick(app, ctx, 1)
        assert submits == ["poll-player", "poll-player"], \
            "backoff resets: success returns to the playing heartbeat, not a stale long one"


# ---------------------------------------------------------------------------
# Round 28, finding 4 (Alec on the #362 build): the thin specular top-edge
# line on the glass plates reads as a hard artifact. The contract: the
# highlight is a segmented falloff — lower peak, ends fading to nothing —
# never one uniform full-span 1px line.
# ---------------------------------------------------------------------------

class TestSpecularHighlightSoftened:

    class _Capture:
        def __init__(self):
            self.rrects = []
            self.rects = []

        def rounded_rect(self, **kw):
            self.rrects.append(kw)

        def rect(self, **kw):
            self.rects.append(kw)

    @staticmethod
    def _specular_segments(cap, plate_y=100.0):
        return [n for n in cap.rects
                if n["color"][:3] == (255, 255, 255)
                and n["height"] == 1 and n["y"] == plate_y + 1]

    def _rasterize_plate(self, w, h, radius):
        cap = self._Capture()
        sl_views._glass_plate(cap, 100.0, 100.0, w, h, radius=radius, z=2)
        nodes = [RectNode(x=0, y=0, width=400, height=400,
                          color_rgba=(16, 16, 16, 255), z_index=0)]
        nodes += [RoundedRectNode(x=n["x"], y=n["y"], width=n["width"], height=n["height"],
                                  radius=n["radius"], color_rgba=n["color"],
                                  z_index=n["z_index"]) for n in cap.rrects]
        nodes += [RectNode(x=n["x"], y=n["y"], width=n["width"], height=n["height"],
                           color_rgba=n["color"], z_index=n["z_index"]) for n in cap.rects]
        frame = SceneFrame(revision=1, logical_width=400, logical_height=400,
                           display_width=400, display_height=400, ts_ns=0,
                           nodes=tuple(nodes))
        return rasterize_scene_frame(frame)

    def test_highlight_is_segments_fading_out_at_the_ends(self):
        cap = self._Capture()
        sl_views._glass_plate(cap, 100.0, 100.0, 200.0, 100.0, radius=22.0, z=2)
        segs = self._specular_segments(cap)
        assert len(segs) >= 8, \
            "one uniform full-span 1px line is the hard artifact Alec sees; draw fading segments"
        segs.sort(key=lambda n: n["x"])
        alphas = [n["color"][3] for n in segs]
        mid = len(alphas) // 2
        assert alphas[0] <= 4 and alphas[-1] <= 4, \
            f"the ends must fade to nothing, got {alphas[0]}/{alphas[-1]}"
        left, right = alphas[:mid], alphas[mid:]
        assert left == sorted(left), f"alpha must rise toward the centre: {alphas}"
        assert right == sorted(right, reverse=True), f"alpha must fall toward the end: {alphas}"

    def test_highlight_peak_is_softened(self):
        assert sl_views.GLASS_HIGHLIGHT[3] <= 48, \
            f"a 1px white line at alpha {sl_views.GLASS_HIGHLIGHT[3]} reads hard; keep the peak <= 48"

    def test_top_edge_raster_has_no_uniform_line(self):
        img = self._rasterize_plate(200.0, 100.0, 22.0)
        row = 101  # the specular row (plate y+1)
        center_lum = int(img[row, 200, :3].sum()) / 3
        end_lum = int(img[row, 120, :3].sum()) / 3
        assert end_lum + 12 <= center_lum, (
            f"the top-edge line must fade toward the ends: end {end_lum:.0f} vs "
            f"centre {center_lum:.0f} — a uniform line is the hard artifact")


# ---------------------------------------------------------------------------
# Round 28, finding 5 (Alec on the #362 build): the pill's square album art
# sits flush at the pill's left cap, so its corners cross the rounded
# silhouette. The thumb is alpha-clipped to a rounded tile — the same
# construction as the idle note tile (r8).
# ---------------------------------------------------------------------------

class TestPillArtRounded:

    def test_pill_thumb_is_clipped_to_its_rounded_tile(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        artist = _artist("ANOTR")
        track = _track("Relax My Eyes", artist, _album("The Reset", artist), ms=243_000)
        device = sl_models.Device(id="d1", name="MacBook Pro", kind="Computer",
                                  is_active=True, is_restricted=False, volume_percent=40)
        app.player = sl_models.PlayerState(is_playing=True, progress_ms=30_500, track=track,
                                           device=device, shuffle=False, repeat="off")
        app._player_synced_at = app.now_monotonic
        _tick(app, ctx, 2)

        px, py, _, _ = sl_views.pill_rect(1280, 800)
        thumbs = [n for n in _nodes(scene_buffer, CpuLayerNode)
                  if abs(n.x - (px + 12)) < 0.5 and abs(n.y - (py + 12)) < 0.5]
        assert thumbs, "pill art thumb missing"
        rgba = thumbs[0].rgba
        h, w = rgba.shape[0], rgba.shape[1]
        assert int(rgba[0, 0, 3]) == 0, \
            "square corner pixels cross the pill's rounded cap — clip the thumb"
        assert int(rgba[0, w - 1, 3]) == 0
        assert int(rgba[h - 1, 0, 3]) == 0
        assert int(rgba[h - 1, w - 1, 3]) == 0
        assert int(rgba[h // 2, w // 2, 3]) == 255, "the art itself stays opaque"


# ---------------------------------------------------------------------------
# Round 28, finding 6 (queued micro-fix): the idle note icon sits ~2px low.
# The note's ink mass is bottom-heavy (two heads under a beam), so its
# geometric centroid reads below its optical centre; the placement bias
# lifts it ~2px at the 20px tile.
# ---------------------------------------------------------------------------

def test_note_optical_bias_lifts_the_idle_glyph():
    _bias_x, bias_y = sl_views._ICON_OPTICAL_BIAS_EM[sl_icons.NOTE]
    assert bias_y <= -0.07, \
        f"the idle note needs a ~0.1em upward optical bias (2px at the 20px tile), got {bias_y}"


# ---------------------------------------------------------------------------
# Event-driven sync (Alec): replace fixed-interval polling with wall-clock
# progress + a poll scheduled at the track boundary, a slow heartbeat to
# bound drift from external control, activity-regain resync, and devices
# fetched on demand instead of every refresh.
# ---------------------------------------------------------------------------

class TestEventDrivenSync:

    class _Clock:
        def __init__(self):
            self.now = 1_000.0

        def __call__(self):
            return self.now

    @staticmethod
    def _track(name="t1", *, ms=200_000):
        artist = _artist(f"artist-{name}")
        return _track(name, artist, _album(f"album-{name}", artist), ms=ms)

    def _player(self, track, *, playing=True, progress_ms=0, repeat="off"):
        return sl_models.PlayerState(is_playing=playing, progress_ms=progress_ms,
                                     track=track, device=None, shuffle=False, repeat=repeat)

    def _base(self, app, ctx, monkeypatch, track=None, *, playing=True, progress_ms=0):
        app.authenticated = True
        app.view = "home"
        submits: list = []
        monkeypatch.setattr(app.worker, "submit", lambda label, job: submits.append((label, job)))
        toasts: list = []
        monkeypatch.setattr(app, "_toast", lambda message: toasts.append(message))
        clock = self._Clock()
        monkeypatch.setattr(app_main.time, "monotonic", clock)
        track = track if track is not None else self._track()
        app.player = self._player(track, playing=playing, progress_ms=progress_ms)
        app._player_synced_at = clock.now
        app._client = object()
        return submits, toasts, clock, track

    def test_progress_bar_advances_on_wall_clock_without_api_traffic(self, app_ctx, monkeypatch):
        """CORE 1: between syncs the bar moves on the local clock alone."""
        app, ctx, _buffer = app_ctx
        submits, _toasts, clock, _t = self._base(app, ctx, monkeypatch, progress_ms=10_000)
        app._schedule_player_poll()  # steady state: boundary ~190s out, heartbeat 60s
        start = app.progress_ms()
        clock.now += 10.0
        _tick(app, ctx, 5)
        assert submits == [], "no API traffic just to move the bar"
        assert 9_000 <= app.progress_ms() - start <= 11_000, "wall clock advanced the bar"

    def test_next_poll_lands_at_track_end_minus_skew(self, app_ctx, monkeypatch):
        """CORE 2: the proactive poll is scheduled at the boundary."""
        app, ctx, _buffer = app_ctx
        _submits, _toasts, clock, _t = self._base(app, ctx, monkeypatch, progress_ms=170_000)
        app._apply_result("poll-player", (self._player(self._track(), progress_ms=170_000), None))
        expected = clock.now + (30.0 - app_main.POLL_BOUNDARY_SKEW_SECS)
        assert abs(app._next_player_poll - expected) < 0.01, \
            f"boundary poll at end minus skew, got {app._next_player_poll - clock.now:.2f}s out"

    def test_heartbeat_caps_the_wait_on_long_tracks(self, app_ctx, monkeypatch):
        """CORE 3c: the heartbeat bounds drift from external control."""
        app, ctx, _buffer = app_ctx
        _s, _t, clock, _tr = self._base(app, ctx, monkeypatch, progress_ms=0)  # 200s track
        app._apply_result("poll-player", (self._player(self._track(), progress_ms=0), None))
        assert abs(app._next_player_poll - (clock.now + app_main.HEARTBEAT_PLAYING_SECS)) < 0.01

    def test_external_pause_leaves_heartbeat_only(self, app_ctx, monkeypatch):
        """EDGE: externally paused — no boundary exists, heartbeat only."""
        app, ctx, _buffer = app_ctx
        _s, _t, clock, track = self._base(app, ctx, monkeypatch)
        app._apply_result("poll-player", (self._player(track, playing=False, progress_ms=50_000), None))
        assert abs(app._next_player_poll - (clock.now + app_main.HEARTBEAT_PAUSED_SECS)) < 0.01

    def test_external_seek_recomputes_the_boundary(self, app_ctx, monkeypatch):
        """EDGE: an external seek moves the boundary to the new remaining time."""
        app, ctx, _buffer = app_ctx
        _s, _t, clock, track = self._base(app, ctx, monkeypatch, progress_ms=170_000)
        app._apply_result("poll-player", (self._player(track, progress_ms=170_000), None))
        first = app._next_player_poll
        app._apply_result("poll-player", (self._player(track, progress_ms=140_000), None))
        expected = clock.now + (60.0 - app_main.POLL_BOUNDARY_SKEW_SECS)
        assert abs(app._next_player_poll - expected) < 0.01
        assert app._next_player_poll > first, "seeking back pushes the boundary out"

    def test_external_skip_recomputes_from_the_new_track(self, app_ctx, monkeypatch):
        """EDGE: heartbeat discovers a new track; boundary comes from ITS end."""
        app, ctx, _buffer = app_ctx
        _s, _t, clock, _tr = self._base(app, ctx, monkeypatch)
        new_track = self._track("t2", ms=20_000)
        app._apply_result("poll-player", (self._player(new_track, progress_ms=5_000), None))
        expected = clock.now + (15.0 - app_main.POLL_BOUNDARY_SKEW_SECS)
        assert abs(app._next_player_poll - expected) < 0.01

    def test_repeat_one_reschedules_the_same_duration(self, app_ctx, monkeypatch):
        """EDGE: repeat-one restarts the same track; the boundary is its length again."""
        app, ctx, _buffer = app_ctx
        track = self._track(ms=30_000)
        _s, _t, clock, _tr = self._base(app, ctx, monkeypatch, track=track)
        app._apply_result("poll-player",
                          (self._player(track, progress_ms=500, repeat="track"), None))
        expected = clock.now + (29.5 - app_main.POLL_BOUNDARY_SKEW_SECS)
        assert abs(app._next_player_poll - expected) < 0.01

    def test_track_shorter_than_the_skew_clamps_to_a_minimum(self, app_ctx, monkeypatch):
        """EDGE: a 3s-remaining track must not schedule a negative/zero wait."""
        app, ctx, _buffer = app_ctx
        _s, _t, clock, track = self._base(app, ctx, monkeypatch, progress_ms=197_000)
        app._apply_result("poll-player", (self._player(track, progress_ms=197_000), None))
        assert abs(app._next_player_poll - (clock.now + app_main.POLL_MIN_INTERVAL_SECS)) < 0.01

    def test_paused_at_the_boundary_polls_on_the_paused_heartbeat(self, app_ctx, monkeypatch):
        """EDGE: paused AT track end — nothing advances, no boundary poll."""
        app, ctx, _buffer = app_ctx
        _s, _t, clock, track = self._base(app, ctx, monkeypatch, playing=False)
        app._apply_result("poll-player",
                          (self._player(track, playing=False, progress_ms=200_000), None))
        assert abs(app._next_player_poll - (clock.now + app_main.HEARTBEAT_PAUSED_SECS)) < 0.01

    def test_rate_limit_suppresses_every_scheduled_poll(self, app_ctx, monkeypatch):
        """COMPOSE with the 429 fix: boundary, heartbeat and activity all
        stay silent until the Retry-After window lifts, then resume."""
        app, ctx, _buffer = app_ctx
        submits, _t, clock, track = self._base(app, ctx, monkeypatch, progress_ms=170_000)
        app._apply_result("poll-player", (self._player(track, progress_ms=170_000), None))
        app._apply_result("poll-player", sl_api.ApiError(
            sl_api.ErrorKind.RATE_LIMITED, "429", 429, retry_after_secs=60.0))
        clock.now += 59.0  # boundary (28s) AND heartbeat (60s) both pass inside the window
        _tick(app, ctx, 5)
        assert submits == [], "rate-limit deadline suppresses every scheduled poll"
        clock.now += 2.0
        _tick(app, ctx, 2)
        assert [label for label, _job in submits] == ["poll-player"], "resume when it lifts"

    def test_activity_regain_triggers_a_throttled_resync(self, app_ctx, monkeypatch):
        """CORE 3b: returning to the app resyncs — once per stale window,
        not per event, and never when the sync is already fresh."""
        app, ctx, _buffer = app_ctx
        submits, _t, clock, _tr = self._base(app, ctx, monkeypatch)
        app._player_synced_at = clock.now - 100.0  # stale: user was away
        event = HDIEvent(event_id=1, ts_ns=1, window_id="w", device="mouse",
                         event_type="pointer_move", status="OK",
                         payload={"x": 5.0, "y": 5.0, "buttons_mask": 0})
        app._handle_input([event])
        _tick(app, ctx, 1)
        assert [label for label, _job in submits] == ["poll-player"], "returning user gets a resync"
        app._handle_input([event])
        _tick(app, ctx, 1)
        assert len(submits) == 1, "throttled: one resync per stale window"
        clock.now += 100.0
        app._player_synced_at = clock.now  # fresh again
        next_before = app._next_player_poll
        app._handle_input([event])
        assert app._next_player_poll == next_before and len(submits) == 1, \
            "no resync when the state is already fresh"

    def test_steady_state_poll_no_longer_fetches_devices(self, app_ctx, monkeypatch):
        """CORE 4: the player sync job carries player + queue only; devices
        move to their own on-demand fetch."""
        app, ctx, _buffer = app_ctx
        submits, _t, _c, _tr = self._base(app, ctx, monkeypatch)
        calls: list = []

        class _Client:
            def player_state(self):
                calls.append("player_state")
                return app.player

            def up_next(self):
                calls.append("up_next")
                return None

            def devices(self):
                calls.append("devices")
                return []

        app._client = _Client()
        _tick(app, ctx, 1)
        poll_jobs = [job for label, job in submits if label == "poll-player"]
        assert len(poll_jobs) == 1
        poll_jobs[0]()
        assert "devices" not in calls, "devices are decoupled from the player tick"
        assert "player_state" in calls

    def test_queue_fetch_is_skipped_without_the_queue_scope(self, app_ctx, monkeypatch):
        """SL-32: the queue scope is no longer requested, so every fresh
        token lacks it — calling /me/player/queue would be a guaranteed 403
        on every poll. The fetch is gated on the granted scope instead."""
        app, ctx, _buffer = app_ctx
        self._base(app, ctx, monkeypatch)
        app._tokens = sl_oauth.TokenSet(
            access_token="t", refresh_token=None,
            expires_at=time.time() + 3600,
            scope="user-read-private user-read-playback-state")
        calls: list = []

        class _Client:
            def player_state(self):
                return app.player

            def up_next(self):
                calls.append("up_next")
                return None

        app._client = _Client()
        player, up_next = app._job_poll_player()
        assert player is app.player
        assert up_next is None, "no queue scope granted: pre-staging quietly off"
        assert calls == [], "no wasted guaranteed-403 request per poll"

    def test_queue_fetch_runs_for_legacy_tokens_holding_the_scope(self, app_ctx, monkeypatch):
        """SL-32: tokens minted while the scope was still accepted keep their
        pre-staging — the gate keys on the granted scope, not a flat removal."""
        app, ctx, _buffer = app_ctx
        self._base(app, ctx, monkeypatch)
        app._tokens = sl_oauth.TokenSet(
            access_token="t", refresh_token=None,
            expires_at=time.time() + 3600,
            scope="user-read-private user-read-playback-queue")
        head = self._track("Queued Song")
        calls: list = []

        class _Client:
            def player_state(self):
                return app.player

            def up_next(self):
                calls.append("up_next")
                return head

        app._client = _Client()
        player, up_next = app._job_poll_player()
        assert up_next is head and calls == ["up_next"], \
            "scope-bearing legacy token: queue head still pre-staged"

    def test_queue_failure_degrades_the_poll_never_sinks_it(self, app_ctx, monkeypatch):
        """Legacy scope-holding tokens can still 403 on /me/player/queue
        (revoked server-side); the player snapshot must still land,
        pre-staging just stays off."""
        app, ctx, _buffer = app_ctx
        self._base(app, ctx, monkeypatch)
        app._tokens = sl_oauth.TokenSet(
            access_token="t", refresh_token=None,
            expires_at=time.time() + 3600,
            scope="user-read-private user-read-playback-queue")

        class _Client:
            def player_state(self):
                return app.player

            def up_next(self):
                raise sl_api.classify_error(403, {"error": {
                    "status": 403, "message": "Insufficient client scope"}})

        app._client = _Client()
        player, up_next = app._job_poll_player()
        assert player is app.player, "the playback snapshot survives a queue 403"
        assert up_next is None, "endpoint 403: pre-staging quietly off"

    def test_devices_fetched_on_popup_open_action_and_session(self, app_ctx, monkeypatch):
        """CORE 4: the three on-demand device triggers."""
        app, ctx, _buffer = app_ctx
        submits, _t, clock, _tr = self._base(app, ctx, monkeypatch)
        app._dispatch_action("open_devices", None, 0.0)
        assert "poll-devices" in [label for label, _job in submits], "popup open fetches devices"
        submits.clear()
        app._player_action(lambda c: None)
        assert "poll-devices" in [label for label, _job in submits], "player action fetches devices"

    def test_device_recovery_waits_for_a_fresh_devices_fetch(self, app_ctx, monkeypatch):
        """CORE 4 + round 28: NO_ACTIVE_DEVICE no longer decides from the
        stale cached list — it fetches devices, then auto-picks/prompts."""
        app, ctx, _buffer = app_ctx
        submits, toasts, clock, _tr = self._base(app, ctx, monkeypatch)
        calls: list = []

        class _Client:
            def devices(self):
                calls.append("devices")
                return [sl_models.Device(id="d1", name="Mac", kind="Computer", is_active=False,
                                         is_restricted=False, volume_percent=50)]

            def transfer(self, device_id, *, play=True):
                calls.append(("transfer", device_id, play))

            def play(self, **kwargs):
                calls.append(("play", kwargs))

        app._client = _Client()
        app._player_action(lambda c: c.play())
        error = sl_api.classify_error(403, {"error": {"status": 403,
                                            "message": "Player command failed: No active device found",
                                            "reason": "NO_ACTIVE_DEVICE"}})
        app._apply_api_error("player-action", error)
        labels = [label for label, _job in submits]
        assert "poll-devices" in labels, "recovery starts with a fresh devices fetch"
        actions_before = labels.count("player-action")
        device_job = next(job for label, job in submits if label == "poll-devices")
        app._apply_result("poll-devices", device_job())
        labels = [label for label, _job in submits]
        assert labels.count("player-action") == actions_before + 1, \
            "after fresh devices land: transfer + retry, queued only then"
        assert getattr(app._last_player_action, "_sl_device_retry", False), \
            "the queued retry carries the no-chain marker"
        app._last_player_action(app._client)
        assert calls[0] == "devices" and ("transfer", "d1", False) in calls

    def test_up_next_pre_staged_into_the_pill_at_the_boundary(self, app_ctx, monkeypatch):
        """CORE 2: at the computed end the pill already shows the queued
        track — the boundary poll confirms, it doesn't cause the flip."""
        app, ctx, buffer = app_ctx
        current = self._track("current", ms=200_000)
        upcoming = self._track("up-next", ms=180_000)
        _s, _t, clock, _tr = self._base(app, ctx, monkeypatch, track=current, progress_ms=199_000)
        app.up_next = upcoming
        clock.now += 2.0  # wall clock is now past the current track's end
        _tick(app, ctx, 2)
        texts = _texts(buffer)
        assert "up-next" in texts, "pill pre-stages the queued track at the boundary"
        assert "current" not in texts

    def test_post_action_one_shot_survives(self, app_ctx, monkeypatch):
        """CORE 3a: the 0.7s re-poll after a user action is unchanged."""
        app, ctx, _buffer = app_ctx
        _s, _t, clock, _tr = self._base(app, ctx, monkeypatch)
        app._player_action(lambda c: None)
        assert abs(app._next_player_poll - (clock.now + app_main.POLL_AFTER_ACTION_SECS)) < 0.01

# ---------------------------------------------------------------------------
# Library as a search-anchored popup (Alec, mock call): the whole left-rail
# component — brand, Your Library, playlist list, seams, scrollbar, account
# chip — exists ONLY as the docked panel above the expanded search field.
# Collapsed, there is no rail at all and home relayouts edge-to-edge.
# ---------------------------------------------------------------------------

class TestLibraryAsPopup:

    @staticmethod
    def _authed(app, ctx, *, playlists=6, view="home"):
        app.authenticated = True
        app._bootstrap_done = True
        app.view = view
        app.playlists = tuple(_playlist(f"Mix {i:02d}") for i in range(playlists))
        _tick(app, ctx, 2)

    @staticmethod
    def _old_rail_rect():
        m = sl_views.SIDEBAR_GLASS_MARGIN
        return (m, m, sl_views.SIDEBAR_W - 2 * m, HEIGHT - 2 * m)

    def test_collapsed_home_has_no_library_rail(self, app_ctx):
        app, ctx, buf = app_ctx
        self._authed(app, ctx)
        assert app.search_expanded is False
        texts = _texts(buf)
        assert "Spotify Light" not in texts, "the brand lives in the popup, not a rail"
        assert "Your Library" not in texts
        assert "PLAYLISTS" not in texts
        assert "Log out" not in texts
        assert not any(r.action in ("open_playlist", "logout", "panel_plate")
                       for r in app._hits), "no rail hits without the popup"
        rail = self._old_rail_rect()
        rings = [n for n in _nodes(buf, RoundedRectNode)
                 if n.color_rgba == sl_views.GLASS_BORDER
                 and (n.x, n.y, n.width, n.height) == rail]
        assert rings == [], "the floating glass rail is gone from the collapsed window"

    def test_home_content_relayouts_without_the_rail(self, app_ctx):
        app, ctx, buf = app_ctx
        self._authed(app, ctx)
        greeting = next(n for n in _nodes(buf, TextNode) if n.text.startswith("Good "))
        assert greeting.x == sl_views.CONTENT_PAD, \
            "with the rail gone, content starts at the window's content pad"
        app.view = "library"  # the playlist card grid, straight from app.playlists
        app.invalidate()
        _tick(app, ctx, 2)
        cards = [n for n in _nodes(buf, RoundedRectNode)
                 if n.width == sl_views.CARD_W and n.height == sl_views.CARD_H]
        assert cards and min(n.x for n in cards) == sl_views.CONTENT_PAD, \
            "the card grid's first column sits at the content pad"

    def test_expanded_panel_carries_the_full_library(self, app_ctx):
        app, ctx, buf = app_ctx
        self._authed(app, ctx, playlists=48)
        app.search_expanded = True
        app.view = "search"
        app.invalidate()
        _tick(app, ctx, 2)
        px, py, pw, ph = sl_views.library_panel_rect(app, WIDTH, HEIGHT)
        texts = {n.text: n for n in _nodes(buf, TextNode)}
        assert "Spotify Light" in texts, "the popup carries the rail's brand row"
        brand = texts["Spotify Light"]
        assert brand.color_rgba == sl_views.ACCENT, "brand keeps the accent styling"
        assert abs(brand.x - (px + 16)) < 1e-6 and py < brand.y < py + 48, \
            "the brand heads the panel"
        assert texts["Your Library"].y > brand.y, "nav title sits under the brand"
        assert texts["PLAYLISTS"].y > texts["Your Library"].y
        assert texts["Mix 00"].x >= px and texts["Mix 00"].y >= py + sl_views.PANEL_LIST_TOP
        assert "Log out" in texts and texts["Log out"].x >= px
        scroll_track = [r for r in app._hits
                        if r.action == "scrollbar" and r.payload == "sidebar"]
        assert scroll_track and px <= scroll_track[0].x < px + pw, \
            "the panel's long list keeps its scrollbar"
        assert any(r.action == "logout" and r.x >= px for r in app._hits)
        assert any(r.action == "open_playlist" and r.x >= px for r in app._hits)

    def test_collapsed_wheel_over_the_old_rail_zone_scrolls_content(self, app_ctx):
        app, ctx, buf = app_ctx
        self._authed(app, ctx, playlists=48)
        app._content_height = 4000.0
        app._mouse = (100.0, 400.0)  # squarely inside the old rail footprint
        app._apply_scroll(-120.0)
        assert app.sidebar_scroll == 0.0, "no rail list to scroll while collapsed"
        assert app.content_scroll == 120.0, "the whole window is content now"

    def test_sidebar_scrollbar_hit_exists_only_while_expanded(self, app_ctx):
        app, ctx, buf = app_ctx
        self._authed(app, ctx, playlists=48)
        assert not any(r.action == "scrollbar" and r.payload == "sidebar"
                       for r in app._hits), "collapsed: no list, no track"
        app.search_expanded = True
        app.invalidate()
        _tick(app, ctx, 2)
        assert any(r.action == "scrollbar" and r.payload == "sidebar"
                   for r in app._hits), "expanded: the popup list keeps the track"

    def test_nav_hit_lives_only_in_the_popup(self, app_ctx):
        app, ctx, buf = app_ctx
        self._authed(app, ctx)
        assert not any(r.action == "nav" and r.payload == "library" for r in app._hits), \
            "collapsed: the library nav row does not exist without the popup"
        app.search_expanded = True
        app.invalidate()
        _tick(app, ctx, 2)
        px, py, pw, ph = sl_views.library_panel_rect(app, WIDTH, HEIGHT)
        nav = [r for r in app._hits if r.action == "nav" and r.payload == "library"]
        assert nav and px <= nav[0].x and nav[0].x + nav[0].w <= px + pw, \
            "the library nav row lives inside the popup"


# ---------------------------------------------------------------------------
# Sidebar liquid glass (Alec): the left rail becomes one floating liquid-
# glass component — the dock pill's material turned vertical. Border ring,
# translucent fill, silhouette-clipped sheen, softened specular top, soft
# shadow. Hover/selection live inside the idiom as tint/alpha shifts (never
# opaque slabs), and the scrolling playlist list dissolves at both seams
# instead of hard-cutting. Round 67: the component is the search-anchored
# popup — these probes run against the expanded docked panel, which IS the
# rail's material relocated.
# ---------------------------------------------------------------------------

class TestSidebarLiquidGlass:

    @staticmethod
    def _panel(app):
        return sl_views.library_panel_rect(app, WIDTH, HEIGHT)

    @staticmethod
    def _base(app, ctx, *, playlists=6, scroll=0.0, view="home"):
        app.authenticated = True
        app._bootstrap_done = True
        app.view = view
        app.playlists = tuple(_playlist(f"Mix {i:02d}") for i in range(playlists))
        app.sidebar_scroll = scroll
        # The library component IS the search-anchored popup now: probe it
        # expanded, docked above the grown field.
        app.search_expanded = True

    @staticmethod
    def _raster(scene_buffer):
        frame = scene_buffer.latest_frame()
        assert frame is not None
        return rasterize_scene_frame(frame)

    def test_rail_is_one_floating_glass_plate_not_a_flat_panel(self, app_ctx):
        app, ctx, buf = app_ctx
        self._base(app, ctx)
        _tick(app, ctx, 2)
        x, y, w, h = self._panel(app)
        rrects = _nodes(buf, RoundedRectNode)
        assert any((n.x, n.y, n.width, n.height) == (x, y, w, h)
                   and n.color_rgba == sl_views.GLASS_BORDER and n.radius >= 12.0
                   for n in rrects), "the popup needs the glass border ring"
        assert any(abs(n.x - (x + 1)) < 0.5 and abs(n.y - (y + 1)) < 0.5
                   and abs(n.width - (w - 2)) < 0.5
                   and n.color_rgba == sl_views.GLASS_FILL for n in rrects), \
            "translucent glass fill sits inset inside the ring"
        assert any(n.color_rgba[0] == 0 and n.color_rgba[3] > 0 and n.width == w
                   and y < n.y <= y + 5 for n in rrects), \
            "the popup floats on the dock's soft shadow"
        rects = _nodes(buf, RectNode)
        assert [n for n in rects
                if n.x == 0 and n.width == sl_views.SIDEBAR_W and n.height == HEIGHT] == [], \
            "the flat square backing panel is gone"
        assert [n for n in rects
                if n.width == 1 and n.x == sl_views.SIDEBAR_W - 1 and n.height == HEIGHT] == [], \
            "the hard right-edge wire is gone — the border ring is the edge"
        m = sl_views.SIDEBAR_GLASS_MARGIN
        old_rail = (m, m, sl_views.SIDEBAR_W - 2 * m, HEIGHT - 2 * m)
        assert [n for n in rrects if (n.x, n.y, n.width, n.height) == old_rail] == [], \
            "the plate lives at the docked panel rect, never at the old rail footprint"

    def test_rail_specular_top_highlight_fades_like_the_dock(self, app_ctx):
        app, ctx, buf = app_ctx
        self._base(app, ctx)
        _tick(app, ctx, 2)
        x, y, w, _h = self._panel(app)
        segs = [n for n in _nodes(buf, RectNode)
                if n.color_rgba[:3] == (255, 255, 255) and n.height == 1
                and n.y == y + 1 and x < n.x < x + w]
        assert len(segs) >= 8, "one uniform full-span line is the round-28 hard wire"
        segs.sort(key=lambda n: n.x)
        alphas = [n.color_rgba[3] for n in segs]
        mid = len(alphas) // 2
        assert alphas[0] <= 4 and alphas[-1] <= 4, "ends fade to nothing"
        assert alphas[:mid] == sorted(alphas[:mid])
        assert alphas[mid:] == sorted(alphas[mid:], reverse=True)
        assert max(alphas) <= 48, "softened peak, same as the dock"

    def test_rail_sheen_stays_inside_the_rounded_silhouette(self, app_ctx):
        app, ctx, buf = app_ctx
        self._base(app, ctx)
        _tick(app, ctx, 2)
        x, y, w, h = self._panel(app)
        rows = [n for n in _nodes(buf, RectNode)
                if n.color_rgba[:3] == (255, 255, 255)
                and 0 < n.color_rgba[3] <= sl_views.GLASS_SHEEN[3]
                and y < n.y < y + h * 0.45 and x < n.x < x + w]
        assert rows, "the popup carries the sheen band"
        top_row = min(rows, key=lambda n: n.y)
        assert top_row.x > x + 1.0, \
            "the topmost sheen row must be chord-clipped inside the corner arc"
        for n in rows:
            assert n.x >= x + 1.0 and n.x + n.width <= x + w - 1.0, \
                "no sheen row may touch the silhouette edge"

    def test_glass_rail_raster_corner_clean_sheen_present(self, app_ctx):
        app, ctx, buf = app_ctx
        self._base(app, ctx)
        _tick(app, ctx, 2)
        img = self._raster(buf)
        x, y, w, _h = self._panel(app)
        corner = img[int(y + 2), int(x + 2), :3].sum() / 3
        assert corner < 60, \
            f"sheen leaking into the corner arc reads as a glitch (lum {corner:.0f})"
        top_center = img[int(y + 4), int(x + w / 2), :3].sum() / 3
        backdrop = img[int(y + 4), 2, :3].sum() / 3  # the window margin outside the plate
        assert top_center > backdrop + 4, "the sheen lights the plate's top edge"

    def test_playlist_hover_is_a_glass_tint_not_an_opaque_slab(self, app_ctx):
        app, ctx, buf = app_ctx
        self._base(app, ctx)
        _tick(app, ctx, 1)
        px, py, pw, _ph = self._panel(app)
        list_top = py + sl_views.PANEL_LIST_TOP
        app.input.state.mouse_x = px + 30.0
        app.input.state.mouse_y = list_top + 13.0
        app.invalidate()
        _tick(app, ctx, 2)
        hover = [n for n in _nodes(buf, RoundedRectNode)
                 if n.x == px + 8 and n.width == pw - 16
                 and abs(n.y - list_top) < 1.0]
        assert hover, "the hovered row gets a state plate"
        assert all(n.color_rgba[3] < 60 for n in hover), \
            f"hover lives inside the glass idiom as a tint, not an opaque slab: {hover[0].color_rgba}"

    def test_nav_hover_and_selection_stay_in_the_glass_idiom(self, app_ctx):
        """The popup's library row is hover-only (the panel itself is the
        library's presence — there is no separate active state to paint).
        Hover keeps the glass tint idiom; nothing draws an opaque slab."""
        app, ctx, buf = app_ctx
        self._base(app, ctx, view="library")
        _tick(app, ctx, 1)
        px, py, pw, _ph = self._panel(app)
        title_y = py + sl_views.PANEL_LIST_TOP - 52.0  # the "Your Library" row block
        app.input.state.mouse_x = px + 30.0
        app.input.state.mouse_y = title_y + 16.0
        app.invalidate()
        _tick(app, ctx, 2)
        tint = [n for n in _nodes(buf, RoundedRectNode)
                if n.x == px + 8 and n.width == pw - 16
                and abs(n.y - title_y) < 1.0 and n.color_rgba[3] < 60]
        assert tint, "the hovered library row gets a glass tint"
        opaque = [n for n in _nodes(buf, RoundedRectNode)
                  if px <= n.x < px + pw and n.color_rgba[3] == 255
                  and n.color_rgba[:3] != (0, 0, 0)]
        assert opaque == [], f"no opaque slabs inside the popup: {opaque[:1]}"

    def test_scroll_seams_fade_instead_of_a_hard_cutoff(self, app_ctx):
        app, ctx, buf = app_ctx
        self._base(app, ctx, playlists=48, scroll=100.0)
        _tick(app, ctx, 2)
        px, py, pw, ph = self._panel(app)
        top = py + sl_views.PANEL_LIST_TOP
        bottom = py + ph - sl_views.PANEL_CHIP_H
        rects = _nodes(buf, RectNode)

        def seam_strips(region_top, region_bottom):
            # Scoped to the popup's x range: the round-30 top scrim used to
            # draw equally wide dark strips at the same z outside the sidebar.
            strips = [n for n in rects
                      if region_top <= n.y < region_bottom
                      and px <= n.x < px + pw
                      and n.color_rgba[:3] < (40, 40, 40)
                      and n.width >= pw - 6 and n.z_index >= 4]
            strips.sort(key=lambda n: n.y)
            return strips

        top_strips = seam_strips(top, top + 22)
        assert len(top_strips) >= 3, "the top seam dissolves over several strips"
        top_alphas = [n.color_rgba[3] for n in top_strips]
        assert top_alphas == sorted(top_alphas, reverse=True) and top_alphas[-1] < top_alphas[0], \
            f"top seam alpha must ramp down into the list: {top_alphas}"
        bottom_strips = seam_strips(bottom - 22, bottom)
        assert len(bottom_strips) >= 3, "the bottom seam dissolves over several strips"
        bottom_alphas = [n.color_rgba[3] for n in bottom_strips]
        assert bottom_alphas == sorted(bottom_alphas) and bottom_alphas[0] < bottom_alphas[-1], \
            f"bottom seam alpha must ramp up toward the chip: {bottom_alphas}"

    def test_account_separator_is_inset_and_quiet(self, app_ctx):
        app, ctx, buf = app_ctx
        self._base(app, ctx)
        _tick(app, ctx, 2)
        px, py, pw, ph = self._panel(app)
        chip_rule_y = py + ph - sl_views.PANEL_CHIP_H
        dividers = [n for n in _nodes(buf, RectNode)
                    if n.height == 1 and abs(n.y - chip_rule_y) < 1.0
                    and px <= n.x < px + pw]
        assert dividers, "the account row keeps a separator"
        for n in dividers:
            assert n.x >= px + 10 and n.width <= pw - 20, \
                "the separator insets like a macOS glass separator, not a full-width wire"
            assert n.color_rgba[3] <= 60, "quiet alpha on glass, not an opaque line"

    def test_rail_stays_a_dark_glass_so_text_contrast_holds(self, app_ctx):
        """White/subtext glyphs ride the popup everywhere; the plate composite
        must stay dark — translucent, but never washing toward white over
        the window backdrop."""
        app, ctx, buf = app_ctx
        self._base(app, ctx)
        _tick(app, ctx, 2)
        img = self._raster(buf)
        px, py, pw, _ph = self._panel(app)
        region = img[int(py + 40):int(py + 200), int(px + 20):int(px + pw - 20), :3]
        mean_lum = float(region.sum() / 3 / region[:, :, 0].size)
        assert mean_lum < 100, \
            f"popup interior lum {mean_lum:.0f} — the glass must stay dark enough for light text"

# ---------------------------------------------------------------------------
# Pill to the top-right (Alec, round 30): the now-playing pill leaves the
# bottom dock for the window's top-right corner, right edge pinned so any
# width change grows leftward. The nav/overflow circles are NOT part of the
# move — they hold the bottom dock exactly where the cluster put them.
# ---------------------------------------------------------------------------

class TestPillTopRight:

    @staticmethod
    def _with_track(app, ctx, *, show_devices=False):
        app.authenticated = True
        artist = _artist("Nirvana")
        track = _track("Lithium", artist, _album("Nevermind", artist), ms=257_000)
        app.player = sl_models.PlayerState(is_playing=True, progress_ms=30_500,
                                           track=track, device=None, shuffle=False,
                                           repeat="off")
        app._player_synced_at = app.now_monotonic
        # The scene is retained: show_devices must be set before the tick, or
        # the popup region never redraws.
        app.show_devices = show_devices
        _tick(app, ctx, 2)

    def test_pill_anchors_top_right_at_design_width(self):
        assert sl_views.pill_rect(1280, 800) == (692.0, 16.0, 572.0, 108.0), \
            "right edge pinned at width - PILL_FLOAT, top at the dock's margin idiom"

    def test_right_edge_stays_pinned_across_window_widths(self):
        for w in (1600.0, 1280.0, 1000.0, 760.0):
            px, py, pw, ph = sl_views.pill_rect(w, 800)
            assert px + pw == pytest.approx(w - sl_views.PILL_FLOAT), \
                f"right edge drifts at width {w} — shrinkage must grow leftward"
            assert py == sl_views.PILL_FLOAT and ph == sl_views.PILL_H
            assert px >= sl_views.SIDEBAR_W + sl_views.PILL_FLOAT, \
                f"pill crosses the sidebar at width {w}"

    def test_idle_and_playing_share_the_same_right_edge(self, app_ctx):
        """Both states anchor the right edge: if the pill's width ever differs
        between idle and playing, growth reads as leftward, never a jump."""
        app, ctx, buf = app_ctx
        app.authenticated = True
        _tick(app, ctx, 2)
        ring_idle = [n for n in _nodes(buf, RoundedRectNode)
                     if n.color_rgba == sl_views.GLASS_BORDER
                     and n.radius == sl_views.GLASS_RECT_RADIUS]
        assert len(ring_idle) == 1
        self._with_track(app, ctx)
        ring_playing = [n for n in _nodes(buf, RoundedRectNode)
                        if n.color_rgba == sl_views.GLASS_BORDER
                        and n.radius == sl_views.GLASS_RECT_RADIUS]
        assert len(ring_playing) == 1
        assert (ring_idle[0].x + ring_idle[0].width) == \
            (ring_playing[0].x + ring_playing[0].width), "right edge must not move"
        assert ring_idle[0].y == ring_playing[0].y == sl_views.PILL_FLOAT

    def test_pill_contents_ride_to_the_top_right(self, app_ctx):
        """The whole component moves: art tile, metadata, transport hits,
        progress strip — nothing player-shaped stays bottom-center."""
        app, ctx, buf = app_ctx
        self._with_track(app, ctx)
        px, py, pw, ph = sl_views.pill_rect(1280, 800)
        art = [n for n in _nodes(buf, CpuLayerNode) if n.width == 84]
        assert art and (art[0].x, art[0].y) == (px + 12, py + 12), "art tile rides along"
        for action in ("toggle_play", "prev", "next", "seek_bar"):
            hits = [r for r in app._hits if r.action == action]
            assert hits and py <= hits[0].y <= py + ph, f"{action} hit left behind at the dock"
        old_zone = [r for r in app._hits
                    if r.action in ("toggle_play", "seek_bar") and r.y > 700]
        assert old_zone == [], "no player hits linger in the old dock zone"

    def test_home_and_search_hold_the_bottom_dock(self, app_ctx):
        """Home/search are not part of the pill's move: they keep the exact
        coordinates the bottom cluster gave them. The overflow circle held
        the dock too until round 36, when the shipped layout file moved it
        to the pill's left flank (TestOverflowPersistsLeftOfPill owns that)."""
        app, ctx, buf = app_ctx
        self._with_track(app, ctx, show_devices=True)
        home = next(r for r in app._hits if r.action == "nav" and r.payload == "home")
        search = next(r for r in app._hits if r.action == "nav" and r.payload == "search")
        assert (home.x, home.y, home.w, home.h) == (468.0, 730.0, 44.0, 44.0)
        assert (search.x, search.y, search.w, search.h) == (1008.0, 730.0, 44.0, 44.0)
        assert [r for r in app._hits if r.action == "open_devices" and r.y > 700] == [], \
            "the bottom-right no longer hosts the overflow circle"

    def test_search_field_clears_the_pill_zone(self, app_ctx):
        app, ctx, buf = app_ctx
        app.authenticated = True
        app.view = "search"
        ctx.logical_width_px = 1000.0
        _tick(app, ctx, 2)
        pill_x = sl_views.pill_rect(1000.0, 800.0)[0]
        fields = [n for n in _nodes(buf, RoundedRectNode)
                  if n.radius == 20.0 and abs(n.y - 24.0) < 1.0]
        assert fields, "search field missing"
        assert fields[0].x + fields[0].width <= pill_x - 12.0 + 1e-6, \
            "the field's rounded cap must not slide under the top-right pill"

    def test_window_top_is_clear_of_scrim(self, app_ctx):
        """SL-33 (Alec): the round-30 top scrim is gone. It spanned the full
        content width, so the Top tracks grid's first row scrolled under a
        dark gradient that ate the top ~25% of the card art while second-row
        cards rendered clean. The window top over content now holds zero
        scrim strips. (SL-35 then removed the dock scrim too; the bottom
        guard lives in TestDockScrimRemoved.)"""
        app, ctx, buf = app_ctx
        app.authenticated = True
        _tick(app, ctx, 2)
        top_zone = 200.0  # the round-30 scrim's footprint: band + fade + margin
        strips = [n for n in _nodes(buf, RectNode)
                  if n.x == sl_views.SIDEBAR_W and n.width == 1280 - sl_views.SIDEBAR_W
                  and n.color_rgba[:3] == sl_views.BG[:3]
                  and n.y < top_zone]
        assert strips == [], f"top scrim strips linger over content: {strips[:3]}"

    def test_scrolled_content_flows_under_the_top_glass(self, app_ctx):
        app, ctx, buf = app_ctx
        app.authenticated = True
        app.view = "library"
        app.playlists = tuple(_playlist(f"Mix {i:02d}") for i in range(48))
        app.content_scroll = 400.0
        _tick(app, ctx, 2)
        frame = buf.latest_frame()
        card_tops = [n.y for n in frame.nodes
                     if isinstance(n, RoundedRectNode) and n.width == sl_views.CARD_W]
        assert min(card_tops) < sl_views.PILL_FLOAT + sl_views.PILL_H, \
            "scrolled cards must pass under the top pill zone, not cull at it"


# ---------------------------------------------------------------------------
# Round 41 (Alec, SL-26/27): the overflow (⋯) circle MERGES into the pill —
# attached at the top-right slot (inset 12) via the shipped layout_attach
# RELATIONSHIP, the tool's first persisted use. It rides the pill's corner
# across resizes, keeps its 44pt size, and the text column yields its slot.
# The popup drops from the pill's bottom, right-aligned to the circle; the
# search field caps at the pill again. (Round 36/38 history: SL-19 parked
# it left of the pill, SL-23 re-spec'd that as an align relationship —
# SL-26's layout_clear removed it before the attach landed.)
class TestOverflowPersistsLeftOfPill:

    def _with_track(self, app, ctx, *, show_devices=False):
        app.authenticated = True
        nirvana = _artist("Nirvana")
        track = _track("Lithium", nirvana, _album("Nevermind", nirvana), ms=257_000)
        app.devices = [
            sl_models.Device(id="d1", name="MacBook Pro", kind="Computer", is_active=True,
                             is_restricted=False, volume_percent=40),
        ]
        app.player = sl_models.PlayerState(is_playing=True, progress_ms=30_500,
                                           track=track, device=app.devices[0],
                                           shuffle=False, repeat="off")
        app._player_synced_at = app.now_monotonic
        app.show_devices = show_devices
        _tick(app, ctx, 2)

    def test_circle_sits_at_the_shipped_position(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        self._with_track(app, ctx)
        px, py, pw, ph = sl_views.pill_rect(1280, 800)
        overflow = next(r for r in app._hits if r.action == "open_devices")
        assert (overflow.x, overflow.y, overflow.w, overflow.h) == (1208.0, 28.0, 44.0, 44.0), \
            "SL-27's attach relationship, baked: pill top-right, inset 12, at 1280x800"
        assert overflow.x + overflow.w == px + pw - 12.0, "12pt in from the pill's right edge"
        assert overflow.y == py + 12.0, "12pt down from the pill's top edge"

    def test_circle_tracks_the_window_right_edge(self, app_ctx):
        """The persisted spec is a RELATIONSHIP (round 41, SL-27: attach to
        the pill's top-right slot): resizes keep the 12pt insets because
        the circle rides the pill's corner — no raw pixels."""
        app, ctx, scene_buffer = app_ctx
        self._with_track(app, ctx)
        for w in (1280.0, 1100.0, 940.0):
            ctx.logical_width_px = w
            app.invalidate()  # stands in for the OS resize event
            _tick(app, ctx, 2)
            px, py, pw, _ = sl_views.pill_rect(w, 800)
            overflow = next(r for r in app._hits if r.action == "open_devices")
            assert overflow.x == px + pw - 12.0 - 44.0, f"attach resolution at width {w}"
            assert overflow.y == py + 12.0, f"top inset drifts at width {w}"

    def test_bottom_dock_keeps_only_home_and_search(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        self._with_track(app, ctx)
        bottom = [r for r in app._hits
                  if r.action in ("nav", "open_devices") and r.y > 700]
        got = {(r.action, r.payload if r.action == "nav" else None): (r.x, r.y)
               for r in bottom}
        assert got == {("nav", "home"): (468.0, 730.0),
                       ("nav", "search"): (1008.0, 730.0)}, \
            "the bottom-right holds just search; home stays; overflow is gone"

    def test_popup_drops_from_the_shipped_circle(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        self._with_track(app, ctx, show_devices=True)
        plates = [n for n in _nodes(scene_buffer, RoundedRectNode)
                  if n.color_rgba == (18, 18, 18, 234) and n.width == 298]
        assert plates, "popup missing"
        px, py, pw, ph = sl_views.pill_rect(1280, 800)
        for n in plates:
            assert n.x + n.width + 1 == px + pw - 12.0, \
                "popup right edge aligns to the attached circle's right edge (menu idiom)"
            assert n.y - 1 == py + ph + 12.0, \
                "popup drops 12pt below the pill's bottom (clear of the merged ⋯)"

    def test_search_field_clears_the_shipped_circle(self, app_ctx):
        # 1000pt: the ⋯ merged INTO the pill, so the pill is again the only
        # thing the field's rounded cap must clear. (With the rail retired —
        # round 67 — content starts at CONTENT_PAD, so the pill cap binds at
        # a narrower width than it did against the old 268pt x0.)
        app, ctx, buf = app_ctx
        app.authenticated = True
        app.view = "search"
        ctx.logical_width_px = 1000.0
        _tick(app, ctx, 2)
        pill_x = sl_views.pill_rect(1000.0, 800.0)[0]
        fields = [n for n in _nodes(buf, RoundedRectNode)
                  if n.radius == 20.0 and abs(n.y - 24.0) < 1.0]
        assert fields, "search field missing"
        assert fields[0].x + fields[0].width == pill_x - 12.0, \
            "the field's rounded cap stops 12pt short of the pill"
        assert fields[0].width == pytest.approx(pill_x - 12.0 - sl_views.CONTENT_PAD), \
            "the pill — not the merged circle, not the 460pt max — sets the cap again"

    def test_a_nav_more_override_still_wins(self, app_ctx):
        """The persisted attach is the base layout, not a cage: a fresh
        layout_set still re-points the circle (a rect spec REPLACES the
        attach relationship, back to window space, and persists that)."""
        app, ctx, scene_buffer = app_ctx
        self._with_track(app, ctx)
        app.mcp_call("layout_set", {
            "id": "nav_more", "rect": {"x": 600, "y": 300, "width": 44, "height": 44}})
        _tick(app, ctx, 2)
        overflow = next(r for r in app._hits if r.action == "open_devices")
        assert (overflow.x, overflow.y) == (600.0, 300.0)


# ---------------------------------------------------------------------------
# Round 42 (Alec, SL-28, on the merged ⋯): "i dont want pill inside pill.
# it should just be the icon itself." The glass disc behind the ellipsis
# reads as a capsule nested in the capsule — remove the chrome: bare glyph,
# no circle background/border/hover-disc. The 44x44 hit rect, the attach
# spec, the slot reservation (reserve_right=50), and the popup anchor all
# resolve off the same rect — layout.toml untouched. The play button's
# white disc is explicitly OUT of scope.
# ---------------------------------------------------------------------------

class TestBareOverflowIcon:
    CIRCLE = (1208.0, 28.0, 44.0, 44.0)  # the shipped attach at 1280x800
    CENTER = (1230.0, 50.0)

    def _playing(self, app, ctx, *, show_devices=False):
        app.authenticated = True
        nirvana = _artist("Nirvana")
        track = _track("Lithium", nirvana, _album("Nevermind", nirvana), ms=257_000)
        app.devices = [
            sl_models.Device(id="d1", name="MacBook Pro", kind="Computer", is_active=True,
                             is_restricted=False, volume_percent=40),
        ]
        app.player = sl_models.PlayerState(is_playing=True, progress_ms=30_500,
                                           track=track, device=app.devices[0],
                                           shuffle=False, repeat="off")
        app._player_synced_at = app.now_monotonic
        app.show_devices = show_devices
        _tick(app, ctx, 2)

    def test_no_disc_is_drawn_behind_the_glyph(self, app_ctx):
        """Scene level: no plate node of any layer (shadow, ring, fill,
        sheen) sits on the icon's rect — the pill's own plate is the only
        glass there now."""
        app, ctx, scene_buffer = app_ctx
        self._playing(app, ctx)
        ox, oy, ow, oh = self.CIRCLE
        frame = scene_buffer.latest_frame()
        disc = [n for n in frame.nodes
                if isinstance(n, (RoundedRectNode, RectNode))
                and n.x >= ox - 2.0 and n.y >= oy - 1.0
                and n.x + n.width <= ox + ow + 2.0
                and n.y + n.height <= oy + oh + 8.0  # the plate's y+5 shadow
                and n.width <= 100.0]  # the pill's own plate/sheen spans through
        assert disc == [], f"disc chrome still drawn behind the icon: {disc[:3]}"

    def test_the_glyph_still_draws_centered_and_bare(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        self._playing(app, ctx)
        frame = scene_buffer.latest_frame()
        glyphs = [n for n in frame.nodes
                  if isinstance(n, TextNode) and n.text == sl_icons.MORE]
        assert len(glyphs) == 1, "exactly one ⋯ glyph"
        assert glyphs[0].font_family == sl_icons.ICON_FONT
        assert glyphs[0].color_rgba == sl_views.SUBTEXT, \
            "idle glyph keeps the quiet ink (hover/popup-open recolor it)"
        hover = next(r for r in app._hits if r.action == "open_devices")
        assert (hover.x, hover.y, hover.w, hover.h) == self.CIRCLE

    def test_the_hit_rect_and_popup_anchor_are_unchanged(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        self._playing(app, ctx, show_devices=True)
        overflow = next(r for r in app._hits if r.action == "open_devices")
        assert (overflow.x, overflow.y, overflow.w, overflow.h) == self.CIRCLE, \
            "the 44x44 hit rect is a layout contract — the disc removal must not move it"
        px, py, pw, ph = sl_views.pill_rect(1280, 800)
        plates = [n for n in _nodes(scene_buffer, RoundedRectNode)
                  if n.color_rgba == (18, 18, 18, 234) and n.width == 298]
        assert plates, "popup missing"
        for n in plates:
            assert n.x + n.width + 1 == overflow.x + overflow.w, \
                "popup right edge still aligns to the icon rect's right edge"
            assert n.y - 1 == py + ph + 12.0, "popup still drops 12pt below the pill"

    def test_play_disc_is_out_of_scope(self, app_ctx):
        """The white play disc STAYS — only the overflow chrome goes."""
        app, ctx, scene_buffer = app_ctx
        self._playing(app, ctx)
        frame = scene_buffer.latest_frame()
        play = next(r for r in app._hits if r.action == "toggle_play")
        discs = [n for n in frame.nodes
                 if isinstance(n, CircleNode)
                 and abs(n.cx - (play.x + play.w / 2)) < 1.0
                 and abs(n.cy - (play.y + play.h / 2)) < 1.0
                 and n.fill_rgba[0] > 200]
        assert discs, "the white play disc must survive the SL-28 chrome removal"

    # -- the pixel probes (rasterized truth) ----------------------------------

    def _raster(self, app, ctx, scene_buffer):
        frame = scene_buffer.latest_frame()
        assert frame is not None
        return rasterize_scene_frame(frame)

    def test_probe_dots_present_around_the_slot_center(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        self._playing(app, ctx)
        img = self._raster(app, ctx, scene_buffer)
        ocx, ocy = int(self.CENTER[0]), int(self.CENTER[1])
        xs, ys = [], []
        for y in range(ocy - 16, ocy + 16):
            for x in range(ocx - 16, ocx + 16):
                r, g, b = (int(v) for v in img[y, x, :3])
                if (r + g + b) / 3 >= 140:  # the SUBTEXT/ACCENT glyph ink
                    xs.append(x)
                    ys.append(y)
        assert xs, "no ⋯ glyph ink found around (1230, 50)"
        assert abs(sum(xs) / len(xs) - self.CENTER[0]) <= 1.5
        assert abs(sum(ys) / len(ys) - self.CENTER[1]) <= 1.5

    def test_probe_no_disc_signature_around_the_icon(self, app_ctx):
        """A disc plate would stamp values the pill body never produces at
        those rows: its shadow pair darkens below the body's floor, its
        fill/ring bump above the sheen's ceiling. Compare each slot row
        against the same-y pill-body strip just left of the slot —
        construction-relative, so the probe survives plate-fill retunes
        (round 66 moved the body's absolute read). Glyph ink and its AA
        halo (which hugs bright pixels) are excluded: the body tops out
        near 65 and the glyph ramps toward the ~190 ink, so 80 sits in
        the gap."""
        import numpy as np
        app, ctx, scene_buffer = app_ctx
        self._playing(app, ctx)
        img = self._raster(app, ctx, scene_buffer)
        ox, oy, ow, oh = (int(v) for v in self.CIRCLE)
        lum = img[..., :3].astype(int).sum(axis=2) / 3.0
        ink = lum >= 80
        padded = np.pad(ink, 1)
        inkish = np.zeros_like(ink)
        for dy in range(3):
            for dx in range(3):
                inkish |= padded[dy:dy + ink.shape[0], dx:dx + ink.shape[1]]
        rx0, rx1 = ox - 60, ox - 16
        hits = []
        for yy in range(oh):
            y = oy + yy
            ref = lum[y, rx0:rx1][~inkish[y, rx0:rx1]]
            if ref.size == 0:
                continue
            lo, hi = ref.min() - 1.0, ref.max() + 1.0
            for x in range(ox, ox + ow):
                if not inkish[y, x] and not (lo <= lum[y, x] <= hi):
                    hits.append((x, y, round(float(lum[y, x]), 1)))
        assert hits == [], f"{len(hits)} disc-signature pixels in the slot: {hits[:5]}"


# ---------------------------------------------------------------------------
# Round 38 (Alec, SL-23): the plate grows to 2 x 286 (right edge pinned) so
# the play button IS the pill's geometric center; empty space after "next"
# mirrors the left half. (nav_more rode the pill's left edge here; SL-26/27
# moved it INTO the pill's top-right slot.)
# ---------------------------------------------------------------------------

class TestPlayButtonIsPillCenter:
    """Alec: 'left half and right half relative to the play button even.'"""

    @staticmethod
    def _playing(app, ctx):
        app.authenticated = True
        nirvana = _artist("Nirvana")
        track = _track("Lithium", nirvana, _album("Nevermind", nirvana), ms=257_000)
        app.player = sl_models.PlayerState(is_playing=True, progress_ms=30_500, track=track,
                                           device=None, shuffle=False, repeat="off")
        app._player_synced_at = app.now_monotonic
        _tick(app, ctx, 2)

    def _hit_center(self, app, action):
        hit = next(r for r in app._hits if r.action == action)
        return hit.x + hit.w / 2, hit.y + hit.h / 2

    def test_play_center_is_the_pill_center_at_several_widths(self, app_ctx):
        app, ctx, buf = app_ctx
        self._playing(app, ctx)
        for w in (1280.0, 1100.0, 940.0):
            ctx.logical_width_px = w
            app.invalidate()
            _tick(app, ctx, 2)
            px, py, pw, ph = sl_views.pill_rect(w, 800)
            cx, cy = self._hit_center(app, "toggle_play")
            assert cx == pytest.approx(px + pw / 2, abs=1e-6), \
                f"play centered at width {w}"
            assert cy == pytest.approx(py + 87.0, abs=1e-6), \
                "the row's vertical slot is unchanged (SL-23 is an x-axis move)"
            prev_cx, _ = self._hit_center(app, "prev")
            next_cx, _ = self._hit_center(app, "next")
            assert (prev_cx + next_cx) / 2 == pytest.approx(px + pw / 2, abs=1e-6), \
                "the whole transport is symmetric about the plate center"

    def test_the_right_half_after_next_is_empty(self, app_ctx):
        app, ctx, buf = app_ctx
        self._playing(app, ctx)
        px, py, pw, ph = sl_views.pill_rect(1280, 800)
        nxt = next(r for r in app._hits if r.action == "next")
        right_margin = px + pw
        assert right_margin - (nxt.x + nxt.w) >= 60.0, \
            "the space after 'next' mirrors the left half"
        for hit in app._hits:
            if hit is nxt or hit.action == "seek_bar":
                continue
            row_overlap = hit.y < py + ph and hit.y + hit.h > py + 60
            assert not (row_overlap and hit.x > nxt.x + nxt.w and hit.x < right_margin), \
                f"{hit.action} sits in the mirrored empty half"

    def test_pill_growth_lands_on_the_left_edge_only(self, app_ctx):
        app, ctx, buf = app_ctx
        self._playing(app, ctx)
        px, _, pw, _ = sl_views.pill_rect(1280, 800)
        assert pw == 572.0 and px + pw == 1280.0 - 16.0
        seek = next(r for r in app._hits if r.action == "seek_bar")
        assert seek.x == pytest.approx(px + 110.0), \
            "the SL-21 text-column alignment still holds on the new plate"
        assert seek.w == pytest.approx(394.0), \
            "SL-26/27: the bar spans the narrowed column — right edge clear of the merged ⋯ menu"

    def test_nav_more_gap_is_12pt_and_rides(self, app_ctx):
        app, ctx, buf = app_ctx
        self._playing(app, ctx)
        px, py, pw, _ = sl_views.pill_rect(1280, 800)
        overflow = next(r for r in app._hits if r.action == "open_devices")
        assert (overflow.x, overflow.y) == (px + pw - 56.0, py + 12.0), \
            "SL-26/27: the ⋯ is attached at the pill's top-right, 12pt insets"
        assert (overflow.x, overflow.y) == (1208.0, 28.0)


# ---------------------------------------------------------------------------
# Round 41 (Alec, SL-26/27): the ⋯ merges into the pill's top-right via
# layout_attach, and the text column yields its slot — the bar keeps the
# SL-25 span rule over the NARROWER column: left edge on the title text
# (110, SL-21 guards), right edge == menu.left − 12 (504 on the 572
# plate). The bar's midpoint (307) sits 21pt right of the play center
# (286) — same accepted art-tile skew, re-derived.
# ---------------------------------------------------------------------------

class TestProgressBarSpansTextColumn:

    @staticmethod
    def _playing(app, ctx):
        app.authenticated = True
        nirvana = _artist("Nirvana")
        track = _track("Lithium", nirvana, _album("Nevermind", nirvana), ms=257_000)
        app.player = sl_models.PlayerState(is_playing=True, progress_ms=30_500, track=track,
                                           device=None, shuffle=False, repeat="off")
        app._player_synced_at = app.now_monotonic
        _tick(app, ctx, 2)

    def test_strip_spans_the_text_column_at_several_widths(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        self._playing(app, ctx)
        for w in (1280.0, 1100.0, 940.0, 800.0):
            ctx.logical_width_px = w
            app.invalidate()
            _tick(app, ctx, 2)
            px, _, pw, _ = sl_views.pill_rect(int(w), 800)
            seek = next(r for r in app._hits if r.action == "seek_bar")
            play = next(r for r in app._hits if r.action == "toggle_play")
            assert seek.x == pytest.approx(px + 110.0), \
                f"left edge off the title text at width {w}"
            menu = next(r for r in app._hits if r.action == "open_devices")
            assert seek.x + seek.w == pytest.approx(menu.x - 12.0), \
                f"bar's right edge != menu.left - gap at width {w} (SL-26/27)"
            assert play.x + play.w / 2 == pytest.approx(px + pw / 2), \
                f"play stays pill-centered (SL-23 stands) at width {w}"

    def test_left_edge_still_meets_the_title_text(self, app_ctx):
        """SL-21 holds: the widening goes right-only, the left edge stays
        glued to the text column — the relationship is a no-op on the new
        natural but still guards a title move."""
        app, ctx, scene_buffer = app_ctx
        self._playing(app, ctx)
        px, _, _, _ = sl_views.pill_rect(1280, 800)
        title = [n for n in _nodes(scene_buffer, TextNode) if n.text == "Lithium"]
        seek = next(r for r in app._hits if r.action == "seek_bar")
        assert title and seek.x == title[0].x == px + 110.0

    def test_the_column_span_numbers_on_the_572_plate(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        self._playing(app, ctx)
        px, _, _, _ = sl_views.pill_rect(1280, 800)
        seek = next(r for r in app._hits if r.action == "seek_bar")
        assert (seek.x, seek.w) == (px + 110.0, 394.0)
        assert seek.x + seek.w == px + 504.0, "right edge == menu.left - 12 (the yielded slot)"
        play = next(r for r in app._hits if r.action == "toggle_play")
        assert (seek.x + seek.w / 2) - (play.x + play.w / 2) == pytest.approx(21.0), \
            "the accepted art-tile skew: bar midpoint 21pt right of the play center"

    def test_the_column_span_holds_idle(self, app_ctx):
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        _tick(app, ctx, 2)
        px, _, _, _ = sl_views.pill_rect(1280, 800)
        strips = [n for n in _nodes(scene_buffer, RoundedRectNode)
                  if n.color_rgba == (70, 70, 70, 255) and n.height == 3]
        assert len(strips) == 1
        assert strips[0].x == px + 110.0 and strips[0].x + strips[0].width == px + 504.0, \
            "idle bar spans the narrowed column too — the geometry is state-invariant"


class TestEffectTools:
    """SL-34 (Alec): visual effects of the old draw_top_scrim/draw_dock_scrim
    kind are MCP-driven, same loop as the layout nudges — effect_apply adds
    or tunes a scrim/gradient band (edge, height, alpha, fade) live on the
    running app and writes the spec through to layout.toml; effect_remove
    deletes it; effect_list inspects. Purely additive: SL-33/SL-35 removed
    both stock scrims, so the app boots with ZERO declared effects — the
    tool brings scrims back only when someone asks, live."""

    def _strips(self, buf, *, top=None, bottom=None, left=None, right=None):
        out = []
        for n in _nodes(buf, RectNode):
            if n.color_rgba[:3] != sl_views.BG[:3] or n.z_index != 6:
                continue
            if top is not None and n.y >= top:
                continue
            if bottom is not None and n.y < bottom:
                continue
            if left is not None and n.x >= left:
                continue
            if right is not None and n.x + n.width <= right:
                continue
            out.append(n)
        return out

    def _apply_dock(self, app):
        """The round-8b dock scrim's exact numbers, as an effect spec."""
        return app.mcp_call("effect_apply", {
            "id": "scrim.dock", "edge": "bottom", "height": 148,
            "fade": 56, "alpha": 240, "margin": 240})

    def test_boots_with_no_effects_and_no_scrims(self, app_ctx):
        """The SL-33/SL-35 state ships: nothing declared, nothing drawn."""
        app, ctx, buf = app_ctx
        app.authenticated = True
        _tick(app, ctx, 2)
        assert app.mcp_call("effect_list", {}) == {"effects": []}
        assert self._strips(buf) == [], "no scrim strips anywhere at boot"

    def test_effect_apply_adds_a_top_scrim_live(self, app_ctx):
        """The SL-33 inversion on demand: the same mechanism that deleted
        the top scrim can bring one back — live, without a code edit."""
        app, ctx, buf = app_ctx
        app.authenticated = True
        _tick(app, ctx, 2)
        result = app.mcp_call("effect_apply", {
            "id": "scrim.top", "edge": "top", "height": 192,
            "fade": 56, "alpha": 240, "margin": 240})
        assert result["persisted"] is True
        assert result["spec"]["edge"] == "top" and result["spec"]["height"] == 192.0
        assert result["rect"] == [240.0, 0.0, 1040.0, 192.0]
        _tick(app, ctx, 2)
        strips = self._strips(buf, top=200.0)
        assert strips, "the applied top scrim renders on the next frame"
        band = [n for n in strips if n.y == 0]
        assert band and band[0].color_rgba[3] == 240 and band[0].height == 136.0
        fade = sorted((n for n in strips if n.y > 0), key=lambda n: n.y)
        alphas = [n.color_rgba[3] for n in fade]
        assert alphas == sorted(alphas, reverse=True), "fade dissolves downward"

    def test_effect_apply_recreates_the_dock_idiom_exactly(self, app_ctx):
        """The removed dock scrim is fully expressible: the round-8b numbers
        as an effect spec render the identical band + fade geometry."""
        app, ctx, buf = app_ctx
        app.authenticated = True
        _tick(app, ctx, 2)
        result = self._apply_dock(app)
        assert result["rect"] == [240.0, 652.0, 1040.0, 148.0]
        _tick(app, ctx, 2)
        strips = sorted(self._strips(buf, bottom=652.0), key=lambda n: n.y)
        assert strips, "the recreated dock scrim renders"
        band = [n for n in strips if n.y == 708.0]
        assert band and band[0].height == 92.0 and band[0].color_rgba[3] == 240, \
            "calm band: 92pt of near-opaque to the window edge"
        fade = [n for n in strips if n.y < 708.0]
        assert len(fade) == 56, "56 one-pixel fade strips, as round 14 shipped"
        alphas = [n.color_rgba[3] for n in fade]
        assert alphas[0] <= 24 and alphas == sorted(alphas), \
            "transparent at the top, monotonically denser downward"

    def test_effect_apply_persists_and_survives_reboot(self, app_ctx):
        app, ctx, _ = app_ctx
        app.authenticated = True
        _tick(app, ctx, 1)
        app.mcp_call("effect_apply", {
            "id": "scrim.top", "edge": "top", "height": 192,
            "fade": 56, "alpha": 240, "margin": 240})
        text = sl_layout.default_path().read_text()
        assert '["scrim.top".effect]' in text
        assert 'edge = "top"' in text and "height = 192.0" in text
        app.init(ctx)  # reboot: the file is the source of truth
        listing = app.mcp_call("effect_list", {})
        assert [e["id"] for e in listing["effects"]] == ["scrim.top"]

    def test_effect_apply_tunes_one_knob_and_keeps_the_rest(self, app_ctx):
        app, ctx, buf = app_ctx
        app.authenticated = True
        _tick(app, ctx, 2)
        self._apply_dock(app)
        result = app.mcp_call("effect_apply", {"id": "scrim.dock", "alpha": 120})
        assert result["spec"] == {"kind": "scrim", "edge": "bottom",
                                  "height": 148.0, "fade": 56.0,
                                  "alpha": 120.0, "margin": 240.0}
        _tick(app, ctx, 2)
        strips = self._strips(buf, bottom=652.0)
        assert strips and max(n.color_rgba[3] for n in strips) == 120, \
            "the live band retunes on the next frame"
        assert "alpha = 120.0" in sl_layout.default_path().read_text()

    def test_effect_remove_clears_live_and_persists(self, app_ctx):
        app, ctx, buf = app_ctx
        app.authenticated = True
        _tick(app, ctx, 2)
        self._apply_dock(app)
        _tick(app, ctx, 2)
        assert self._strips(buf, bottom=652.0), "scrim up before removal"
        result = app.mcp_call("effect_remove", {"id": "scrim.dock"})
        assert result == {"cleared": ["scrim.dock"]}
        _tick(app, ctx, 2)
        assert self._strips(buf, bottom=652.0) == []
        assert "scrim.dock" not in sl_layout.default_path().read_text()
        assert app.mcp_call("effect_remove", {"id": "scrim.dock"}) == {"cleared": []}

    def test_effect_apply_rejects_bad_specs(self, app_ctx):
        app, ctx, _ = app_ctx
        _tick(app, ctx, 1)
        for bad in ({"id": "scrim.x", "edge": "diagonal", "height": 10},
                    {"id": "scrim.x", "edge": "top"},
                    {"id": "scrim.x", "edge": "top", "height": 10, "fade": 11},
                    {"id": "scrim.x", "edge": "top", "height": 10, "alpha": 300},
                    {"id": "scrim.x", "edge": "top", "height": 10, "margin": -1},
                    {"id": "scrim.x", "edge": "top", "height": 10, "alph": 1},
                    {"id": "", "edge": "top", "height": 10}):
            with pytest.raises(sl_layout.LayoutError):
                app.mcp_call("effect_apply", bad)
        assert app.mcp_call("effect_list", {}) == {"effects": []}, \
            "rejections never partially store"

    def test_left_edge_scrim_renders_vertical_strips(self, app_ctx):
        """All four edges are expressible: a left scrim bands at x=0 and
        fades rightward over ~1px vertical strips."""
        app, ctx, buf = app_ctx
        app.authenticated = True
        _tick(app, ctx, 2)
        app.mcp_call("effect_apply", {
            "id": "scrim.left", "edge": "left", "height": 100,
            "fade": 40, "alpha": 200, "margin": 0})
        _tick(app, ctx, 2)
        strips = self._strips(buf, left=100.0)
        assert strips, "left-edge scrim renders"
        band = [n for n in strips if n.x == 0]
        assert band and band[0].width == 60.0 and band[0].color_rgba[3] == 200
        assert band[0].height == 800.0, "the band spans the window height (margin 0)"
        fade = sorted((n for n in strips if n.x > 0), key=lambda n: n.x)
        alphas = [n.color_rgba[3] for n in fade]
        assert alphas == sorted(alphas, reverse=True), "fade dissolves rightward"
        assert all(n.width == 1.0 for n in fade), "~1px strips, no scanline banding"


class TestDrawScrims:
    """The generic scrim draw keeps the round-14/round-10 properties the
    stock scrims had — effect-drawn bands must not reintroduce scanline
    banding or a hard cutoff above the chrome."""

    class _Frame:
        def __init__(self):
            self.rects = []

        def rect(self, **kw):
            self.rects.append(kw)

    DOCK_SPEC = {"kind": "scrim", "edge": "bottom", "height": 148.0,
                 "fade": 56.0, "alpha": 240.0, "margin": 240.0}

    def test_fade_has_no_visible_banding(self):
        capture = self._Frame()
        sl_views.draw_scrims(capture, [self.DOCK_SPEC], width=1280, height=800)
        top = 800 - 148.0
        nodes = [
            RectNode(
                x=sl_views.SIDEBAR_W, y=top, width=1280 - sl_views.SIDEBAR_W,
                height=148.0, color_rgba=(190, 190, 190, 255), z_index=3),
        ]
        nodes += [
            RectNode(
                x=r["x"], y=r["y"], width=r["width"], height=r["height"],
                color_rgba=r["color"], z_index=r["z_index"])
            for r in capture.rects
        ]
        frame = SceneFrame(
            revision=1, logical_width=1280, logical_height=800,
            display_width=1280, display_height=800, ts_ns=0, nodes=tuple(nodes))
        img = rasterize_scene_frame(frame)
        fade = img[int(top):int(top + 56), 700, :3].astype(int)
        steps = int((fade[:-1] - fade[1:]).max())  # darkens downward → positive jumps
        assert steps <= 12, f"scrim fade banding: max row-to-row step {steps}"

    def test_fade_completes_into_a_calm_band_at_any_height(self):
        for h in (800.0, 700.0, 600.0, 520.0):
            frame = self._Frame()
            sl_views.draw_scrims(frame, [self.DOCK_SPEC], width=1280, height=h)
            _, dock_top, _, _ = sl_views.dock_cluster_rect(1280, h)
            strips = sorted(frame.rects, key=lambda r: r["y"])
            assert strips[0]["color"][3] <= 24, f"fade starts transparent at h={h}"
            assert strips[-1]["y"] + strips[-1]["height"] >= h, f"scrim reaches bottom at h={h}"
            done = [r for r in strips if r["color"][3] >= 230]
            assert done, f"scrim reaches near-opaque at h={h}"
            assert done[0]["y"] + done[0]["height"] <= dock_top - 8.0 + 1e-6, \
                f"fade completes into a calm band above the dock at h={h}"


# ---------------------------------------------------------------------------
# SL-36: real Liquid Glass (NSGlassEffectView) BELOW the Metal-drawn pill.
# The scene keeps drawing art/text/controls crisply on top; the pill's own
# simulated plate (fill, border, sheen, highlight, shadow) yields, the window
# clear goes transparent, and an opaque backdrop covers everything but the
# pill zone. Hosts without under-glass capability keep today's drawn plate.
# ---------------------------------------------------------------------------


class TestPillNativeGlass:
    def _bridge(self, monkeypatch, *, capable=True):
        bridge = _FakeNativeBridge()
        bridge.supports_under_glass = capable
        monkeypatch.setattr(app_main, "native_controls", lambda: bridge)
        return bridge

    def _playing(self, app, ctx):
        app.authenticated = True
        nirvana = _artist("Nirvana")
        track = _track("Lithium", nirvana, _album("Nevermind", nirvana), ms=257_000)
        app.player = sl_models.PlayerState(is_playing=True, progress_ms=30_500, track=track,
                                           device=None, shuffle=False, repeat="off")
        app._player_synced_at = app.now_monotonic
        _tick(app, ctx, 2)

    def _pill_surface(self, bridge):
        under = [s for s in bridge.glass if s.placement == "under"]
        assert len(under) == 1, "exactly one under-glass surface (the pill)"
        return under[0]

    def test_pill_glass_surface_created_under_render_view(self, app_ctx, monkeypatch):
        app, ctx, _ = app_ctx
        bridge = self._bridge(monkeypatch)
        self._playing(app, ctx)

        pill = self._pill_surface(bridge)
        px, py, pw, ph = sl_views.pill_rect(1280, 800)
        assert pill.frame == (px, py, pw, ph)
        assert pill.corner_radius == sl_views.glass_silhouette_radius(ph)
        assert pill.style == "regular"
        assert pill.is_visible is True

    def test_pill_glass_absent_without_capability(self, app_ctx, monkeypatch):
        """Vulkan/older-macOS/headless hosts keep the drawn plate exactly as
        today — no native surface, opaque clear, plate nodes present."""
        app, ctx, scene_buffer = app_ctx
        bridge = self._bridge(monkeypatch, capable=False)
        self._playing(app, ctx)

        assert bridge.glass == []
        clears = _nodes(scene_buffer, ClearNode)
        assert clears and clears[-1].color_rgba == sl_views.BG
        px, py, pw, ph = sl_views.pill_rect(1280, 800)
        rrects = _nodes(scene_buffer, RoundedRectNode)
        assert any(n.color_rgba == sl_views.GLASS_BORDER and n.x == px and n.y == py
                   and n.width == pw and n.height == ph for n in rrects), \
            "incapable hosts keep the drawn pill plate"

    def test_pill_glass_tracks_layout_moves_and_radius(self, app_ctx, monkeypatch):
        """The pill rect is dynamic (layout nudges, big-pill rounded-rect
        rule): the native plate must follow frame and corner radius."""
        app, ctx, _ = app_ctx
        bridge = self._bridge(monkeypatch)
        self._playing(app, ctx)
        pill = self._pill_surface(bridge)

        app.mcp_call("layout_set", {
            "id": "pill", "rect": {"x": 700, "y": 40, "width": 560, "height": 72}})
        _tick(app, ctx, 2)

        assert pill.frame == (700.0, 40.0, 560.0, 72.0)
        assert pill.destroyed is False
        expected_radius = sl_views.glass_silhouette_radius(72.0)
        assert pill.corner_radius == expected_radius
        assert expected_radius in pill.corner_radius_calls

    def test_drawn_plate_yields_under_native_glass(self, app_ctx, monkeypatch):
        """With real glass beneath, the simulated plate is gone — fill,
        border ring, sheen rows, specular highlight, and shadow plates —
        while the pill's content (art, title, transport) keeps drawing."""
        app, ctx, scene_buffer = app_ctx
        self._bridge(monkeypatch)
        self._playing(app, ctx)

        px, py, pw, ph = sl_views.pill_rect(1280, 800)
        rrects = _nodes(scene_buffer, RoundedRectNode)
        rects = _nodes(scene_buffer, RectNode)
        plate_colors = {(16, 16, 16, 208), (255, 255, 255, 40),
                        sl_views.GLASS_SHADOW_FAR, sl_views.GLASS_SHADOW_NEAR}
        assert [n for n in rrects if n.color_rgba in plate_colors
                and n.x <= px + 2 and n.y <= py + 6
                and n.x + n.width >= px + pw - 2] == [], \
            "no simulated plate pieces at the pill silhouette"
        assert [n for n in rects if n.color_rgba == sl_views.GLASS_HIGHLIGHT
                and n.y == py + 1] == [], "no specular highlight under real glass"
        texts = _texts(scene_buffer)
        assert "Lithium" in texts, "pill content keeps drawing on top"

    def test_clear_transparent_and_no_scene_base_when_material_live(
            self, app_ctx, monkeypatch):
        """SL-38: under-glass makes the WHOLE window see-through — the clear
        is fully transparent and the scene paints no opaque base anywhere;
        the behind-window Apple material is the only backdrop (pill zone
        included). The opaque SL-36 tiles only return if the native backdrop
        itself fails (TestWindowMaterial)."""
        app, ctx, scene_buffer = app_ctx
        self._bridge(monkeypatch)
        self._playing(app, ctx)

        clears = _nodes(scene_buffer, ClearNode)
        assert clears and all(c.color_rgba == (0, 0, 0, 0) for c in clears), \
            "window clear must be fully transparent while under-glass is live"
        bg_rects = [n for n in _nodes(scene_buffer, RectNode)
                    if n.color_rgba == sl_views.BG and n.z_index == 0]
        assert bg_rects == [], \
            "no opaque scene base once the window material provides the backdrop"

    def test_pill_glass_destroyed_on_logout(self, app_ctx, monkeypatch):
        app, ctx, _ = app_ctx
        bridge = self._bridge(monkeypatch)
        self._playing(app, ctx)
        pill = self._pill_surface(bridge)

        # _end_session invalidates; a direct flag flip must do the same or
        # the render-on-invalidation loop never re-syncs the surfaces.
        app.authenticated = False
        app.invalidate()
        _tick(app, ctx, 2)

        assert pill.destroyed is True
        assert [s for s in bridge.glass if s.placement == "under"
                and not s.destroyed] == []

    def test_scene_plate_fills_the_pill_silhouette_under_native_glass(
            self, app_ctx, monkeypatch):
        """SL-40: under the native glass the scene carries its own alpha'd
        plate so the capsule reads as one surface over any backdrop. Round
        66 (Alec): the plate fill IS the nav circles' family — "i want them
        all to be like the home and search buttons" — MATERIAL_PLATE_FILL
        while the window material is live, the exact fill the home/search
        circle plates carry; the native glass already owns the edge/blur."""
        app, ctx, scene_buffer = app_ctx
        self._bridge(monkeypatch)
        self._playing(app, ctx)

        px, py, pw, ph = sl_views.pill_rect(1280, 800)
        plates = [n for n in _nodes(scene_buffer, RoundedRectNode)
                  if n.color_rgba == sl_views.MATERIAL_PLATE_FILL
                  and (n.x, n.y, n.width, n.height) == (px, py, pw, ph)]
        assert len(plates) == 1, "exactly one scene plate under the pill contents"
        plate = plates[0]
        assert plate.radius == sl_views.glass_silhouette_radius(ph), \
            "the plate silhouette matches the native glass corner"
        assert plate.z_index == 10, "the plate sits below the pill contents"
        circle_fills = [n for n in _nodes(scene_buffer, RoundedRectNode)
                        if n.width == 42 and n.height == 42
                        and n.color_rgba == sl_views.MATERIAL_PLATE_FILL]
        assert circle_fills and all(n.color_rgba == plate.color_rgba
                                    for n in circle_fills), \
            "the pill plate IS the nav circles' plate fill (the active circle retints)"
        discs = [n for n in _nodes(scene_buffer, CircleNode) if n.radius == 16]
        assert discs and all(n.z_index > plate.z_index for n in discs), \
            "the play disc stays above the plate"

    def test_pill_plate_composites_uniformly_over_gap_and_cards(
            self, app_ctx, monkeypatch):
        """Rasterizer histogram: the pill region's alpha floor lands in the
        frost window across the whole capsule — over the dark gap and the
        card backdrop alike — and nothing bleeds outside the glass frame.
        Round 66: the plate is the nav circles' own fill, so the interior
        composite IS the circles' fill-over-halo stack — fill 90 over the
        halo pair (near 32 over far 17) over clear ≈ 119."""
        app, ctx, scene_buffer = app_ctx
        self._bridge(monkeypatch)
        self._playing(app, ctx)
        app.view = "library"
        app.playlists = [_playlist("Roadtrip"), _playlist("Focus")]
        app.invalidate()
        _tick(app, ctx, 2)

        frame = scene_buffer.latest_frame()
        img = rasterize_scene_frame(frame)
        px, py, pw, ph = (int(v) for v in sl_views.pill_rect(1280, 800))
        # Inset past the corner arcs (the silhouette radius cuts deeper than
        # a uniform 6px inset) so the floor samples the plate body.
        inset = int(sl_views.glass_silhouette_radius(ph)) + 6
        region = img[py + 6:py + ph - 6, px + inset:px + pw - inset, 3]
        floor = int(region.min())
        assert 112 <= floor <= 126, \
            f"pill-region alpha floor {floor} outside the nav-circle frost window"
        # Nothing bleeds outside the glass frame: above the card grid, the
        # column just left of the pill stays fully transparent.
        assert int(img[py + ph // 2, px - 8, 3]) == 0

    def test_scene_plate_only_draws_under_native_glass(self, app_ctx, monkeypatch):
        """Bridgeless/incapable hosts keep the simulated plate — built from
        the same family fill the nav circles use (round 66) — and the bare
        full-rect scene plate stays a native-glass-only companion."""
        app, ctx, scene_buffer = app_ctx
        self._bridge(monkeypatch, capable=False)
        self._playing(app, ctx)

        px, py, pw, ph = sl_views.pill_rect(1280, 800)
        rrects = _nodes(scene_buffer, RoundedRectNode)
        assert any(n.color_rgba == sl_views.GLASS_FILL
                   and (n.x, n.y, n.width, n.height) == (px + 1, py + 1, pw - 2, ph - 2)
                   for n in rrects), \
            "the fallback plate is the nav circles' family fill, inset like theirs"
        assert [n for n in rrects if n.color_rgba[:3] == (16, 16, 16)] == [], \
            "the dark pill fills are gone everywhere"
        assert [n for n in rrects
                if (n.x, n.y, n.width, n.height) == (px, py, pw, ph)
                and n.color_rgba == sl_views.GLASS_FILL] == [], \
            "the bare full-rect plate is a native-glass-only companion"

    def test_pill_plate_carries_the_nav_halo_family(self, app_ctx, monkeypatch):
        """SL-40 follow-up: the bare plate read flush against content —
        "looks flat compared to the other pills" (Alec's screenshot). The
        home/search circles lift off via the _glass_plate shadow pair; the
        pill carries the same halo family (material-softened while the
        window material is live) beneath the plate — drop-shadow idiom,
        offset below the capsule only."""
        app, ctx, scene_buffer = app_ctx
        self._bridge(monkeypatch)
        self._playing(app, ctx)

        px, py, pw, ph = sl_views.pill_rect(1280, 800)
        radius = sl_views.glass_silhouette_radius(ph)
        rrects = _nodes(scene_buffer, RoundedRectNode)
        far = [n for n in rrects if n.color_rgba == sl_views.MATERIAL_SHADOW_FAR
               and (n.x, n.y, n.width, n.height) == (px - 1, py + 5, pw + 2, ph)]
        near = [n for n in rrects if n.color_rgba == sl_views.MATERIAL_SHADOW_NEAR
                and (n.x, n.y, n.width, n.height) == (px, py + 2, pw, ph)]
        assert len(far) == 1, "one far halo plate at the family's offset rect"
        assert len(near) == 1, "one near halo plate at the family's offset rect"
        assert far[0].radius == radius and near[0].radius == radius, \
            "the halo silhouette matches the pill glass corner"
        assert far[0].z_index == 10 and near[0].z_index == 10, \
            "the halo rides at the plate's z"
        chrome_halos = [n for n in rrects
                        if n.color_rgba == sl_views.MATERIAL_SHADOW_FAR and n.z_index == 10]
        assert len(chrome_halos) >= 2, \
            "the pill halo shares the nav buttons' shadow family"
        nodes = list(scene_buffer.latest_frame().nodes)
        plate_idx = next(i for i, n in enumerate(nodes)
                         if getattr(n, "color_rgba", None) == sl_views.MATERIAL_PLATE_FILL
                         and (n.x, n.y, n.width, n.height) == (px, py, pw, ph))
        assert nodes.index(far[0]) < plate_idx, "the far halo draws beneath the plate"
        assert nodes.index(near[0]) < plate_idx, "the near halo draws beneath the plate"

    def test_pill_halo_uses_the_full_strength_family_without_the_material(
            self, app_ctx, monkeypatch):
        """Pill glass live with the window material rejected: the halo
        follows the nav buttons' non-material family — GLASS_SHADOW_* at the
        same offset rects."""
        app, ctx, scene_buffer = app_ctx
        bridge = self._bridge(monkeypatch)
        bridge.backdrop_error = RuntimeError("backdrop rejected")
        self._playing(app, ctx)

        assert app._pill_glass_live, "the pill glass still lands"
        assert not app._window_material_live, "the backdrop was rejected"
        px, py, pw, ph = sl_views.pill_rect(1280, 800)
        rrects = _nodes(scene_buffer, RoundedRectNode)
        far = [n for n in rrects if n.color_rgba == sl_views.GLASS_SHADOW_FAR
               and (n.x, n.y, n.width, n.height) == (px - 1, py + 5, pw + 2, ph)]
        near = [n for n in rrects if n.color_rgba == sl_views.GLASS_SHADOW_NEAR
                and (n.x, n.y, n.width, n.height) == (px, py + 2, pw, ph)]
        assert len(far) == 1 and len(near) == 1

    def test_pill_halo_bleeds_softly_below_and_never_above(
            self, app_ctx, monkeypatch):
        """Rasterizer: the halo composites as a soft drop below the capsule
        (material-family shadow over clear) while the row above the pill
        stays fully transparent — a drop shadow, not a glow."""
        app, ctx, scene_buffer = app_ctx
        self._bridge(monkeypatch)
        self._playing(app, ctx)
        app.view = "library"
        app.playlists = [_playlist("Roadtrip"), _playlist("Focus")]
        app.invalidate()
        _tick(app, ctx, 2)

        frame = scene_buffer.latest_frame()
        img = rasterize_scene_frame(frame)
        px, py, pw, ph = (int(v) for v in sl_views.pill_rect(1280, 800))
        inset = int(sl_views.glass_silhouette_radius(ph)) + 6
        strip = img[py + ph + 1, px + inset:px + pw - inset, 3]
        floor = int(strip.min())
        assert 20 <= floor <= 90, \
            f"halo alpha {floor} below the pill outside the soft-shadow band"
        above = img[py - 2, px + inset:px + pw - inset, 3]
        assert int(above.max()) == 0, "no halo above the capsule"


# ---------------------------------------------------------------------------
# SL-38: the whole window is glass. One window-spanning behind-window Apple
# material replaces the scene's near-black base ("make the entire app
# background transparent instead of black"); component fills alpha down so
# the blur material reads through, while text/icons/borders stay opaque.
# Hosts without under-glass capability keep today's opaque look, and a host
# that rejects the backdrop surface keeps the SL-36 opaque tiles.
# ---------------------------------------------------------------------------


class TestWindowMaterial:
    def _bridge(self, monkeypatch, *, capable=True):
        bridge = _FakeNativeBridge()
        bridge.supports_under_glass = capable
        monkeypatch.setattr(app_main, "native_controls", lambda: bridge)
        return bridge

    def _playing(self, app, ctx, *, show_devices=False):
        app.authenticated = True
        nirvana = _artist("Nirvana")
        track = _track("Lithium", nirvana, _album("Nevermind", nirvana), ms=257_000)
        app.player = sl_models.PlayerState(is_playing=True, progress_ms=30_500, track=track,
                                           device=None, shuffle=False, repeat="off")
        app._player_synced_at = app.now_monotonic
        app.show_devices = show_devices
        _tick(app, ctx, 2)

    def _library(self, app, ctx):
        app.view = "library"
        app.playlists = [_playlist("Roadtrip"), _playlist("Focus")]
        app.invalidate()
        _tick(app, ctx, 2)

    def _backdrop(self, bridge):
        backdrops = [s for s in bridge.glass if s.placement == "backdrop"]
        assert len(backdrops) == 1, "exactly one window backdrop surface"
        return backdrops[0]

    def test_window_backdrop_spans_window(self, app_ctx, monkeypatch):
        app, ctx, _ = app_ctx
        bridge = self._bridge(monkeypatch)
        self._playing(app, ctx)

        backdrop = self._backdrop(bridge)
        assert backdrop.frame == (0.0, 0.0, 1280.0, 800.0)
        assert backdrop.is_visible is True
        assert app._window_material_live is True

    def test_backdrop_tracks_window_resize(self, app_ctx, monkeypatch):
        app, ctx, _ = app_ctx
        bridge = self._bridge(monkeypatch)
        self._playing(app, ctx)
        backdrop = self._backdrop(bridge)

        ctx.logical_width_px = 1000
        ctx.logical_height_px = 700
        app.invalidate()
        _tick(app, ctx, 2)

        assert backdrop.frame == (0.0, 0.0, 1000.0, 700.0)
        assert backdrop.destroyed is False

    def test_backdrop_failure_keeps_opaque_scene_tiles(self, app_ctx, monkeypatch):
        """A host that rejects the backdrop keeps the SL-36 fallback: pill
        glass live, opaque scene tiles around it — never a raw desktop bleed
        with no material. The failure latches off (no per-frame retry)."""
        app, ctx, scene_buffer = app_ctx
        bridge = self._bridge(monkeypatch)
        bridge.backdrop_error = RuntimeError("no backdrop for you")
        self._playing(app, ctx)

        assert [s for s in bridge.glass if s.placement == "backdrop"] == []
        assert app._window_material_live is False
        pills = [s for s in bridge.glass if s.placement == "under" and not s.destroyed]
        assert len(pills) == 1, "pill glass stays live when the backdrop fails"
        bg_rects = [n for n in _nodes(scene_buffer, RectNode)
                    if n.color_rgba == sl_views.BG and n.z_index == 0]
        assert len(bg_rects) == 4, "opaque scene tiles backstop the failed backdrop"

        created = len(bridge.glass)
        _tick(app, ctx, 2)
        assert len(bridge.glass) == created, "backdrop failure latches off"

    def test_backdrop_destroyed_on_logout(self, app_ctx, monkeypatch):
        app, ctx, scene_buffer = app_ctx
        bridge = self._bridge(monkeypatch)
        self._playing(app, ctx)
        backdrop = self._backdrop(bridge)

        app.authenticated = False
        app.invalidate()
        _tick(app, ctx, 2)

        assert backdrop.destroyed is True
        assert app._window_material_live is False
        clears = _nodes(scene_buffer, ClearNode)
        assert clears and clears[-1].color_rgba == sl_views.BG, \
            "logged-out hosts return to the opaque near-black clear"

    def test_card_and_sidebar_fills_alpha_when_material_live(self, app_ctx, monkeypatch):
        """Alec's callout: the opaque dark-gray cards blocked the effect.
        Over the live material, plates switch from the near-invisible white
        tint (designed for an opaque near-black base) to alpha'd dark fills
        in the tasteful 0.5–0.75 window so the blur reads through."""
        app, ctx, scene_buffer = app_ctx
        self._bridge(monkeypatch)
        self._playing(app, ctx)
        self._library(app, ctx)

        rrects = _nodes(scene_buffer, RoundedRectNode)
        assert any(n.color_rgba == sl_views.MATERIAL_PLATE_FILL for n in rrects), \
            "cards/sidebar alpha down over the window material"
        assert 64 <= sl_views.MATERIAL_PLATE_FILL[3] <= 128, \
            "frost trial: fills sit below the old 0.5–0.75 window — the stack " \
            "composite, not the fill alone, targets the 120–150 card-body floor"
        assert [n for n in rrects if n.color_rgba == sl_views.GLASS_FILL] == [], \
            "no white-tint plates while the material is live"

    def test_fills_unchanged_when_material_not_live(self, app_ctx, monkeypatch):
        """Bridgeless/incapable hosts keep today's plate language byte-for-byte."""
        app, ctx, scene_buffer = app_ctx
        self._bridge(monkeypatch, capable=False)
        self._playing(app, ctx)
        self._library(app, ctx)

        rrects = _nodes(scene_buffer, RoundedRectNode)
        assert any(n.color_rgba == sl_views.GLASS_FILL for n in rrects), \
            "incapable hosts keep the white-tint plate fill"
        assert [n for n in rrects
                if n.color_rgba == getattr(sl_views, "MATERIAL_PLATE_FILL", None)] == []

    def test_text_stays_opaque_over_material(self, app_ctx, monkeypatch):
        """Legibility is the constraint: fills alpha down, text does not."""
        app, ctx, scene_buffer = app_ctx
        self._bridge(monkeypatch)
        self._playing(app, ctx)
        self._library(app, ctx)

        headings = [n for n in _nodes(scene_buffer, TextNode) if n.text == "Your Library"]
        assert headings, "library heading drawn"
        assert all(n.color_rgba[3] == 255 for n in headings), \
            "text stays fully opaque over the material"

    def test_popup_fill_alphad_when_material_live(self, app_ctx, monkeypatch):
        """The playback popup is the darkest floating panel: it keeps the
        most body (top of the alpha window) but still lets the material read."""
        app, ctx, scene_buffer = app_ctx
        self._bridge(monkeypatch)
        self._playing(app, ctx, show_devices=True)

        plates = [n for n in _nodes(scene_buffer, RoundedRectNode)
                  if n.width == 298 and n.color_rgba == sl_views.MATERIAL_POPUP_FILL]
        assert plates, "popup plate alphas down over the material"
        assert sl_views.MATERIAL_PLATE_FILL[3] < sl_views.MATERIAL_POPUP_FILL[3] <= 160, \
            "the popup keeps the most body inside the frost window"
        popup_floor = self._stack_floor(sl_views.MATERIAL_SHADOW_FAR[3],
                                        sl_views.MATERIAL_SHADOW_NEAR[3],
                                        30,  # the popup's own hairline border
                                        sl_views.MATERIAL_POPUP_FILL[3])
        assert 120.0 <= popup_floor <= 165.0, \
            f"popup stack composites to {popup_floor:.1f} — most body, still glass"
        assert [n for n in _nodes(scene_buffer, RoundedRectNode)
                if n.color_rgba == (18, 18, 18, 234)] == [], \
            "the near-opaque popup fill is gone while the material is live"

    @staticmethod
    def _stack_floor(*alphas: float) -> float:
        """f32 source-over composite, bottom-up from the transparent clear —
        the same math the rasterizer and the GPU blend apply per pixel."""
        d = 0.0
        for a in alphas:
            d = 255.0 - (255.0 - d) * (1.0 - a / 255.0)
        return d

    @staticmethod
    def _base_material_fills(frame):
        """Material plate fills that sit on the clear (cards, rail, dock
        circles) — NOT plates nested on another material plate (the active
        nav row, the account chip), whose floor legitimately composites over
        the host plate's ~130 body instead of over the clear. Round 66: the
        pill's native-glass plate also carries the family fill, but it skips
        the scene border ring (the glass owns the edge), so its floor stacks
        one ring shallower than the card-body band — out of scope here."""
        pill = sl_views.pill_rect(frame.logical_width, frame.logical_height)
        fills = [n for n in frame.nodes if isinstance(n, RoundedRectNode)
                 and n.color_rgba == sl_views.MATERIAL_PLATE_FILL
                 and (n.x, n.y, n.width, n.height) != pill]
        base = []
        for i, n in enumerate(fills):
            cx, cy = n.x + n.width / 2.0, n.y + n.height / 2.0
            nested = any(m.x <= cx <= m.x + m.width and m.y <= cy <= m.y + m.height
                         for m in fills[:i])
            if not nested:
                base.append(n)
        return base

    def test_frost_trial_card_body_composite_window(self, app_ctx, monkeypatch):
        """Frost trial (round 62): the first material pass composited card
        bodies to ~205/255 over the clear (~80% opacity — reads solid on a
        dark desktop). The retune halves the shadow-tint stack and drops the
        fills so card bodies land in the 120–150 frost window (about 50%
        bleed-through). Pins the constant stack math, headlessly."""
        self._bridge(monkeypatch)
        floor = self._stack_floor(sl_views.MATERIAL_SHADOW_FAR[3],
                                  sl_views.MATERIAL_SHADOW_NEAR[3],
                                  sl_views.MATERIAL_BORDER[3],
                                  sl_views.MATERIAL_PLATE_FILL[3])
        assert 120.0 <= floor <= 150.0, \
            f"card-body stack composites to {floor:.1f}, outside the 120–150 frost window"

    def test_frost_trial_softens_the_shadow_tint_stack(self, app_ctx, monkeypatch):
        """The a34/a64/a36 shadow-tint stack under material plates softens in
        material mode — otherwise the black under-stack (113 alpha on its
        own) dominates the composite and reads as muddy blobs, not frost."""
        app, ctx, scene_buffer = app_ctx
        self._bridge(monkeypatch)
        self._playing(app, ctx)
        self._library(app, ctx)

        rrects = _nodes(scene_buffer, RoundedRectNode)
        assert any(n.color_rgba == sl_views.MATERIAL_SHADOW_FAR for n in rrects), \
            "material-mode plates draw the softened far shadow"
        assert any(n.color_rgba == sl_views.MATERIAL_SHADOW_NEAR for n in rrects), \
            "material-mode plates draw the softened near shadow"
        assert any(n.color_rgba == sl_views.MATERIAL_BORDER for n in rrects), \
            "the hairline border ring softens with the stack"
        full = (sl_views.GLASS_SHADOW_FAR, sl_views.GLASS_SHADOW_NEAR)
        assert [n for n in rrects if n.color_rgba in full] == [], \
            "no full-strength shadow plates survive while the material is live"

    def test_frost_trial_rasterized_card_floor(self, app_ctx, monkeypatch):
        """Rasterizer histogram: card-body alpha floors land in the 120–150
        frost window, gaps stay exactly 0, art/glyphs stay opaque."""
        app, ctx, scene_buffer = app_ctx
        self._bridge(monkeypatch)
        self._playing(app, ctx)
        self._library(app, ctx)

        frame = scene_buffer.latest_frame()
        img = rasterize_scene_frame(frame)
        fills = self._base_material_fills(frame)
        assert fills, "material cards/rail drawn"
        floors = []
        for n in fills:
            # Inset past the border ring AA and the shadowless top rows so
            # the floor samples the fully stacked card body.
            x0, y0 = int(n.x) + 8, int(n.y) + 10
            x1, y1 = int(n.x + n.width) - 8, int(n.y + n.height) - 8
            if x1 <= x0 or y1 <= y0:
                continue
            floors.append(int(img[y0:y1, x0:x1, 3].min()))
        assert floors, "sampled card interiors"
        assert all(120 <= f <= 150 for f in floors), \
            f"card-body floors {sorted(set(floors))} outside the 120–150 frost window"
        assert int(img[..., 3].min()) == 0, "gaps stay fully transparent"
        assert int(img[..., 3].max()) == 255, "art/glyphs stay opaque"

    def test_frost_trial_probe_expectations_track_the_retune(self, app_ctx, monkeypatch):
        """The drawable probe's composite-aware expectations derive from the
        frame, so they track the retune automatically: material fills report
        expected ≈130 (the stack composite), the gap region reports 0."""
        from luvatrix_core.core.drawable_probe import default_probe_regions
        app, ctx, scene_buffer = app_ctx
        self._bridge(monkeypatch)
        self._playing(app, ctx)
        self._library(app, ctx)

        frame = scene_buffer.latest_frame()
        regions = default_probe_regions(frame)
        fills = [r for r in regions
                 if r.name.endswith(f"_a{sl_views.MATERIAL_PLATE_FILL[3]}")]
        assert fills, "probe auto-regions track the retuned fill alpha"
        # Card-body fills sit on the clear; plates nested on another material
        # plate (active nav row) composite over its ~130 body instead.
        base_nodes = self._base_material_fills(frame)
        base = [r for r in fills
                if any(abs((r.x + r.width / 2.0) - (n.x + n.width / 2.0)) < 4.0
                       and abs((r.y + r.height / 2.0) - (n.y + n.height / 2.0)) < 4.0
                       for n in base_nodes)]
        assert base, "card-body probe regions found"
        assert all(128 <= r.expected_alpha <= 132 for r in base), \
            f"composite expectations {[r.expected_alpha for r in base]} miss the ~130 floor"
        gaps = [r for r in regions if r.name.startswith("gap")]
        assert gaps and all(r.expected_alpha == 0 for r in gaps), \
            "the gap region keeps its zero expectation"


# ---------------------------------------------------------------------------
# SL-41 retained scroll hot path: content-space scene + GPU content offset
# ---------------------------------------------------------------------------
class TestCaretIdleGating:
    """Round 68 (macOS idle churn, measured on d0504a2): the focused-field
    heartbeat invalidated on EVERY app-loop tick so the caret could blink.
    With the loop running at present rate (120fps on macOS) a focused field
    rendered 120 frames/s at idle — the scene dedup caught the identical
    ones, but the renders themselves are pure battery burn. The heartbeat
    only needs a redraw when the caret's 2Hz phase flips."""

    @staticmethod
    def _count_invalidations(app, monkeypatch) -> list[int]:
        count = [0]
        original = app.invalidate

        def counting() -> None:
            count[0] += 1
            original()

        monkeypatch.setattr(app, "invalidate", counting)
        return count

    def test_focused_field_invalidates_only_on_caret_phase_flip(self, app_ctx, monkeypatch):
        app, ctx, _ = app_ctx
        _tick(app, ctx, 2)
        count = self._count_invalidations(app, monkeypatch)
        clock = [1000.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])
        app.search_focused = True
        # 30 timer heartbeats spanning 0.3s — inside a single 0.5s caret phase.
        for _ in range(30):
            clock[0] += 0.01
            app._handle_timers()
        assert count[0] <= 2, (
            f"focused idle field invalidated {count[0]}x in 0.3s — "
            "expected a redraw only on caret phase flips"
        )

    def test_focused_field_still_blinks_the_caret(self, app_ctx, monkeypatch):
        app, ctx, _ = app_ctx
        _tick(app, ctx, 2)
        count = self._count_invalidations(app, monkeypatch)
        clock = [1000.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])
        app.search_focused = True
        # 2.0s of heartbeats — the caret phase flips ~4 times; blinking must survive.
        for _ in range(40):
            clock[0] += 0.05
            app._handle_timers()
        assert count[0] >= 2, "caret blink must keep invalidating at ~2Hz while focused"

    def test_unfocused_idle_has_no_heartbeat_invalidations(self, app_ctx, monkeypatch):
        app, ctx, _ = app_ctx
        _tick(app, ctx, 2)
        count = self._count_invalidations(app, monkeypatch)
        clock = [1000.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])
        for _ in range(30):
            clock[0] += 0.05
            app._handle_timers()
        assert count[0] == 0, f"untouched window must stay at zero invalidations, got {count[0]}"


class TestScrollContentBand:
    """Round 64 A/B data exonerated the VEV/blur stack at idle-home: the gap
    phase (~13ms/present) is the app rebuilding every primitive per wheel
    tick. The hot path publishes the scrollable content (z 1..4) in stable
    CONTENT coordinates on a retained frame whose content_offset the GPU
    applies; chrome (z>=5: scrollbar, scrims, sidebar, pill, popup, toasts)
    and the z=0 window backstop stay anchored. Wheel ticks become
    transform-only revisions; throttled re-window renders (plus a settle
    render after the gesture) keep culling, hover, and the thumb honest.
    Targets without band support keep today's translate-everything path."""

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _enable_band(ctx) -> None:
        ctx.set_scene_content_z_band_supported(True)

    def _engage(self, app, ctx, ticks: int = 2) -> None:
        """The gesture's first wheel tick ENGAGES the band: it cannot go
        transform-only (no banded frame exists yet), so it falls back to one
        full banded rebuild. Streak ticks after that are transform-only.
        The pre-tick lands the bandless resting frame first — it is what
        publishes the content extent the scroll clamps against."""
        _tick(app, ctx, 2)
        app._mouse = (600.0, 400.0)
        app._apply_scroll(-120.0)
        assert app._render_requested, "the gesture's first tick rebuilds banded"
        assert app._band_engaged, "a visible scroll tick engages the band"
        _tick(app, ctx, ticks)

    @staticmethod
    def _library(app, ctx, count: int = 48):
        app.authenticated = True
        app._bootstrap_done = True
        app.view = "library"
        app.playlists = tuple(_playlist(f"Mix {i:02d}") for i in range(count))

    @staticmethod
    def _tracks(app, ctx, count: int = 200):
        artist = _artist("Nirvana")
        album = _album("Nevermind", artist)
        playlist = _playlist("Biglist", count=count)
        tracks = [_track(f"T{i:03d}", artist, album, n=i + 1) for i in range(count)]
        app.authenticated = True
        app._bootstrap_done = True
        app.playlists = [playlist]
        app.view = "playlist:pl-Biglist"
        app.playlist_detail = (playlist, tracks)

    # -- frame shape --------------------------------------------------------
    def test_resting_frames_stay_bandless_and_unretained(self, app_ctx):
        """THE encode gate: a frame nobody is scrolling through is EXACTLY
        the pre-SL-41 shape — no band, no retained flag, zero offset. Probe-
        driven non-scroll frames must never pay the tier-split tax."""
        app, ctx, buf = app_ctx
        self._enable_band(ctx)
        self._library(app, ctx)
        app.content_scroll = 120.0
        _tick(app, ctx, 2)
        frame = buf.latest_frame()
        assert frame.content_z_band is None, "resting frames carry no z band"
        assert not frame.retained, "resting frames are not retained"
        assert frame.content_offset_y == 0.0, "resting frames bake the translation"

    def test_frame_carries_offset_retained_and_band(self, app_ctx):
        app, ctx, buf = app_ctx
        self._enable_band(ctx)
        self._library(app, ctx)
        self._engage(app, ctx)
        frame = buf.latest_frame()
        assert frame.retained, "the hot path publishes retained frames"
        assert frame.content_z_band == (1.0, 4.0), "content z 1..4 scrolls; chrome z>=5 and backstop z=0 stay"
        assert frame.content_offset_y == 120.0

    def test_content_geometry_is_stable_across_scroll_positions(self, app_ctx):
        """THE rebuild killer: a node that did not change keeps its exact
        content-space y no matter where scroll sits — only the frame's
        offset moves."""
        app, ctx, buf = app_ctx
        self._enable_band(ctx)
        self._library(app, ctx)
        self._engage(app, ctx)
        title_y = next(n.y for n in _nodes(buf, TextNode) if n.text == "Your Library")
        app._mouse = (600.0, 400.0)
        app._apply_scroll(-180.0)  # streak tick: transform-only to 300
        title = next(n for n in _nodes(buf, TextNode) if n.text == "Your Library")
        assert title.y == title_y, "content-space y must not bake the scroll offset"
        assert buf.latest_frame().content_offset_y == 300.0

    def test_chrome_stays_anchored_outside_the_band(self, app_ctx):
        app, ctx, buf = app_ctx
        self._enable_band(ctx)
        self._library(app, ctx)
        app.search_expanded = True  # the library popup is the chrome probe
        self._engage(app, ctx)
        rail = next(n for n in _nodes(buf, TextNode) if n.text == "Spotify Light")
        assert rail.z_index >= 5, "popup chrome must renumber out of the content band"
        rail_y = rail.y
        app._mouse = (600.0, 400.0)
        app._apply_scroll(-180.0)
        _tick(app, ctx, 1)
        rail2 = next(n for n in _nodes(buf, TextNode) if n.text == "Spotify Light")
        assert rail2.y == rail_y, "chrome draws at screen coordinates — no offset baked, ever"

    # -- wheel path ---------------------------------------------------------
    def test_wheel_tick_publishes_a_transform_only_revision(self, app_ctx):
        app, ctx, buf = app_ctx
        self._enable_band(ctx)
        self._tracks(app, ctx)
        self._engage(app, ctx)  # gesture underway: banded frame at 120 exists
        before = buf.latest_frame()
        rev_before = buf.revision

        app._mouse = (600.0, 400.0)
        app._apply_scroll(-120.0)

        assert app.content_scroll == 240.0
        assert not app._render_requested, "a hot-path tick must NOT schedule a rebuild"
        after = buf.latest_frame()
        assert buf.revision == rev_before + 1, "the offset publishes immediately"
        assert after.nodes is before.nodes, "transform-only revision reuses the exact node tuple"
        assert after.content_offset_y == 240.0
        assert after.content_z_band == (1.0, 4.0), "the band survives the transform-only revision"

    def test_wheel_throttled_rewindow_rerenders(self, app_ctx, monkeypatch):
        """Unbounded gestures re-window: when the throttle window elapses the
        tick falls back to a full render (fresh cull window, thumb, hover)."""
        app, ctx, buf = app_ctx
        self._enable_band(ctx)
        self._tracks(app, ctx)
        monkeypatch.setattr(app_main, "SCROLL_REWINDOW_INTERVAL_S", 0.0)
        _tick(app, ctx, 2)

        app._mouse = (600.0, 400.0)
        app._apply_scroll(-120.0)
        assert app._render_requested, "an elapsed throttle window forces a rebuild"
        _tick(app, ctx, 1)
        assert buf.latest_frame().content_offset_y == 120.0

    def test_settle_render_fires_after_the_gesture(self, app_ctx, monkeypatch):
        """The final crisp frame lands once the wheel stream stops — and it
        lands BANDLESS: the settle render disengages the band so the resting
        frame (and every idle frame after it) is the pre-SL-41 shape with
        the translation baked back in."""
        app, ctx, buf = app_ctx
        self._enable_band(ctx)
        self._tracks(app, ctx)
        # The streak must deterministically take the transform-only branch:
        # software-rendered ticks can burn the real 0.1s re-window throttle
        # all by themselves (that path has its own test).
        monkeypatch.setattr(app_main, "SCROLL_REWINDOW_INTERVAL_S", 999.0)
        _tick(app, ctx, 2)  # bandless rest at 0: ground-truth content space
        rest_y = next(n.y for n in _nodes(buf, TextNode) if n.text == "T005")

        app._mouse = (600.0, 400.0)
        app._apply_scroll(-120.0)
        assert app._render_requested, "the first tick engages with a banded rebuild"
        _tick(app, ctx, 2)  # banded frame at 120; the 0.12s settle has not fired
        before = buf.latest_frame()
        assert before.content_z_band == (1.0, 4.0)

        monkeypatch.setattr(app_main, "SCROLL_SETTLE_S", 0.0)
        app._mouse = (600.0, 400.0)  # ticks re-read the (empty) input mouse
        app._apply_scroll(-120.0)  # streak tick: transform-only to 240
        assert not app._render_requested, "a streak tick must not rebuild"
        assert buf.latest_frame().nodes is before.nodes, "the streak stays transform-only"
        assert buf.latest_frame().content_offset_y == 240.0

        _tick(app, ctx, 1)
        after = buf.latest_frame()
        assert after.nodes is not before.nodes, "the settle render rebuilds the window"
        assert after.content_z_band is None, "the settle render rests the band"
        assert after.content_offset_y == 0.0
        title = next(n for n in _nodes(buf, TextNode) if n.text == "T005")
        assert abs(title.y - (rest_y - 240.0)) < 1.0, \
            "the resting frame bakes the translation where the gesture ended"

    def test_sidebar_wheel_still_renders_every_tick(self, app_ctx):
        """Scope: only the content area is on the retained path — the popup
        list's own scroll keeps today's invalidate-per-tick behavior."""
        app, ctx, buf = app_ctx
        self._enable_band(ctx)
        self._tracks(app, ctx)
        # The list needs real scrollable extent: one seeded playlist clamps
        # any wheel to 0 on every implementation.
        app.playlists = tuple(_playlist(f"Rail {i:02d}") for i in range(60))
        app.search_expanded = True  # the list lives in the search-anchored popup
        _tick(app, ctx, 2)

        px, py, pw, ph = sl_views.library_panel_rect(app, WIDTH, HEIGHT)
        app._mouse = (px + pw / 2, py + ph / 2)
        app._apply_scroll(-120.0)
        assert app.sidebar_scroll == 120.0 and app.content_scroll == 0.0
        assert app._render_requested, "popup list scroll still rebuilds per tick"

    # -- input correctness mid-gesture --------------------------------------
    def test_click_dispatches_against_content_space_hits_mid_scroll(self, app_ctx, monkeypatch):
        """Hits recorded at the last render live in content space; a click
        during a transform-only streak maps through the LIVE offset, so rows
        stay clickable while the gesture is still scrolling."""
        app, ctx, buf = app_ctx
        self._enable_band(ctx)
        self._tracks(app, ctx, count=40)
        self._engage(app, ctx)  # banded gesture underway at scroll 120
        region = next(r for r in app._hits if r.action == "play_track_in_context")
        assert region.scrollable, "content hits must be flagged scrollable"

        app._mouse = (600.0, 400.0)
        app._apply_scroll(-200.0)  # transform-only: hits are NOT re-recorded
        calls = []
        monkeypatch.setattr(app, "_dispatch_action",
                            lambda action, payload, x: calls.append((action, payload)))
        # The row now shows at content_y - scroll on screen (120 + 200 live).
        app._dispatch_click(region.x + 4, region.y - 320.0 + 2)
        assert calls and calls[0][0] == "play_track_in_context", \
            "the click must land on the row that sits under the cursor NOW"

    def test_chrome_hits_ignore_the_scroll_offset(self, app_ctx, monkeypatch):
        app, ctx, buf = app_ctx
        self._enable_band(ctx)
        self._tracks(app, ctx, count=40)
        app.search_expanded = True  # the library nav row lives in the popup
        _tick(app, ctx, 2)
        nav = next(r for r in app._hits if r.action == "nav" and r.payload == "library")
        assert not nav.scrollable, "chrome hits stay in screen space"

        app._mouse = (600.0, 400.0)
        app._apply_scroll(-200.0)
        calls = []
        monkeypatch.setattr(app, "_dispatch_action",
                            lambda action, payload, x: calls.append((action, payload)))
        app._dispatch_click(nav.x + 2, nav.y + 2)
        assert calls == [("nav", "library")], "fixed chrome hit regions must not shift"

    # -- culling + scrollbar --------------------------------------------------
    def test_cull_window_covers_viewport_plus_margin(self, app_ctx):
        """The retained window spans the viewport plus one viewport of margin
        on each side — enough that a 100ms re-window throttle can never
        outrun drawn content — but far rows still cull (build cost stays
        proportional to the window, not the library)."""
        app, ctx, buf = app_ctx
        self._enable_band(ctx)
        self._tracks(app, ctx)
        self._engage(app, ctx)  # banded window recentred at scroll 120
        texts = _texts(buf)
        assert "T005" in texts, "rows inside the viewport draw"
        assert "T025" in texts, "rows inside the margin draw"
        assert "T060" not in texts, "rows beyond viewport + margin cull"

        app.content_scroll = 2400.0
        app.invalidate()
        _tick(app, ctx, 2)
        texts = _texts(buf)
        assert "T005" not in texts, "scrolled-past rows cull above the window"
        assert "T060" in texts, "the window recenters on the new offset"
        assert "T199" not in texts, "far-below rows still cull"

    def test_scrollbar_thumb_stays_chrome_and_tracks_renders(self, app_ctx):
        app, ctx, buf = app_ctx
        self._enable_band(ctx)
        self._tracks(app, ctx)
        self._engage(app, ctx)
        thumb = next(n for n in _nodes(buf, RoundedRectNode) if n.x == 1280 - 7)
        assert thumb.z_index == 5, "the thumb is chrome — outside the content band"
        y0 = thumb.y
        app.content_scroll = 2400.0
        app.invalidate()
        _tick(app, ctx, 2)
        thumb2 = next(n for n in _nodes(buf, RoundedRectNode) if n.x == 1280 - 7)
        assert thumb2.y > y0, "re-window renders keep the thumb honest"

    # -- publish hygiene: noise must not churn renders or presents -----------
    def test_noop_ticks_at_the_scroll_bounds_stay_silent(self, app_ctx):
        """Clamped wheel noise (trackpad momentum tails at a boundary) must
        not arm the settle, publish an offset, or schedule a render — the
        pre-SL-41 path deduped these away at submit time."""
        app, ctx, buf = app_ctx
        self._enable_band(ctx)
        self._tracks(app, ctx)
        _tick(app, ctx, 2)
        rev0 = buf.revision
        assert app.content_scroll == 0.0

        app._mouse = (600.0, 400.0)
        app._apply_scroll(60.0)  # clamps to 0: nothing moved
        assert not app._render_requested, "a no-op tick must not render"
        assert app._scroll_settle_due is None, "a no-op tick must not arm the settle"
        _tick(app, ctx, 3)
        assert not app._render_requested
        assert buf.revision == rev0, "a no-op tick must not present either"

    def test_sub_pixel_creep_does_not_publish(self, app_ctx):
        """Sub-pixel trackpad jitter accumulates silently: publishes start at
        a visible delta (0.1 logical px), not at the first float wobble."""
        app, ctx, buf = app_ctx
        self._enable_band(ctx)
        self._tracks(app, ctx)
        _tick(app, ctx, 2)
        rev0 = buf.revision

        app._mouse = (600.0, 400.0)
        app._apply_scroll(-0.05)
        assert app.content_scroll == 0.05
        assert not app._render_requested and buf.revision == rev0, \
            "invisible creep neither renders nor presents"
        app._apply_scroll(-5.0)
        assert app._render_requested, "a visible delta engages the gesture"

    # -- legacy fallback -------------------------------------------------------
    def test_targets_without_band_support_keep_the_legacy_path(self, app_ctx):
        """Vulkan/matrix hosts (and any scene target without the band): the
        app must behave byte-for-byte like today — translated draws, no
        retained frame, whole-frame offset zero."""
        app, ctx, buf = app_ctx
        # Capability deliberately NOT enabled — the fixture default.
        self._library(app, ctx)
        app.content_scroll = 100.0
        _tick(app, ctx, 2)
        frame = buf.latest_frame()
        assert frame.content_z_band is None
        assert not frame.retained
        assert frame.content_offset_y == 0.0
        title = next(n for n in _nodes(buf, TextNode) if n.text == "Your Library")
        assert title.y == 24.0 - 100.0, "legacy draws bake the translation"

        app._mouse = (600.0, 400.0)
        app._apply_scroll(-120.0)
        assert app._render_requested, "legacy wheel ticks invalidate as today"
