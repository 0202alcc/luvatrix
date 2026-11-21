"""SL-31 slice C: route the pill transport through the web device when local.

The TransportRouter speaks SpotifyClient's transport surface but sends
SDK-local verbs to the WebPlaybackDevice when the web device is the active
Connect device; content plays, shuffle/repeat, and transfers stay on the
Connect Web API (the SDK cannot do them). App wiring covers session
lifecycle gating and event-driven state adoption.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "examples" / "spotify_light"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import app_main  # noqa: E402
import sl_models  # noqa: E402
import sl_oauth  # noqa: E402
from sl_player import TransportRouter, WebPlaybackDevice  # noqa: E402
from luvatrix_core.core.playback_bridge import (  # noqa: E402
    InMemoryPlaybackBridge,
    PlaybackEventKind,
)


class _RecordingClient:
    """Stands in for SpotifyClient at the transport surface."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def _rec(self, name, **kw):
        self.calls.append((name, kw))

    def play(self, **kw):
        self._rec("play", **kw)

    def pause(self, **kw):
        self._rec("pause", **kw)

    def next_track(self, **kw):
        self._rec("next_track", **kw)

    def previous_track(self, **kw):
        self._rec("previous_track", **kw)

    def seek(self, position_ms, **kw):
        self._rec("seek", position_ms=position_ms, **kw)

    def set_volume(self, percent, **kw):
        self._rec("set_volume", percent=percent, **kw)

    def set_shuffle(self, enabled, **kw):
        self._rec("set_shuffle", enabled=enabled, **kw)

    def set_repeat(self, mode, **kw):
        self._rec("set_repeat", mode=mode, **kw)

    def transfer(self, device_id, **kw):
        self._rec("transfer", device_id=device_id, **kw)

    def up_next(self):
        self._rec("up_next")
        return None


@pytest.fixture
def routed():
    bridge = InMemoryPlaybackBridge()
    bridge.start()
    web = WebPlaybackDevice(bridge, device_name="Luvatrix Test")
    client = _RecordingClient()
    active = {"on": True}
    router = TransportRouter(client, web, lambda: active["on"])
    return router, web, bridge, client, active


class TestTransportRouterLocalVerbs:
    def test_pause_routes_to_sdk_when_active(self, routed):
        router, web, bridge, client, _ = routed
        router.pause()
        assert [v for v, _ in bridge.sent] == ["pause"]
        assert client.calls == []

    def test_pause_routes_to_connect_when_inactive(self, routed):
        router, web, bridge, client, active = routed
        active["on"] = False
        router.pause()
        assert bridge.sent == []
        assert client.calls == [("pause", {})]

    def test_next_previous_seek_volume_local(self, routed):
        router, web, bridge, client, _ = routed
        router.next_track()
        router.previous_track()
        router.seek(4_000)
        router.set_volume(55)
        assert [v for v, _ in bridge.sent] == [
            "nextTrack", "previousTrack", "seek", "setVolume",
        ]
        assert client.calls == []

    def test_bare_play_is_resume_locally(self, routed):
        router, web, bridge, client, _ = routed
        router.play()
        assert [v for v, _ in bridge.sent] == ["resume"]
        assert client.calls == []

    def test_bare_play_goes_to_connect_when_inactive(self, routed):
        router, web, bridge, client, active = routed
        active["on"] = False
        router.play()
        assert client.calls == [("play", {})]
        assert bridge.sent == []

    def test_content_play_stays_on_connect_even_when_active(self, routed):
        router, web, bridge, client, _ = routed
        router.play(context_uri="spotify:playlist:x")
        router.play(uris=["spotify:track:a"])
        assert [name for name, _ in client.calls] == ["play", "play"]
        assert client.calls[0][1]["context_uri"] == "spotify:playlist:x"
        assert bridge.sent == []

    def test_shuffle_repeat_transfer_stay_on_connect(self, routed):
        router, web, bridge, client, _ = routed
        router.set_shuffle(True)
        router.set_repeat("track")
        router.transfer("dev-9", play=False)
        assert [name for name, _ in client.calls] == ["set_shuffle", "set_repeat", "transfer"]
        assert bridge.sent == []

    def test_unlisted_methods_delegate(self, routed):
        router, *_rest, client, _active = routed
        router.up_next()
        assert client.calls == [("up_next", {})]


def _tokens(scope: str = "user-read-private streaming") -> sl_oauth.TokenSet:
    return sl_oauth.TokenSet(
        access_token="tok", refresh_token="rt",
        expires_at=time.time() + 3600, scope=scope,
    )


def _device(device_id: str) -> sl_models.Device:
    return sl_models.Device(id=device_id, name="Luvatrix Test", kind="web",
                            is_active=True, is_restricted=False, volume_percent=None)


