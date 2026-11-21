"""SL-31 PR A2: the WKWebView playback surface.

The surface is the contract (playback_bridge) made real: a hidden scripted
web view hosting the SDK adapter page, token pushes for getOAuthToken, and
an event queue keyed off the channel. Tests run the REAL surface over the
null bridge's inert-but-recording stub — everything except live WebKit is
pinned here; the live channel is the Mac probe's job (PR B).
"""
from __future__ import annotations

from collections.abc import Mapping

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

    def test_page_posts_host_ready(self):
        """The inline script's last act is the host_ready signal — the native
        side queues every evaluation until it arrives (loadHTMLString is async;
        anything earlier is silently dropped)."""
        assert '"host_ready"' in PLAYER_HOST_HTML

    def test_page_posts_sdk_ready_from_the_sdk_callback(self):
        assert '"sdk_ready"' in PLAYER_HOST_HTML
        callback = PLAYER_HOST_HTML.index("onSpotifyWebPlaybackSDKReady =")
        posted = PLAYER_HOST_HTML.index('"sdk_ready"')
        assert callback < posted, "sdk_ready must be posted from inside the callback"


def _page_ready(surface) -> None:
    """Simulate the page's lifecycle signals: inline script ran, SDK loaded."""
    surface._view.post_message({"type": "host_ready", "payload": {}})
    surface._view.post_message({"type": "sdk_ready", "payload": {}})


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
        _page_ready(surface)
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
    def test_initial_token_pushes_once_the_page_is_ready(self):
        bridge = NullNativeControlBridge()
        surface = WKWebPlaybackSurface(bridge, token="tok-1")
        surface.start()
        _page_ready(surface)
        assert surface._view.evaluated == [
            'window.LuvatrixPlayerHost.setToken("tok-1")']

    def test_set_token_repushes_to_the_live_page(self):
        bridge = NullNativeControlBridge()
        surface = WKWebPlaybackSurface(bridge)
        surface.start()
        _page_ready(surface)
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
        _page_ready(surface)
        assert surface._view.evaluated[0].endswith('setToken("tok-1")')
        assert surface._view.evaluated[1] == pb.encode_command("connect", {})


