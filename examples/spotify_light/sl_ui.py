"""Pure presentation helpers: formatting, layout math, and view-model builders.

Everything here is side-effect free so the render layer stays thin and the
logic stays unit-testable without an app context.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import sl_models

ELLIPSIS = "…"


@dataclass(frozen=True)
class CardView:
    id: str
    title: str
    subtitle: str
    image_url: str | None
    context_uri: str | None
    kind: str  # "playlist" | "album" | "artist" | "track"


@dataclass(frozen=True)
class SectionView:
    title: str
    cards: tuple[CardView, ...]


@dataclass(frozen=True)
class TrackRow:
    index: int
    title: str
    artists: str
    album: str
    duration: str
    uri: str


def format_duration_ms(ms: int) -> str:
    total_seconds = max(0, int(ms) // 1000)
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars == 1:
        return ELLIPSIS
    return text[: max_chars - 1] + ELLIPSIS


def grid_columns(viewport_width: float, *, card_width: float, gap: float) -> int:
    """Columns that fit viewport_width; at least 2, at most 8."""
    if viewport_width <= 0 or card_width <= 0:
        return 2
    cols = int((viewport_width + gap) // (card_width + gap))
    return max(2, min(8, cols))


def interpolate_progress(
    *,
    base_ms: int,
    base_monotonic: float,
    duration_ms: int,
    playing: bool,
    now: float | None = None,
) -> int:
    """Now-playing progress between player polls; clamps at the track end."""
    if not playing:
        return max(0, int(base_ms))
    current = time.monotonic() if now is None else now
    elapsed_ms = max(0.0, current - base_monotonic) * 1000.0
    estimate = int(base_ms + elapsed_ms)
    if duration_ms > 0:
        return min(estimate, duration_ms)
    return estimate


def seek_fraction(progress_ms: int, duration_ms: int) -> float:
    if duration_ms <= 0:
        return 0.0
    return max(0.0, min(1.0, progress_ms / duration_ms))


def _artist_names(artists) -> str:
    names = [a.name for a in artists if a.name]
    return ", ".join(names) if names else "Unknown artist"


def track_card(track: sl_models.Track, *, image_target_px: int = 300) -> CardView:
    return CardView(
        id=track.id,
        title=track.name,
        subtitle=_artist_names(track.artists),
        image_url=sl_models.pick_image_url(track.album.images if track.album else (), image_target_px),
        context_uri=track.uri,
        kind="track",
    )


def album_card(album: sl_models.Album, *, image_target_px: int = 300) -> CardView:
    return CardView(
        id=album.id,
        title=album.name,
        subtitle=_artist_names(album.artists),
        image_url=sl_models.pick_image_url(album.images, image_target_px),
        context_uri=album.uri,
        kind="album",
    )


def playlist_card(playlist: sl_models.Playlist, *, image_target_px: int = 300) -> CardView:
    subtitle = f"{playlist.track_count} tracks" if playlist.track_count is not None else "Playlist"
    return CardView(
        id=playlist.id,
        title=playlist.name,
        subtitle=subtitle,
        image_url=sl_models.pick_image_url(playlist.images, image_target_px),
        context_uri=playlist.uri,
        kind="playlist",
    )


def artist_card(artist: sl_models.Artist, *, image_target_px: int = 300) -> CardView:
    return CardView(
        id=artist.id,
        title=artist.name,
        subtitle="Artist",
        image_url=sl_models.pick_image_url(artist.images, image_target_px),
        context_uri=None,  # artist playback needs an artist-radio context; not wired in v1
        kind="artist",
    )


def build_home_sections(*, top_tracks, new_releases, playlists, top_artists, image_target_px: int = 300) -> list[SectionView]:
    sections: list[SectionView] = []
    if top_tracks:
        sections.append(SectionView("Top tracks", tuple(track_card(t, image_target_px=image_target_px) for t in top_tracks)))
    if new_releases:
        sections.append(SectionView("New releases", tuple(album_card(a, image_target_px=image_target_px) for a in new_releases)))
    if playlists:
        sections.append(SectionView("Your playlists", tuple(playlist_card(p, image_target_px=image_target_px) for p in playlists)))
    if top_artists:
        sections.append(SectionView("Top artists", tuple(artist_card(a, image_target_px=image_target_px) for a in top_artists)))
    return sections


def build_track_rows(tracks) -> list[TrackRow]:
    rows: list[TrackRow] = []
    for index, track in enumerate(tracks, start=1):
        rows.append(
            TrackRow(
                index=index,
                title=track.name,
                artists=_artist_names(track.artists),
                album=track.album.name if track.album else "",
                duration=format_duration_ms(track.duration_ms),
                uri=track.uri,
            )
        )
    return rows