def _player_state(device_id: str | None) -> sl_models.PlayerState:
    return sl_models.PlayerState(
        is_playing=True, progress_ms=1_000, track=None,
        device=_device(device_id) if device_id else None,
        shuffle=False, repeat="off",
    )


class _FakeSurface(InMemoryPlaybackBridge):
    """Surface-shaped fake: PlaybackBridge + lifecycle + token pushes."""

    def __init__(self):
        super().__init__()
        self.tokens: list[str] = []

    def set_token(self, token: str) -> None:
        self.tokens.append(token)


class _FakeNativeBridge:
    available = True

    def create_scripted_web_view(self, **kw):  # pragma: no cover - the fake surface bypasses this
        raise AssertionError("factory should be injected in tests")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("SPOTIFY_LIGHT_CONFIG_DIR", str(tmp_path))
    from luvatrix_core.core.runtime import AppRuntime
    from luvatrix_core.core.scene_graph import SceneGraphBuffer
    from luvatrix_core.core.hdi import HDIThread
    from luvatrix_core.core.sensors import SensorManagerThread
    from luvatrix_core.core.window_matrix import WindowMatrix

    class _NoopHDISource:
        def poll(self, window_active: bool, ts_ns: int):
            return []

    runtime = AppRuntime(
        matrix=WindowMatrix(800, 1280),
        hdi=HDIThread(source=_NoopHDISource()),
        sensor_manager=SensorManagerThread(providers={}),
        scene_buffer=SceneGraphBuffer(),
        host_os="macos",
    )
    ctx = runtime.build_context({"window.write", "hdi.keyboard", "hdi.mouse"})
    instance = app_main.create()
    instance.init(ctx)
    yield instance
    instance.teardown()


def _start_web(app, monkeypatch, scope="user-read-private streaming"):
    surfaces = []

    def factory(bridge, *, device_name, token):
        surface = _FakeSurface()
        surface.start()
        surface.set_token(token)
        surfaces.append((surface, device_name, token))
        return surface

    monkeypatch.setattr(app_main, "native_controls", lambda: _FakeNativeBridge())
    app._web_surface_factory = factory
    app.client_id = "cid"
    app._begin_session(_tokens(scope))
    return surfaces


class TestSessionLifecycle:
    def test_no_streaming_scope_no_device(self, app, monkeypatch):
        monkeypatch.setattr(app_main, "native_controls", lambda: _FakeNativeBridge())
        app._web_surface_factory = lambda *a, **k: pytest.fail("must not build")
        app.client_id = "cid"
        app._begin_session(_tokens("user-read-private user-read-email"))
        assert app._web_device is None

    def test_no_native_bridge_no_device(self, app, monkeypatch):
        monkeypatch.setattr(app_main, "native_controls", lambda: None)
        app._web_surface_factory = lambda *a, **k: pytest.fail("must not build")
        app.client_id = "cid"
        app._begin_session(_tokens())
        assert app._web_device is None

    def test_session_starts_surface_and_connects(self, app, monkeypatch):
        surfaces = _start_web(app, monkeypatch)
        assert len(surfaces) == 1
        surface, device_name, token = surfaces[0]
        assert token == "tok"
        assert device_name
        assert app._web_device is not None
        assert [v for v, _ in surface.sent] == ["connect"]

    def test_end_session_stops_surface(self, app, monkeypatch):
        surfaces = _start_web(app, monkeypatch)
        surface = surfaces[0][0]
        app._end_session()
        assert surface._stopped
        assert app._web_device is None
        assert app._web_surface is None

    def test_second_begin_replaces_surface(self, app, monkeypatch):
        first = _start_web(app, monkeypatch)[0][0]
        app._begin_session(_tokens())
        assert first._stopped
        assert app._web_surface is not None and app._web_surface is not first


