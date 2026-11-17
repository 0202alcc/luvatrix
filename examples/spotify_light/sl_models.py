"""Spotify Web API response models. Stub module — see tests."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Image:
    url: str
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class Artist:
    id: str
    name: str
    uri: str
    images: tuple[Image, ...] = ()


@dataclass(frozen=True)
class Album:
    id: str
    name: str
    uri: str
    artists: tuple[Artist, ...] = ()
    images: tuple[Image, ...] = ()
    release_date: str | None = None
    total_tracks: int | None = None


@dataclass(frozen=True)
class Track:
    id: str
    name: str
    uri: str
    duration_ms: int
    artists: tuple[Artist, ...] = ()
    album: Album | None = None
    track_number: int | None = None
    explicit: bool = False


@dataclass(frozen=True)
class Playlist:
    id: str
    name: str
    uri: str
    images: tuple[Image, ...] = ()
    owner_name: str | None = None
    track_count: int | None = None


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    kind: str
    is_active: bool
    is_restricted: bool
    volume_percent: int | None


@dataclass(frozen=True)
class PlayerState:
    is_playing: bool
    progress_ms: int
    track: Track | None
    device: Device | None
    shuffle: bool
    repeat: str
    timestamp_ms: int | None = None


@dataclass(frozen=True)
class Profile:
    id: str
    display_name: str | None
    email: str | None
    image_url: str | None
    product: str | None


@dataclass(frozen=True)
class SearchResults:
    tracks: tuple[Track, ...] = ()
    albums: tuple[Album, ...] = ()
    artists: tuple[Artist, ...] = ()
    playlists: tuple[Playlist, ...] = ()


def parse_track(payload: dict) -> Track: raise NotImplementedError
def parse_track_or_none(payload) -> Track | None: raise NotImplementedError
def parse_album(payload: dict) -> Album: raise NotImplementedError
def parse_artist(payload: dict) -> Artist: raise NotImplementedError
def parse_playlist(payload: dict) -> Playlist: raise NotImplementedError
def parse_device(payload: dict) -> Device: raise NotImplementedError
def parse_player_state(payload: dict) -> PlayerState: raise NotImplementedError
def parse_profile(payload: dict) -> Profile: raise NotImplementedError
def parse_search_results(payload: dict) -> SearchResults: raise NotImplementedError
def parse_playlist_tracks_page(payload: dict) -> tuple[list[Track], bool]: raise NotImplementedError
def parse_playlists_page(payload: dict) -> tuple[list[Playlist], bool]: raise NotImplementedError
def pick_image_url(images, target_px: int) -> str | None: raise NotImplementedError
