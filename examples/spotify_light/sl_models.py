"""Spotify Web API response models and defensive parsers.

Parsers tolerate the shapes Spotify actually returns: playlist items with a
null `track` (local files), missing images, absent optional fields, and
partial player state when nothing is playing.
"""
from __future__ import annotations

from dataclasses import dataclass


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


def _str(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def parse_image(payload: dict) -> Image | None:
    if not isinstance(payload, dict):
        return None
    url = payload.get("url")
    if not isinstance(url, str) or not url:
        return None
    return Image(url=url, width=_int_or_none(payload.get("width")), height=_int_or_none(payload.get("height")))


def _parse_images(payload: object) -> tuple[Image, ...]:
    if not isinstance(payload, list):
        return ()
    return tuple(img for img in (parse_image(item) for item in payload) if img is not None)


def parse_artist(payload: dict) -> Artist:
    artist_id = _str(payload.get("id"))
    return Artist(
        id=artist_id,
        name=_str(payload.get("name")),
        uri=_str(payload.get("uri"), f"spotify:artist:{artist_id}"),
        images=_parse_images(payload.get("images")),
    )


def parse_album(payload: dict) -> Album:
    album_id = _str(payload.get("id"))
    artists = payload.get("artists")
    return Album(
        id=album_id,
        name=_str(payload.get("name")),
        uri=_str(payload.get("uri"), f"spotify:album:{album_id}"),
        artists=tuple(parse_artist(a) for a in artists if isinstance(a, dict)) if isinstance(artists, list) else (),
        images=_parse_images(payload.get("images")),
        release_date=payload.get("release_date") if isinstance(payload.get("release_date"), str) else None,
        total_tracks=_int_or_none(payload.get("total_tracks")),
    )


def parse_track(payload: dict) -> Track:
    track_id = _str(payload.get("id"))
    artists = payload.get("artists")
    album = payload.get("album")
    duration = payload.get("duration_ms")
    return Track(
        id=track_id,
        name=_str(payload.get("name")),
        uri=_str(payload.get("uri"), f"spotify:track:{track_id}"),
        duration_ms=duration if isinstance(duration, int) and duration >= 0 else 0,
        artists=tuple(parse_artist(a) for a in artists if isinstance(a, dict)) if isinstance(artists, list) else (),
        album=parse_album(album) if isinstance(album, dict) else None,
        track_number=_int_or_none(payload.get("track_number")),
        explicit=bool(payload.get("explicit", False)),
    )


def parse_track_or_none(payload: object) -> Track | None:
    """Playlist/search items can be null (local files) or partial; skip those."""
    if not isinstance(payload, dict):
        return None
    if not payload.get("id") or not payload.get("name"):
        return None
    uri = payload.get("uri")
    if not isinstance(uri, str) or not uri.startswith("spotify:track:"):
        return None
    return parse_track(payload)


def parse_playlist(payload: dict) -> Playlist:
    playlist_id = _str(payload.get("id"))
    owner = payload.get("owner")
    tracks = payload.get("tracks")
    track_count = None
    if isinstance(tracks, dict):
        track_count = _int_or_none(tracks.get("total"))
    return Playlist(
        id=playlist_id,
        name=_str(payload.get("name")),
        uri=_str(payload.get("uri"), f"spotify:playlist:{playlist_id}"),
        images=_parse_images(payload.get("images")),
        owner_name=owner.get("display_name") if isinstance(owner, dict) and isinstance(owner.get("display_name"), str) else None,
        track_count=track_count,
    )


def parse_device(payload: dict) -> Device:
    return Device(
        id=_str(payload.get("id")),
        name=_str(payload.get("name")),
        kind=_str(payload.get("type")),
        is_active=bool(payload.get("is_active", False)),
        is_restricted=bool(payload.get("is_restricted", False)),
        volume_percent=_int_or_none(payload.get("volume_percent")),
    )


def parse_player_state(payload: dict) -> PlayerState:
    device = payload.get("device")
    item = payload.get("item")
    progress = payload.get("progress_ms")
    return PlayerState(
        is_playing=bool(payload.get("is_playing", False)),
        progress_ms=progress if isinstance(progress, int) and progress >= 0 else 0,
        track=parse_track_or_none(item),
        device=parse_device(device) if isinstance(device, dict) else None,
        shuffle=bool(payload.get("shuffle_state", False)),
        repeat=_str(payload.get("repeat_state"), "off"),
        timestamp_ms=_int_or_none(payload.get("timestamp")),
    )


def parse_profile(payload: dict) -> Profile:
    images = _parse_images(payload.get("images"))
    return Profile(
        id=_str(payload.get("id")),
        display_name=payload.get("display_name") if isinstance(payload.get("display_name"), str) else None,
        email=payload.get("email") if isinstance(payload.get("email"), str) else None,
        image_url=images[0].url if images else None,
        product=payload.get("product") if isinstance(payload.get("product"), str) else None,
    )


def parse_search_results(payload: dict) -> SearchResults:
    def section(name: str) -> list:
        block = payload.get(name)
        if not isinstance(block, dict):
            return []
        items = block.get("items")
        return items if isinstance(items, list) else []

    return SearchResults(
        tracks=tuple(t for t in (parse_track_or_none(i) for i in section("tracks")) if t is not None),
        albums=tuple(parse_album(i) for i in section("albums") if isinstance(i, dict) and i.get("id")),
        artists=tuple(parse_artist(i) for i in section("artists") if isinstance(i, dict) and i.get("id")),
        playlists=tuple(
            parse_playlist(i) for i in section("playlists") if isinstance(i, dict) and i.get("id")
        ),
    )


def parse_playlist_tracks_page(payload: dict) -> tuple[list[Track], bool]:
    items = payload.get("items")
    tracks = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            track = parse_track_or_none(item.get("track"))
            if track is not None:
                tracks.append(track)
    return tracks, bool(payload.get("next"))


def parse_playlists_page(payload: dict) -> tuple[list[Playlist], bool]:
    items = payload.get("items")
    playlists = []
    if isinstance(items, list):
        playlists = [parse_playlist(i) for i in items if isinstance(i, dict) and i.get("id")]
    return playlists, bool(payload.get("next"))


def parse_albums_page_items(payload: dict) -> tuple[list[Album], bool]:
    albums = payload.get("albums")
    if not isinstance(albums, dict):
        return [], False
    items = albums.get("items")
    parsed = [parse_album(i) for i in items if isinstance(i, dict) and i.get("id")] if isinstance(items, list) else []
    return parsed, bool(albums.get("next"))


def pick_image_url(images: tuple[Image, ...] | list[Image], target_px: int) -> str | None:
    """Smallest image that still covers target_px; falls back to the largest available."""
    if not images:
        return None
    with_dims = [i for i in images if i.width and i.width > 0]
    if not with_dims:
        return images[0].url
    covering = [i for i in with_dims if i.width >= target_px]
    if covering:
        return min(covering, key=lambda i: i.width).url
    return max(with_dims, key=lambda i: i.width).url
