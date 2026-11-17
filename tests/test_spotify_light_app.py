"""Headless integration tests for the Spotify Light app UI (examples/spotify_light).

The app is driven through the real luvatrix runtime (manifest load, lifecycle,
scene frame submission) with a noop HDI source, and the emitted scene nodes
are asserted directly. No network access happens: unauthenticated views never
schedule jobs, and authenticated views are given in-memory state.
"""
from __future__ import annotations

import json
import sys
import threading
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
    ClearNode,
    CpuLayerNode,
    RectNode,
    SceneGraphBuffer,
    TextNode,
)
from luvatrix_core.core.sensor_manager import SensorManagerThread  # noqa: E402
from luvatrix_core.core.window_matrix import WindowMatrix  # noqa: E402

import app_main  # noqa: E402
import sl_models  # noqa: E402
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
                         "Lithium", "Nevermind", "Nirvana"):
            assert expected in texts, f"missing text: {expected!r}"
        # Track rows outside a playlist context play bare uris.
        assert any(region.action == "play_uris" for region in app._hits)

        # The playlist card sits below the fold at 1280x800; scroll to reveal it.
        app.content_scroll = 480.0
        app.invalidate()
        _tick(app, ctx, 2)
        assert "90s Rock" in _texts(scene_buffer)


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

    def set_frame(self, x, y, width, height):
        self.frame = (x, y, width, height)

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
    def __init__(self, *, x, y, width, height, corner_radius=0.0, style="regular"):
        self.frame = (x, y, width, height)
        self.corner_radius = corner_radius
        self.style = style
        self.is_visible = True
        self.destroyed = False

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
        self.created: list[_FakeNativeField] = []
        self.glass: list[_FakeGlassSurface] = []

    def create_text_field(self, **kwargs):
        field = _FakeNativeField(**kwargs)
        self.created.append(field)
        return field

    def create_glass_surface(self, **kwargs):
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
        # Same rect the drawn field uses: x=cx-190, y=height*0.42+84, 380x40.
        assert field.frame == (450.0, 420.0, 380.0, 40.0)
        texts = _texts(scene_buffer)
        assert "Client ID" not in texts  # drawn placeholder replaced by the native field
        assert any("developer.spotify.com/dashboard" in t for t in texts)  # instructions stay
        actions = {region.action for region in app._hits}
        assert "focus_client_id" not in actions
        assert "save_client_id" not in actions  # disabled while the draft is empty

        # Typing into the native field flows into the app draft and arms Save.
        field.set_value("abc-123")
        assert app.client_id_draft == "abc-123"
        _tick(app, ctx, 1)
        assert "save_client_id" in {region.action for region in app._hits}

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


class TestGlassSurfaces:
    """Liquid Glass: app-declared glass regions via the native-controls bridge."""

    def test_login_field_glass_container_borderless_field(self, app_ctx, monkeypatch):
        app, ctx, _ = app_ctx
        bridge = _FakeNativeBridge()
        monkeypatch.setattr(app_main, "native_controls", lambda: bridge)

        _tick(app, ctx, 2)

        containers = [g for g in bridge.glass if g.style == "regular"]
        assert len(containers) == 1
        container = containers[0]
        assert container.frame == (450.0, 420.0, 380.0, 40.0)
        assert container.corner_radius == 20.0
        field = bridge.created[0]
        assert field.within is container
        assert field.bordered is False

    def test_chrome_glass_for_sidebar_and_player_bar(self, app_ctx, monkeypatch):
        app, ctx, _ = app_ctx
        app.authenticated = True
        bridge = _FakeNativeBridge()
        monkeypatch.setattr(app_main, "native_controls", lambda: bridge)

        _tick(app, ctx, 2)

        by_style = {g.style: g for g in bridge.glass}
        assert by_style["sidebar"].frame == (0.0, 0.0, sl_views.SIDEBAR_W, 800.0)
        assert by_style["regular"].frame == (0.0, 800.0 - sl_views.PLAYER_H, 1280.0,
                                             sl_views.PLAYER_H)
        assert app.glass_active is True

    def test_glass_active_suppresses_drawn_backgrounds(self, app_ctx, monkeypatch):
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        monkeypatch.setattr(app_main, "native_controls", lambda: _FakeNativeBridge())

        _tick(app, ctx, 2)

        rects = _nodes(scene_buffer, RectNode)
        sidebar_bg = [n for n in rects if n.color_rgba == sl_views.SIDEBAR_BG
                      and n.width == sl_views.SIDEBAR_W and n.height == 800]
        bar_bg = [n for n in rects if n.color_rgba == sl_views.BAR_BG
                  and n.height == sl_views.PLAYER_H]
        assert sidebar_bg == []
        assert bar_bg == []

    def test_drawn_backgrounds_return_without_bridge(self, app_ctx, monkeypatch):
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        monkeypatch.setattr(app_main, "native_controls", lambda: None)

        _tick(app, ctx, 2)

        rects = _nodes(scene_buffer, RectNode)
        assert any(n.color_rgba == sl_views.SIDEBAR_BG and n.width == sl_views.SIDEBAR_W
                   for n in rects)
        assert any(n.color_rgba == sl_views.BAR_BG and n.height == sl_views.PLAYER_H
                   for n in rects)
        assert app.glass_active is False

    def test_content_flows_under_bar_only_with_glass(self, app_ctx, monkeypatch):
        app, ctx, scene_buffer = app_ctx
        app.authenticated = True
        app.view = "library"
        app.playlists = tuple(_playlist(f"Mix {i:02d}") for i in range(48))
        app.content_scroll = 400.0

        def card_bottoms() -> list[float]:
            frame = scene_buffer.latest_frame()
            assert frame is not None
            return [node.y + node.height for node in frame.nodes
                    if getattr(node, "color_rgba", None) == sl_views.CARD_BG
                    and node.x >= sl_views.SIDEBAR_W]

        monkeypatch.setattr(app_main, "native_controls", lambda: None)
        _tick(app, ctx, 2)
        no_glass_bottom = max(card_bottoms())

        bridge = _FakeNativeBridge()
        monkeypatch.setattr(app_main, "native_controls", lambda: bridge)
        app.invalidate()
        _tick(app, ctx, 2)
        glass_bottom = max(card_bottoms())

        assert glass_bottom > no_glass_bottom
        assert glass_bottom > 800.0 - sl_views.PLAYER_H

    def test_glass_destroyed_when_bridge_goes_away(self, app_ctx, monkeypatch):
        app, ctx, _ = app_ctx
        app.authenticated = True
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
        assert bridge.register_app_hooks(app) == 2

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