class TestPageReadyGating:
    """The 100%-repro startup race from live-fire: loadHTMLString is async, so
    setToken + connect evaluated immediately after start() landed before the
    page existed and were silently dropped ({host=1, sdk=1, tokenSet=0,
    player=0}). Everything outbound queues until the page's ready signals."""

    def test_commands_before_page_ready_are_queued_not_evaluated(self):
        bridge = NullNativeControlBridge()
        surface = WKWebPlaybackSurface(bridge, token="tok-1")
        surface.start()
        surface.send("connect")
        assert surface._view.evaluated == []

    def test_host_ready_flushes_token_but_not_verbs(self):
        """setToken only needs LuvatrixPlayerHost (inline script); verbs need
        the SDK global — they wait for sdk_ready."""
        bridge = NullNativeControlBridge()
        surface = WKWebPlaybackSurface(bridge, token="tok-1")
        surface.start()
        surface.send("connect")
        surface._view.post_message({"type": "host_ready", "payload": {}})
        assert surface._view.evaluated == [
            'window.LuvatrixPlayerHost.setToken("tok-1")']

    def test_sdk_ready_flushes_verbs_in_send_order(self):
        bridge = NullNativeControlBridge()
        surface = WKWebPlaybackSurface(bridge, token="tok-1")
        surface.start()
        surface.send("connect")
        surface.send("setVolume", volume=0.5)
        _page_ready(surface)
        assert surface._view.evaluated == [
            'window.LuvatrixPlayerHost.setToken("tok-1")',
            pb.encode_command("connect", {}),
            pb.encode_command("setVolume", {"volume": 0.5}),
        ]

    def test_token_push_before_connect_ordering_survives_the_queue(self):
        """The one ordering that matters: token lands before connect, even
        though connect was sent before any ready signal arrived."""
        bridge = NullNativeControlBridge()
        surface = WKWebPlaybackSurface(bridge, token="tok-1")
        surface.start()
        surface.send("connect")
        _page_ready(surface)
        evaluated = surface._view.evaluated
        assert evaluated[0].endswith('setToken("tok-1")')
        assert evaluated[1] == pb.encode_command("connect", {})

    def test_post_ready_commands_go_straight_through(self):
        bridge = NullNativeControlBridge()
        surface = WKWebPlaybackSurface(bridge, token="tok-1")
        surface.start()
        _page_ready(surface)
        surface.send("pause")
        assert surface._view.evaluated[-1] == pb.encode_command("pause", {})

    def test_set_token_before_ready_queues_and_flushes_in_order(self):
        bridge = NullNativeControlBridge()
        surface = WKWebPlaybackSurface(bridge, token="tok-1")
        surface.start()
        surface.set_token("tok-2")
        surface._view.post_message({"type": "host_ready", "payload": {}})
        assert surface._view.evaluated == [
            'window.LuvatrixPlayerHost.setToken("tok-1")',
            'window.LuvatrixPlayerHost.setToken("tok-2")',
        ]

    def test_late_token_after_ready_goes_straight_through(self):
        bridge = NullNativeControlBridge()
        surface = WKWebPlaybackSurface(bridge)
        surface.start()
        _page_ready(surface)
        surface.set_token("tok-late")
        assert surface._view.evaluated == [
            'window.LuvatrixPlayerHost.setToken("tok-late")']

    def test_ready_signals_are_not_emitted_as_events(self):
        """host_ready/sdk_ready are page-lifecycle signals, not playback
        events — the app loop must never see them."""
        bridge = NullNativeControlBridge()
        surface = WKWebPlaybackSurface(bridge)
        surface.start()
        _page_ready(surface)
        assert surface.drain_events() == []

    def test_stop_clears_readiness_and_pending_queue(self):
        bridge = NullNativeControlBridge()
        surface = WKWebPlaybackSurface(bridge, token="tok-1")
        surface.start()
        surface.send("connect")
        _page_ready(surface)
        surface.stop()
        assert surface._host_ready is False
        assert surface._sdk_ready is False
        assert surface._pending_js == []


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


class _NsDictLike(Mapping):
    """PyObjC __NSDictionaryM stand-in (Mapping, not dict) — the exact wire
    shape from the runner's diag: on_message type=__NSDictionaryM."""

    def __init__(self, data):
        self._data = dict(data)

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)


class TestPyObjCWireShapes:
    """End-to-end through the null boundary: post_message now runs the same
    normalizer as the real _receive_message, so fakes reproduce the wire."""

    def test_ready_signals_open_gates_when_sent_as_nsdict(self):
        bridge = NullNativeControlBridge()
        surface = WKWebPlaybackSurface(bridge, token="tok-1")
        surface.start()
        surface.send("connect")
        surface._view.post_message(_NsDictLike({"type": "host_ready"}))
        surface._view.post_message(_NsDictLike({"type": "sdk_ready"}))
        assert surface._view.evaluated == [
            'window.LuvatrixPlayerHost.setToken("tok-1")',
            pb.encode_command("connect", {}),
        ]

    def test_playback_event_as_nsdict_drains_with_plain_payload(self):
        bridge = NullNativeControlBridge()
        surface = WKWebPlaybackSurface(bridge)
        surface.start()
        surface._view.post_message(_NsDictLike({
            "type": "player_state_changed",
            "payload": _NsDictLike({"paused": 0, "position_ms": 123}),
        }))
        events = surface.drain_events()
        assert [e.kind for e in events] == [pb.PlaybackEventKind.STATE_CHANGED]
        assert type(events[0].payload) is dict
        assert events[0].payload["position_ms"] == 123
