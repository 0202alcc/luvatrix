"""SL-31 PR A1: the playback bridge contract.

One JSON channel between an EME-capable web surface (the Web Playback SDK
host page) and the app: events flow JS -> native as ``{type, payload}``
dicts, commands flow native -> JS as ``{verb, args}`` invocations of the
host adapter. The contract lives in luvatrix_core.core.playback_bridge so
every engine adapter (WKWebView message handler, localhost socket, CEF
router) and every app consumer speaks the same vocabulary.
"""
from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from luvatrix_core.core import playback_bridge as pb


class TestEventParsing:
    def test_ready_carries_the_device_id(self):
        event = pb.parse_event({"type": "ready", "payload": {"device_id": "abc123"}})
        assert event is not None
        assert event.kind is pb.PlaybackEventKind.READY
        assert event.payload["device_id"] == "abc123"

    def test_every_sdk_error_kind_parses(self):
        for kind in ("initialization_error", "authentication_error",
                     "account_error", "playback_error"):
            event = pb.parse_event({"type": kind, "payload": {"message": "boom"}})
            assert event is not None and event.kind.value == kind
            assert event.payload["message"] == "boom"

    def test_state_changed_and_snapshot_are_distinct(self):
        changed = pb.parse_event({"type": "player_state_changed", "payload": {"paused": True}})
        snapshot = pb.parse_event({"type": "state_snapshot", "payload": {"paused": False}})
        assert changed is not None and changed.kind is pb.PlaybackEventKind.STATE_CHANGED
        assert snapshot is not None and snapshot.kind is pb.PlaybackEventKind.STATE_SNAPSHOT

    def test_not_ready_parses(self):
        event = pb.parse_event({"type": "not_ready", "payload": {"device_id": "abc"}})
        assert event is not None and event.kind is pb.PlaybackEventKind.NOT_READY

    def test_missing_payload_defaults_to_empty(self):
        event = pb.parse_event({"type": "not_ready"})
        assert event is not None and event.payload == {}

    def test_unknown_types_drop_without_crashing(self):
        """Forward compatibility: a newer host page must not crash an older app."""
        assert pb.parse_event({"type": "video_element_hijacked", "payload": {}}) is None

    @pytest.mark.parametrize("message", [
        None, 42, "ready", [], {},
        {"payload": {}},               # no type
        {"type": 7, "payload": {}},    # non-string type
        {"type": "ready", "payload": "nope"},  # payload must be a dict
    ])
    def test_malformed_messages_drop(self, message):
        assert pb.parse_event(message) is None


class TestCommandEncoding:
    def test_invoke_targets_the_host_adapter(self):
        js = pb.encode_command("pause", {})
        assert js == 'window.LuvatrixPlayerHost.invoke("pause", {})'

    def test_args_ride_as_json(self):
        js = pb.encode_command("seek", {"position_ms": 90500})
        assert js == 'window.LuvatrixPlayerHost.invoke("seek", {"position_ms": 90500})'

    def test_volume_is_a_unit_interval(self):
        js = pb.encode_command("setVolume", {"volume": 0.5})
        assert '"volume": 0.5' in js

    def test_the_full_sdk_verb_set_is_valid(self):
        for verb in ("connect", "disconnect", "activateElement", "pause",
                     "resume", "togglePlay", "nextTrack", "previousTrack",
                     "seek", "setVolume", "getCurrentState"):
            pb.encode_command(verb, {})

    def test_unknown_verbs_are_rejected(self):
        with pytest.raises(ValueError, match="unknown playback verb"):
            pb.encode_command("playArbitraryUris", {"uris": []})

    def test_encoded_output_is_parseable_javascript_arguments(self):
        """The invoke arguments must stay JSON: no python repr leaks."""
        js = pb.encode_command("seek", {"position_ms": 1000, "note": 'a"b'})
        _, args = js[len('window.LuvatrixPlayerHost.invoke('):-1].split(", ", 1)
        assert json.loads(args) == {"position_ms": 1000, "note": 'a"b'}


class TestInMemoryBridge:
    def test_records_commands_in_order(self):
        bridge = pb.InMemoryPlaybackBridge()
        bridge.start()
        bridge.send("connect")
        bridge.send("seek", position_ms=1000)
        bridge.send("pause")
        assert bridge.sent == [("connect", {}), ("seek", {"position_ms": 1000}), ("pause", {})]

    def test_send_rejects_unknown_verbs(self):
        bridge = pb.InMemoryPlaybackBridge()
        bridge.start()
        with pytest.raises(ValueError):
            bridge.send("rm_rf")

    def test_injected_events_drain_in_order_then_empty(self):
        bridge = pb.InMemoryPlaybackBridge()
        bridge.inject({"type": "ready", "payload": {"device_id": "d1"}})
        bridge.inject({"type": "player_state_changed", "payload": {"paused": False}})
        bridge.inject({"type": "not_a_real_event"})
        drained = bridge.drain_events()
        assert [e.kind for e in drained] == [
            pb.PlaybackEventKind.READY, pb.PlaybackEventKind.STATE_CHANGED]
        assert bridge.drain_events() == [], "drain consumes"

    def test_stop_marks_unavailable_and_send_fails(self):
        bridge = pb.InMemoryPlaybackBridge()
        bridge.start()
        assert bridge.available
        bridge.stop()
        assert not bridge.available
        with pytest.raises(RuntimeError, match="stopped"):
            bridge.send("pause")

    def test_send_before_start_fails(self):
        bridge = pb.InMemoryPlaybackBridge()
        with pytest.raises(RuntimeError, match="not started"):
            bridge.send("pause")


class TestContractAnchors:
    def test_handler_name_is_stable(self):
        """The WKScriptMessageHandler name is half the wire protocol — the JS
        host page and the Swift-side handler must never drift apart."""
        assert pb.MESSAGE_HANDLER_NAME == "luvatrixPlayer"

    def test_verb_vocabulary_matches_the_sdk_player_api(self):
        assert pb.VERBS == frozenset({
            "connect", "disconnect", "activateElement", "pause", "resume",
            "togglePlay", "nextTrack", "previousTrack", "seek", "setVolume",
            "getCurrentState",
        })


class _NsDictLike(Mapping):
    """PyObjC __NSDictionaryM stand-in: a Mapping that is NOT a dict."""

    def __init__(self, data):
        self._data = dict(data)

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)


class TestParseEventPyObjCShapes:
    """parse_event gated on isinstance(dict) — real WebKit bodies are
    __NSDictionaryM, so every real playback event would have dropped next
    (the ready-gate signals were just the first to die)."""

    def test_accepts_non_dict_mapping(self):
        event = pb.parse_event(_NsDictLike({"type": "ready", "payload": {"device_id": "d1"}}))
        assert event is not None
        assert event.kind is pb.PlaybackEventKind.READY
        assert event.payload["device_id"] == "d1"

    def test_mapping_payload_becomes_a_real_dict(self):
        event = pb.parse_event(_NsDictLike({
            "type": "player_state_changed",
            "payload": _NsDictLike({"paused": 1}),
        }))
        assert event is not None
        assert type(event.payload) is dict
        assert event.payload["paused"] == 1

    def test_non_mapping_still_drops(self):
        assert pb.parse_event("not-even-a-dict") is None
        assert pb.parse_event(42) is None