class TestEventPump:
    def test_ready_submits_device_poll(self, app, monkeypatch):
        surfaces = _start_web(app, monkeypatch)
        surface = surfaces[0][0]
        app.worker.poll()  # drain bootstrap/poll-devices submissions
        surface.inject({"type": "ready", "payload": {"device_id": "dev-1"}})
        app._pump_web_playback()
        labels = [label for label, _ in app.worker.poll()]
        assert "poll-devices" in labels
        assert app._web_device.device_id == "dev-1"

    def test_state_adopted_when_web_is_active(self, app, monkeypatch):
        surfaces = _start_web(app, monkeypatch)
        surface = surfaces[0][0]
        surface.inject({"type": "ready", "payload": {"device_id": "dev-1"}})
        app.player = _player_state("dev-1")  # Connect says the web device is active
        surface.inject({"type": "player_state_changed", "payload": {
            "paused": False, "position_ms": 42_000, "duration_ms": 200_000,
            "shuffle": False, "repeat_mode": 0,
            "track": {"uri": "spotify:track:t1", "name": "T", "artists": "A",
                      "album": "AL", "art_url": "u"},
        }})
        app._pump_web_playback()
        assert app.player is not None
        assert app.player.progress_ms == 42_000
        assert app.player.track is not None and app.player.track.id == "t1"

    def test_state_ignored_when_other_device_active(self, app, monkeypatch):
        surfaces = _start_web(app, monkeypatch)
        surface = surfaces[0][0]
        surface.inject({"type": "ready", "payload": {"device_id": "dev-1"}})
        app.player = _player_state("other-device")
        surface.inject({"type": "player_state_changed", "payload": {
            "paused": True, "position_ms": 99_000, "duration_ms": 200_000,
            "shuffle": False, "repeat_mode": 0, "track": None,
        }})
        app._pump_web_playback()
        assert app.player.progress_ms == 1_000  # untouched

    def test_auth_error_toasts_once(self, app, monkeypatch):
        surfaces = _start_web(app, monkeypatch)
        surface = surfaces[0][0]
        app.status_message = ""
        surface.inject({"type": "authentication_error", "payload": {"message": "expired"}})
        app._pump_web_playback()
        first = app.status_message
        assert first
        surface.inject({"type": "authentication_error", "payload": {"message": "expired again"}})
        app._pump_web_playback()
        assert app.status_message == first

    def test_pump_without_device_is_noop(self, app):
        app._pump_web_playback()  # must not raise


class TestTransportTarget:
    def test_target_is_client_without_device(self, app):
        app._client = _RecordingClient()
        assert app._transport_target() is app._client

    def test_target_is_router_with_registered_device(self, app, monkeypatch):
        _start_web(app, monkeypatch)
        app._client = _RecordingClient()
        app._web_device.device_id = "dev-1"
        target = app._transport_target()
        assert isinstance(target, TransportRouter)

    def test_router_drives_sdk_when_web_device_active(self, app, monkeypatch):
        surfaces = _start_web(app, monkeypatch)
        surface = surfaces[0][0]
        app._client = _RecordingClient()
        app._web_device.device_id = "dev-1"
        app.player = _player_state("dev-1")
        app._transport_target().pause()
        assert [v for v, _ in surface.sent if v == "pause"] == ["pause"]
        assert app._client.calls == []

    def test_router_falls_back_when_other_device_active(self, app, monkeypatch):
        surfaces = _start_web(app, monkeypatch)
        surface = surfaces[0][0]
        app._client = _RecordingClient()
        app._web_device.device_id = "dev-1"
        app.player = _player_state("other")
        app._transport_target().pause()
        assert app._client.calls == [("pause", {})]
        assert [v for v, _ in surface.sent] == ["connect"]


class TestTokenRefreshPush:
    def test_refresh_callback_receives_new_token(self, tmp_path, monkeypatch):
        pushed: list[str] = []
        stale = sl_oauth.TokenSet(
            access_token="old", refresh_token="rt",
            expires_at=time.time() - 10, scope="streaming",
        )
        fresh = sl_oauth.TokenSet(
            access_token="new", refresh_token="rt2",
            expires_at=time.time() + 3600, scope="streaming",
        )
        monkeypatch.setattr(sl_oauth, "refresh_tokens", lambda cid, rt: fresh)
        monkeypatch.setattr(app_main.sl_store, "save_tokens", lambda *a, **k: None)
        mgr = app_main.TokenManager(tmp_path, "cid", stale, on_token=pushed.append)
        assert mgr.access_token() == "new"
        assert pushed == ["new"]

    def test_no_callback_no_crash(self, tmp_path, monkeypatch):
        fresh = sl_oauth.TokenSet(
            access_token="new", refresh_token="rt2",
            expires_at=time.time() + 3600, scope="streaming",
        )
        monkeypatch.setattr(sl_oauth, "refresh_tokens", lambda cid, rt: fresh)
        monkeypatch.setattr(app_main.sl_store, "save_tokens", lambda *a, **k: None)
        stale = sl_oauth.TokenSet(
            access_token="old", refresh_token="rt", expires_at=time.time() - 10,
        )
        mgr = app_main.TokenManager(tmp_path, "cid", stale)
        assert mgr.access_token() == "new"

    def test_surface_receives_refreshed_token(self, app, monkeypatch):
        surfaces = _start_web(app, monkeypatch)
        surface = surfaces[0][0]
        fresh = sl_oauth.TokenSet(
            access_token="refreshed", refresh_token="rt2",
            expires_at=time.time() + 3600, scope="streaming",
        )
        app._token_manager._tokens = sl_oauth.TokenSet(
            access_token="tok", refresh_token="rt",
            expires_at=time.time() - 10, scope="streaming",
        )
        monkeypatch.setattr(sl_oauth, "refresh_tokens", lambda cid, rt: fresh)
        monkeypatch.setattr(app_main.sl_store, "save_tokens", lambda *a, **k: None)
        app._token_manager.access_token()
        assert surface.tokens[-1] == "refreshed"
