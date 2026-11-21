"""SL-31 slice B: streaming scope + WebPlaybackDevice over the bridge contract.

The device adapter is transport-agnostic: it speaks verbs into any
PlaybackBridge (the WK surface on macOS, the in-memory bridge in tests)
and adapts SDK state JSON into sl_models.PlayerState.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "examples" / "spotify_light"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import sl_models  # noqa: E402
import sl_oauth  # noqa: E402
from sl_player import WebPlaybackDevice  # noqa: E402
from luvatrix_core.core.playback_bridge import InMemoryPlaybackBridge, PlaybackEventKind  # noqa: E402


def _tokens(scope: str) -> sl_oauth.TokenSet:
    return sl_oauth.TokenSet(
        access_token="tok", refresh_token=None,
        expires_at=time.time() + 3600, scope=scope,
    )


class TestStreamingScope:
    def test_scopes_include_streaming(self):
        assert "streaming" in sl_oauth.SCOPES.split() if isinstance(sl_oauth.SCOPES, str) else "streaming" in sl_oauth.SCOPES

    def test_authorize_url_requests_streaming(self):
        url = sl_oauth.authorize_url(
            client_id="cid",
            redirect_uri="http://127.0.0.1:8888/callback",
            challenge="chal",
            state="st",
        )
        assert "streaming" in url

    def test_has_streaming_scope_detects_granted(self):
        assert sl_oauth.has_streaming_scope(_tokens("user-read-private streaming"))
        assert not sl_oauth.has_streaming_scope(_tokens("user-read-private user-read-email"))
        assert not sl_oauth.has_streaming_scope(_tokens(""))


def _state_payload(**overrides):
    payload = {
        "paused": False,
        "position_ms": 61_000,
        "duration_ms": 200_000,
        "shuffle": True,
        "repeat_mode": 2,
        "track": {
            "uri": "spotify:track:abc123",
            "name": "Song",
            "artists": "A One, B Two",
            "album": "The Album",
            "art_url": "https://img/640.jpg",
        },
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def device():
    bridge = InMemoryPlaybackBridge()
    bridge.start()
    return WebPlaybackDevice(bridge, device_name="Luvatrix Test"), bridge


class TestVerbs:
    def test_connect_disconnect_activate(self, device):
        dev, bridge = device
        dev.connect()
        dev.activate_element()
        dev.disconnect()
        assert [v for v, _ in bridge.sent] == ["connect", "activateElement", "disconnect"]

    def test_transport_verbs(self, device):
        dev, bridge = device
        dev.pause()
        dev.resume()
        dev.toggle_play()
        dev.next_track()
        dev.previous_track()
        assert [v for v, _ in bridge.sent] == [
            "pause", "resume", "togglePlay", "nextTrack", "previousTrack",
        ]

    def test_seek_sends_position_ms(self, device):
        dev, bridge = device
        dev.seek(1_500)
        assert bridge.sent == [("seek", {"position_ms": 1_500})]

    def test_set_volume_converts_percent_to_fraction(self, device):
        dev, bridge = device
        dev.set_volume(40)
        assert bridge.sent == [("setVolume", {"volume": pytest.approx(0.4)})]

    def test_set_volume_clamps(self, device):
        dev, bridge = device
        dev.set_volume(-5)
        dev.set_volume(250)
        assert [a["volume"] for _, a in bridge.sent] == [0.0, 1.0]


class TestIdentity:
    def test_no_device_before_ready(self, device):
        dev, _ = device
        assert dev.device_id is None
        assert dev.device is None

    def test_ready_sets_identity(self, device):
        dev, bridge = device
        bridge.inject({"type": "ready", "payload": {"device_id": "dev-1"}})
        dev.drain_events()
        assert dev.device_id == "dev-1"
        assert dev.device == sl_models.Device(
            id="dev-1", name="Luvatrix Test", kind="web",
            is_active=True, is_restricted=False, volume_percent=None,
        )

    def test_not_ready_clears_identity(self, device):
        dev, bridge = device
        bridge.inject({"type": "ready", "payload": {"device_id": "dev-1"}})
        dev.drain_events()
        bridge.inject({"type": "not_ready", "payload": {}})
        dev.drain_events()
        assert dev.device_id is None
        assert dev.device is None

    def test_drain_returns_events(self, device):
        dev, bridge = device
        bridge.inject({"type": "ready", "payload": {"device_id": "dev-1"}})
        events = dev.drain_events()
        assert [e.kind for e in events] == [PlaybackEventKind.READY]


class TestStateAdaptation:
    def _prime(self, dev, bridge):
        bridge.inject({"type": "ready", "payload": {"device_id": "dev-1"}})
        dev.drain_events()

    def test_state_changed_maps_to_player_state(self, device):
        dev, bridge = device
        self._prime(dev, bridge)
        bridge.inject({"type": "player_state_changed", "payload": _state_payload()})
        dev.drain_events()
        state = dev.last_state
        assert state is not None
        assert state.is_playing is True
        assert state.progress_ms == 61_000
        assert state.shuffle is True
        assert state.repeat == "track"
        assert state.device is not None and state.device.id == "dev-1"

    def test_track_mapping(self, device):
        dev, bridge = device
        self._prime(dev, bridge)
        bridge.inject({"type": "player_state_changed", "payload": _state_payload()})
        dev.drain_events()
        track = dev.last_state.track
        assert track is not None
        assert track.id == "abc123"
        assert track.uri == "spotify:track:abc123"
        assert track.name == "Song"
        assert track.duration_ms == 200_000
        assert [a.name for a in track.artists] == ["A One", "B Two"]
        assert track.album is not None and track.album.name == "The Album"
        assert track.album.images and track.album.images[0].url == "https://img/640.jpg"

    def test_paused_maps_to_not_playing(self, device):
        dev, bridge = device
        self._prime(dev, bridge)
        bridge.inject({"type": "player_state_changed", "payload": _state_payload(paused=True)})
        dev.drain_events()
        assert dev.last_state.is_playing is False

    @pytest.mark.parametrize("mode,expected", [(0, "off"), (1, "context"), (2, "track")])
    def test_repeat_mode_mapping(self, device, mode, expected):
        dev, bridge = device
        self._prime(dev, bridge)
        bridge.inject({"type": "player_state_changed", "payload": _state_payload(repeat_mode=mode)})
        dev.drain_events()
        assert dev.last_state.repeat == expected

    def test_state_snapshot_also_updates_last_state(self, device):
        dev, bridge = device
        self._prime(dev, bridge)
        bridge.inject({"type": "state_snapshot", "payload": _state_payload(position_ms=5)})
        dev.drain_events()
        assert dev.last_state.progress_ms == 5

    def test_empty_state_clears_track(self, device):
        dev, bridge = device
        self._prime(dev, bridge)
        bridge.inject({"type": "player_state_changed", "payload": {"empty": True}})
        dev.drain_events()
        state = dev.last_state
        assert state is not None
        assert state.track is None
        assert state.is_playing is False
        assert state.progress_ms == 0

    def test_null_track_tolerated(self, device):
        dev, bridge = device
        self._prime(dev, bridge)
        bridge.inject({"type": "player_state_changed", "payload": _state_payload(track=None)})
        dev.drain_events()
        assert dev.last_state.track is None
        assert dev.last_state.is_playing is True

    def test_state_before_ready_has_no_device(self, device):
        dev, bridge = device
        bridge.inject({"type": "player_state_changed", "payload": _state_payload()})
        dev.drain_events()
        assert dev.last_state is not None
        assert dev.last_state.device is None

    def test_last_state_none_before_any_state(self, device):
        dev, _ = device
        assert dev.last_state is None

    def test_last_state_has_fresh_timestamp(self, device):
        dev, bridge = device
        self._prime(dev, bridge)
        before = int(time.time() * 1000)
        bridge.inject({"type": "player_state_changed", "payload": _state_payload()})
        dev.drain_events()
        assert dev.last_state.timestamp_ms is not None
        assert dev.last_state.timestamp_ms >= before


class TestErrors:
    def test_error_events_flow_through_drain(self, device):
        dev, bridge = device
        bridge.inject({"type": "authentication_error", "payload": {"message": "bad token"}})
        events = dev.drain_events()
        assert [e.kind for e in events] == [PlaybackEventKind.AUTH_ERROR]
        assert events[0].payload["message"] == "bad token"

    def test_malformed_events_dropped(self, device):
        dev, bridge = device
        bridge.inject({"type": "nonsense"})
        bridge.inject("not even a dict")
        assert dev.drain_events() == []
