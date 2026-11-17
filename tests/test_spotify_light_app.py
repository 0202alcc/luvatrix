"""Headless integration tests for the Spotify Light app UI (examples/spotify_light).

The app is driven through the real luvatrix runtime (manifest load, lifecycle,
scene frame submission) with a noop HDI source, and the emitted scene nodes
are asserted directly. No network access happens: unauthenticated views never
schedule jobs, and authenticated views are given in-memory state.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "examples" / "spotify_light"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from luvatrix_core.core.app_runtime import AppRuntime  # noqa: E402
from luvatrix_core.core.hdi_thread import HDIEvent, HDIThread  # noqa: E402
from luvatrix_core.core.scene_graph import (  # noqa: E402
    ClearNode,
    CpuLayerNode,
    SceneGraphBuffer,
    TextNode,
)
from luvatrix_core.core.sensor_manager import SensorManagerThread  # noqa: E402
from luvatrix_core.core.window_matrix import WindowMatrix  # noqa: E402

import app_main  # noqa: E402
import sl_models  # noqa: E402
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
        matrix=WindowMatrix(WIDTH, HEIGHT),
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
            "Home", "Search", "Your Library", "PLAYLISTS", "Roadtrip", "Focus",
            "Top tracks", "New releases", "Your playlists", "Top artists",
            "Come As You Are", "Nevermind", "Nirvana", "Alec", "Log out",
            "Nothing playing",
        ):
            assert expected in texts, f"missing text: {expected!r}"
        assert any(t.startswith("Good ") for t in texts)
        # Album art placeholders land as CpuLayerNode textures.
        assert _nodes(scene_buffer, CpuLayerNode)
        actions = {region.action for region in app._hits}
        assert {"nav", "open_playlist", "open_card", "logout", "seek_bar", "volume_bar",
                "toggle_play", "open_devices"} <= actions

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


class TestSearchView:
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
                         "Lithium", "Nevermind", "Nirvana", "90s Rock"):
            assert expected in texts, f"missing text: {expected!r}"
        # Track rows outside a playlist context play bare uris.
        assert any(region.action == "play_uris" for region in app._hits)


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
        for expected in ("Lithium", "Nirvana", "4:17", "||", "Connect to a device",
                         "MacBook Pro", "Kitchen Speaker", "Speaker"):
            assert expected in texts, f"missing text: {expected!r}"
        # Elapsed-time label reflects interpolated progress near 0:30/0:31.
        assert any(t in ("0:30", "0:31") for t in texts)
        actions = {region.action for region in app._hits}
        assert {"toggle_shuffle", "prev", "next", "cycle_repeat", "pick_device"} <= actions
