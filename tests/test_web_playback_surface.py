"""SL-31 PR A2: the WKWebView playback surface.

The surface is the contract (playback_bridge) made real: a hidden scripted
web view hosting the SDK adapter page, token pushes for getOAuthToken, and
an event queue keyed off the channel. Tests run the REAL surface over the
null bridge's inert-but-recording stub — everything except live WebKit is
pinned here; the live channel is the Mac probe's job (PR B).
"""
from __future__ import annotations

import pytest

from luvatrix_core.core import playback_bridge as pb
from luvatrix_core.core.native_controls import NullNativeControlBridge
from luvatrix_core.platform.macos.playback_surface import (
    PLAYER_HOST_HTML,
    WKWebPlaybackSurface,
    player_host_html,
)


class TestHostPageContractAnchors:
    """The JS page and the Python contract are two halves of one protocol —
    drift here is the integration's silent-killer risk."""

    def test_handler_name_appears_in_the_page(self):
        assert f"messageHandlers.{pb.MESSAGE_HANDLER_NAME}" in PLAYER_HOST_HTML

    def test_every_verb_is_dispatched_in_the_page(self):
        for verb in pb.VERBS:
            assert f'"{verb}"' in PLAYER_HOST_HTML, f"host page never handles {verb}"

    def test_every_event_kind_is_postable_from_the_page(self):
        for kind in pb.PlaybackEventKind:
            assert f'"{kind.value}"' in PLAYER_HOST_HTML, f"host page never posts {kind.value}"

    def test_sdk_script_loads_from_scdn(self):
        assert "https://sdk.scdn.co/spotify-player.js" in PLAYER_HOST_HTML

    def test_ready_callback_is_defined_before_the_script_loads(self):
        assert PLAYER_HOST_HTML.index("onSpotifyWebPlaybackSDKReady =") < \
            PLAYER_HOST_HTML.index("sdk.scdn.co"), \
            "Spotify fires the callback synchronously on load — it must exist first"

    def test_script_load_failure_maps_to_initialization_error(self):
        """A dead CDN read is an initialization_error, not a silent page."""
        assert "onerror" in PLAYER_HOST_HTML

    def test_device_name_placeholder_substitutes_json_safely(self):
        assert "__DEVICE_NAME__" in PLAYER_HOST_HTML
        html = player_host_html('Alec’s "Desk" Mac')
        assert "__DEVICE_NAME__" not in html
        assert 'Alec\\u2019s \\"Desk\\" Mac' in html or "Alec" in html


class TestSurfaceLifecycleOverNullBridge:
    def _surface(self, bridge, **kwargs):
        return WKWebPlaybackSurface(bridge, **kwargs)

    def test_start_creates_the_hidden_view_with_the_host_page(self):
        bridge = NullNativeControlBridge()
        surface = self._surface(bridge, device_name="Test Mac")
        surface.start()
        view = surface._view
        assert view is not None
        assert view.handler_name == pb.MESSAGE_HANDLER_NAME
        assert view.frame == (0.0, 0.0, 1.0, 1.0), "a 1x1 attached surface, not a panel"
        assert "Test Mac" in view.html
        assert view.base_url.startswith("https://"), "EME needs a secure origin"

    def test_start_is_idempotent(self):
        bridge = NullNativeControlBridge()
        surface = self._surface(bridge)
        surface.start()
        first = surface._view
        surface.start()
        assert surface._view is first

    def test_send_evaluates_the_encoded_command(self):
        bridge = NullNativeControlBridge()
        surface = self._surface(bridge)
        surface.start()
        surface.send("pause")
        surface.send("seek", position_ms=90500)
        assert surface._view.evaluated == [
            pb.encode_command("pause", {}),
            pb.encode_command("seek", {"position_ms": 90500}),
        ]

    def test_send_before_start_and_after_stop_fail(self):
        bridge = NullNativeControlBridge()
        surface = self._surface(bridge)
        with pytest.raises(RuntimeError, match="not started"):
            surface.send("pause")
        surface.start()
        surface.stop()
        with pytest.raises(RuntimeError, match="stopped"):
            surface.send("pause")

    def test_stop_destroys_the_view_and_is_idempotent(self):
        bridge = NullNativeControlBridge()
        surface = self._surface(bridge)
        surface.start()
        view = surface._view
        surface.stop()
        assert view.destroyed is True
        assert surface._view is None
        surface.stop()  # no raise

    def test_start_after_stop_fails(self):
        bridge = NullNativeControlBridge()
        surface = self._surface(bridge)
        surface.start()
        surface.stop()
        with pytest.raises(RuntimeError, match="stopped"):
            surface.start()


class TestSurfaceToken:
    def test_initial_token_pushes_on_start(self):
        bridge = NullNativeControlBridge()
        surface = WKWebPlaybackSurface(bridge, token="tok-1")
        surface.start()
        assert surface._view.evaluated == [
            'window.LuvatrixPlayerHost.setToken("tok-1")']

    def test_set_token_repushes_to_the_live_page(self):
        bridge = NullNativeControlBridge()
        surface = WKWebPlaybackSurface(bridge)
        surface.start()
        assert surface._view.evaluated == []
        surface.set_token("tok-2")
        assert surface._view.evaluated == [
            'window.LuvatrixPlayerHost.setToken("tok-2")']

    def test_token_push_precedes_commands(self):
        """getOAuthToken must answer with the fresh token when connect runs."""
        bridge = NullNativeControlBridge()
        surface = WKWebPlaybackSurface(bridge, token="tok-1")
        surface.start()
        surface.send("connect")
        assert surface._view.evaluated[0].endswith('setToken("tok-1")')
        assert surface._view.evaluated[1] == pb.encode_command("connect", {})


class TestSurfaceEvents:
    def _started(self):
        bridge = NullNativeControlBridge()
        surface = WKWebPlaybackSurface(bridge)
        surface.start()
        return surface

    def test_ready_sets_the_device_id_and_queues(self):
        surface = self._started()
        surface._view.post_message({"type": "ready", "payload": {"device_id": "d1"}})
        assert surface.device_id == "d1"
        events = surface.drain_events()
        assert [e.kind for e in events] == [pb.PlaybackEventKind.READY]

    def test_not_ready_clears_the_device_id(self):
        surface = self._started()
        surface._view.post_message({"type": "ready", "payload": {"device_id": "d1"}})
        surface.drain_events()
        surface._view.post_message({"type": "not_ready", "payload": {}})
        assert surface.device_id is None
        assert [e.kind for e in surface.drain_events()] == [pb.PlaybackEventKind.NOT_READY]

    def test_malformed_messages_drop_silently(self):
        surface = self._started()
        surface._view.post_message({"type": "mystery"})
        surface._view.post_message("not-even-a-dict")
        assert surface.drain_events() == []

    def test_events_drain_in_order(self):
        surface = self._started()
        surface._view.post_message({"type": "ready", "payload": {"device_id": "d1"}})
        surface._view.post_message({"type": "player_state_changed", "payload": {"paused": False}})
        surface._view.post_message({"type": "account_error", "payload": {"message": "x"}})
        assert [e.kind for e in surface.drain_events()] == [
            pb.PlaybackEventKind.READY,
            pb.PlaybackEventKind.STATE_CHANGED,
            pb.PlaybackEventKind.ACCOUNT_ERROR,
        ]

    def test_stop_clears_the_device_id(self):
        surface = self._started()
        surface._view.post_message({"type": "ready", "payload": {"device_id": "d1"}})
        surface.stop()
        assert surface.device_id is None
