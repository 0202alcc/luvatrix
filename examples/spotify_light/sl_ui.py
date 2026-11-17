"""Pure presentation helpers for the Spotify Light UI. Stub module — see tests."""
from __future__ import annotations

from dataclasses import dataclass


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


def format_duration_ms(ms: int) -> str: raise NotImplementedError
def truncate(text: str, max_chars: int) -> str: raise NotImplementedError
def grid_columns(viewport_width: float, *, card_width: float, gap: float) -> int: raise NotImplementedError
def interpolate_progress(*, base_ms: int, base_monotonic: float, duration_ms: int, playing: bool, now: float | None = None) -> int: raise NotImplementedError
def seek_fraction(progress_ms: int, duration_ms: int) -> float: raise NotImplementedError
def build_home_sections(*, top_tracks, new_releases, playlists, top_artists) -> list[SectionView]: raise NotImplementedError
def build_track_rows(tracks) -> list[TrackRow]: raise NotImplementedError
