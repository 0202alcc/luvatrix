"""Spotify Web API client. Stub module — see tests."""
from __future__ import annotations

from enum import Enum

API_BASE = "https://api.spotify.com/v1"


class ErrorKind(Enum):
    UNAUTHORIZED = "unauthorized"
    PREMIUM_REQUIRED = "premium_required"
    DEVICE_NOT_FOUND = "device_not_found"
    API = "api"
    NETWORK = "network"


class ApiError(Exception):
    def __init__(self, kind: ErrorKind, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status


def search_url(query: str, types, *, limit: int = 10, offset: int = 0) -> str:
    raise NotImplementedError


class SpotifyClient:
    def __init__(self, *, token_provider, http=None) -> None:
        raise NotImplementedError

    def me(self): raise NotImplementedError
    def my_playlists(self, *, limit: int = 50): raise NotImplementedError
    def playlist_tracks(self, playlist_id: str, *, limit: int = 100): raise NotImplementedError
    def new_releases(self, *, limit: int = 20): raise NotImplementedError
    def top_artists(self, *, limit: int = 20): raise NotImplementedError
    def top_tracks(self, *, limit: int = 20): raise NotImplementedError
    def search(self, query: str, *, types=("track", "album", "artist", "playlist"), limit: int = 10): raise NotImplementedError
    def player_state(self): raise NotImplementedError
    def devices(self): raise NotImplementedError
    def play(self, *, context_uri=None, uris=None, offset_uri=None, position_ms=None, device_id=None): raise NotImplementedError
    def pause(self, *, device_id=None): raise NotImplementedError
    def next_track(self, *, device_id=None): raise NotImplementedError
    def previous_track(self, *, device_id=None): raise NotImplementedError
    def seek(self, position_ms: int, *, device_id=None): raise NotImplementedError
    def set_volume(self, percent: int, *, device_id=None): raise NotImplementedError
    def set_shuffle(self, enabled: bool, *, device_id=None): raise NotImplementedError
    def set_repeat(self, mode: str, *, device_id=None): raise NotImplementedError
    def transfer(self, device_id: str, *, play: bool = True): raise NotImplementedError
