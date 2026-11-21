"""Web Playback SDK device: in-app playback over the luvatrix bridge contract.

Wraps any ``PlaybackBridge`` (the WKWebView surface on macOS, an in-memory
bridge in tests) and presents a device-shaped object to the app: transport
calls encode contract verbs, and SDK state events adapt into
``sl_models.PlayerState`` so the pill renders local playback exactly like a
Connect-polled device.

Volume speaks percent (0–100) at this boundary, matching the rest of the
app; the contract verb carries the SDK's 0.0–1.0 fraction.
"""
from __future__ import annotations

import time

from luvatrix_core.core.playback_bridge import (
    PlaybackBridge,
    PlaybackEvent,
    PlaybackEventKind,
)

import sl_models

DEFAULT_DEVICE_NAME = "Luvatrix Player"
_KIND = "web"
_REPEAT_MODES = {0: "off", 1: "context", 2: "track"}


def _track_from_sdk(payload: dict, *, duration_ms: int = 0) -> sl_models.Track | None:
    uri = payload.get("uri")
    if not isinstance(uri, str) or not uri.startswith("spotify:track:"):
        return None
    name = payload.get("name")
    if not isinstance(name, str) or not name:
        return None
    artists = payload.get("artists")
    names = [n.strip() for n in artists.split(",")] if isinstance(artists, str) else []
    album_name = payload.get("album")
    art_url = payload.get("art_url")
    album = None
    if isinstance(album_name, str) and album_name:
        images = (sl_models.Image(url=art_url),) if isinstance(art_url, str) and art_url else ()
        album = sl_models.Album(id="", name=album_name, uri="", images=images)
    return sl_models.Track(
        id=uri.rsplit(":", 1)[-1],
        name=name,
        uri=uri,
        duration_ms=duration_ms,
        artists=tuple(sl_models.Artist(id="", name=n, uri="") for n in names if n),
        album=album,
    )


def player_state_from_sdk(payload: object, device: sl_models.Device | None) -> sl_models.PlayerState:
    """Adapt one slim SDK state payload (state_changed or state_snapshot)."""
    if not isinstance(payload, dict) or payload.get("empty"):
        return sl_models.PlayerState(
            is_playing=False, progress_ms=0, track=None, device=device,
            shuffle=False, repeat="off",
            timestamp_ms=int(time.time() * 1000),
        )
    position = payload.get("position_ms")
    duration = payload.get("duration_ms")
    track_payload = payload.get("track")
    repeat_mode = payload.get("repeat_mode")
    return sl_models.PlayerState(
        is_playing=not bool(payload.get("paused", True)),
        progress_ms=position if isinstance(position, int) and position >= 0 else 0,
        track=_track_from_sdk(
            track_payload,
            duration_ms=duration if isinstance(duration, int) and duration >= 0 else 0,
        ) if isinstance(track_payload, dict) else None,
        device=device,
        shuffle=bool(payload.get("shuffle", False)),
        repeat=_REPEAT_MODES.get(repeat_mode, "off"),
        timestamp_ms=int(time.time() * 1000),
    )


class WebPlaybackDevice:
    """A Connect-visible device whose transport is the in-page SDK player."""

    def __init__(self, bridge: PlaybackBridge, *, device_name: str = DEFAULT_DEVICE_NAME) -> None:
        self._bridge = bridge
        self._device_name = device_name
        self.device_id: str | None = None
        self.last_state: sl_models.PlayerState | None = None

    @property
    def device(self) -> sl_models.Device | None:
        if self.device_id is None:
            return None
        return sl_models.Device(
            id=self.device_id, name=self._device_name, kind=_KIND,
            is_active=True, is_restricted=False, volume_percent=None,
        )

    def connect(self) -> None:
        self._bridge.send("connect")

    def disconnect(self) -> None:
        self._bridge.send("disconnect")

    def activate_element(self) -> None:
        self._bridge.send("activateElement")

    def pause(self) -> None:
        self._bridge.send("pause")

    def resume(self) -> None:
        self._bridge.send("resume")

    def toggle_play(self) -> None:
        self._bridge.send("togglePlay")

    def next_track(self) -> None:
        self._bridge.send("nextTrack")

    def previous_track(self) -> None:
        self._bridge.send("previousTrack")

    def seek(self, position_ms: int) -> None:
        self._bridge.send("seek", position_ms=int(position_ms))

    def set_volume(self, percent: int) -> None:
        clamped = max(0, min(100, int(percent)))
        self._bridge.send("setVolume", volume=clamped / 100.0)

    def drain_events(self) -> list[PlaybackEvent]:
        """Pump the bridge; updates identity and last_state. Returns events."""
        events = self._bridge.drain_events()
        for event in events:
            if event.kind is PlaybackEventKind.READY:
                device_id = event.payload.get("device_id")
                self.device_id = str(device_id) if device_id else None
            elif event.kind is PlaybackEventKind.NOT_READY:
                self.device_id = None
            elif event.kind in (PlaybackEventKind.STATE_CHANGED, PlaybackEventKind.STATE_SNAPSHOT):
                self.last_state = player_state_from_sdk(event.payload, self.device)
        return events
