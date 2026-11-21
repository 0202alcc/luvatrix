"""Playback bridge contract: one JSON channel to an in-app web player.

The Web Playback SDK route (web-playback spike, option a) hosts Spotify's
JS player in a hidden web surface. Everything the app and the surface say to
each other rides ONE engine-agnostic contract:

- events flow surface -> app as ``{"type": ..., "payload": {...}}`` dicts
  (a WKScriptMessageHandler message, a localhost socket frame, a CEF
  router payload — same shape everywhere);
- commands flow app -> surface as ``LuvatrixPlayerHost.invoke(verb, args)``
  JS evaluations, where ``verb`` is the Spotify.Player method name.

This module owns the vocabulary so adapters and consumers cannot drift:
the message-handler name, the event kinds, the verb set, the encoder, the
parser (unknown event types drop — a newer host page must never crash an
older app), and ``InMemoryPlaybackBridge``, the test double apps wire in
when no real surface exists (headless, CI, unsupported hosts).
"""
from __future__ import annotations

import json
import queue
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

# Half the wire protocol: the JS host page posts to
# ``window.webkit.messageHandlers.<this>.postMessage(...)`` and the native
# side registers its WKScriptMessageHandler under the same name.
MESSAGE_HANDLER_NAME = "luvatrixPlayer"


class PlaybackEventKind(str, Enum):
    READY = "ready"                          # device registered; payload.device_id
    NOT_READY = "not_ready"                  # device went offline
    STATE_CHANGED = "player_state_changed"   # SDK push; payload is the raw state
    STATE_SNAPSHOT = "state_snapshot"        # answer to getCurrentState
    INIT_ERROR = "initialization_error"      # EME/environment failure
    AUTH_ERROR = "authentication_error"      # token invalid/expired/wrong scopes
    ACCOUNT_ERROR = "account_error"          # e.g. not Premium
    PLAYBACK_ERROR = "playback_error"        # mid-stream failure


@dataclass(frozen=True)
class PlaybackEvent:
    kind: PlaybackEventKind
    payload: dict[str, Any] = field(default_factory=dict)


def parse_event(message: object) -> PlaybackEvent | None:
    """Parse one raw channel message; anything unrecognized returns None.

    Drops (never raises): non-dicts, missing/non-string ``type``, non-dict
    ``payload``, and types this app version doesn't know.
    """
    if not isinstance(message, Mapping):
        return None
    kind_raw = message.get("type")
    if not isinstance(kind_raw, str):
        return None
    try:
        kind = PlaybackEventKind(kind_raw)
    except ValueError:
        return None
    payload = message.get("payload", {})
    if payload is None:
        payload = {}
    if not isinstance(payload, Mapping):
        return None
    return PlaybackEvent(kind=kind, payload=dict(payload))


class PlaybackVerb(str, Enum):
    """The Spotify.Player methods the app may invoke (the SDK cannot start
    arbitrary contexts or set shuffle/repeat — those stay on the Web API)."""

    CONNECT = "connect"
    DISCONNECT = "disconnect"
    ACTIVATE = "activateElement"
    PAUSE = "pause"
    RESUME = "resume"
    TOGGLE = "togglePlay"
    NEXT = "nextTrack"
    PREV = "previousTrack"
    SEEK = "seek"
    SET_VOLUME = "setVolume"
    GET_STATE = "getCurrentState"


VERBS = frozenset(verb.value for verb in PlaybackVerb)


def encode_command(verb: str, args: dict[str, Any]) -> str:
    """One JS expression invoking the host adapter. Args serialize as JSON —
    never Python repr — so quoting survives the round trip."""
    if verb not in VERBS:
        raise ValueError(f"unknown playback verb: {verb!r}")
    return f"window.LuvatrixPlayerHost.invoke({json.dumps(verb)}, {json.dumps(args)})"


@runtime_checkable
class PlaybackBridge(Protocol):
    """A running playback surface the app can drive and drain."""

    @property
    def available(self) -> bool:
        """False once stopped or when the host surface died."""
        ...

    def start(self) -> None:
        """Attach the surface and load the host page. Main thread on macOS."""
        ...

    def send(self, verb: str, **args: Any) -> None:
        """Queue one command to the host page. Thread-safe."""
        ...

    def drain_events(self) -> list[PlaybackEvent]:
        """Pop every event queued since the last drain (app-loop side)."""
        ...

    def stop(self) -> None:
        """Detach and release the surface. Idempotent."""
        ...


class InMemoryPlaybackBridge:
    """Scriptable PlaybackBridge double: records commands, queues injected
    events, enforces the lifecycle. This is also what apps hold on hosts
    where no real surface can exist — send() then simply goes nowhere, which
    is correct: without a surface there is no local playback device."""

    def __init__(self) -> None:
        self._events: queue.Queue[PlaybackEvent] = queue.Queue()
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self._started = False
        self._stopped = False

    @property
    def available(self) -> bool:
        return not self._stopped

    def start(self) -> None:
        if self._stopped:
            raise RuntimeError("playback bridge is stopped")
        self._started = True

    def send(self, verb: str, **args: Any) -> None:
        if self._stopped:
            raise RuntimeError("playback bridge is stopped")
        if not self._started:
            raise RuntimeError("playback bridge not started")
        if verb not in VERBS:
            raise ValueError(f"unknown playback verb: {verb!r}")
        self.sent.append((verb, dict(args)))

    def inject(self, message: object) -> None:
        """Queue one raw event as the surface would post it; malformed drops."""
        event = parse_event(message)
        if event is not None:
            self._events.put(event)

    def drain_events(self) -> list[PlaybackEvent]:
        out: list[PlaybackEvent] = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                return out

    def stop(self) -> None:
        self._stopped = True
