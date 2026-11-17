"""Album art fetching, decoding, and caching. Stub module — see tests."""
from __future__ import annotations

from pathlib import Path


class ArtError(Exception):
    pass


class ArtCache:
    def __init__(self, cache_dir: Path, *, max_items: int = 256) -> None:
        raise NotImplementedError

    def fetch(self, url: str, size: int, *, http_get=None): raise NotImplementedError
    def placeholder(self, seed: str, size: int): raise NotImplementedError
