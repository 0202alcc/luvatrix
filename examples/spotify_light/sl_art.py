"""Album art fetching, decoding, resizing, and two-level caching.

Decoded images are RGBA ``numpy`` arrays shaped ``(size, size, 4)`` — the
exact payload a ``CpuLayerNode`` needs, so the render path never re-encodes.
Fetches happen on the worker thread; the render loop only reads the cache.
"""
from __future__ import annotations

import hashlib
import urllib.request
from collections import OrderedDict
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image


class ArtError(Exception):
    pass


def _cache_key(url: str, size: int) -> str:
    return hashlib.sha1(f"{url}|{size}".encode("utf-8")).hexdigest()


def _default_http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "spotify-light/0.1"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read()


def decode_rgba(payload: bytes, size: int) -> np.ndarray:
    try:
        with Image.open(BytesIO(payload)) as image:
            image = image.convert("RGBA")
            if image.size != (size, size):
                image = image.resize((size, size), Image.LANCZOS)
            return np.asarray(image, dtype=np.uint8).copy()
    except Exception as exc:
        raise ArtError(f"could not decode image payload: {exc}") from exc


def _placeholder_color(seed: str) -> tuple[int, int, int]:
    digest = hashlib.sha1(seed.encode("utf-8")).digest()
    # Keep placeholders in a muted range so text stays readable on top.
    return (40 + digest[0] % 90, 40 + digest[1] % 90, 40 + digest[2] % 90)


class ArtCache:
    def __init__(self, cache_dir: Path, *, max_items: int = 256) -> None:
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max_items = max(8, int(max_items))
        self._mem: OrderedDict[str, np.ndarray] = OrderedDict()

    def fetch(self, url: str, size: int, *, http_get=None) -> np.ndarray:
        key = _cache_key(url, size)
        cached = self._mem_get(key)
        if cached is not None:
            return cached
        disk = self._disk_path(key)
        if disk.exists():
            rgba = decode_rgba(disk.read_bytes(), size)
            return self._mem_put(key, rgba)
        get = http_get or _default_http_get
        try:
            payload = get(url)
        except ArtError:
            raise
        except Exception as exc:
            raise ArtError(f"art download failed: {exc}") from exc
        rgba = decode_rgba(payload, size)
        try:
            disk.write_bytes(payload)
        except OSError:
            pass  # disk cache is best-effort; memory cache still applies
        return self._mem_put(key, rgba)

    def placeholder(self, seed: str, size: int) -> np.ndarray:
        key = _cache_key(f"placeholder:{seed}", size)
        cached = self._mem_get(key)
        if cached is not None:
            return cached
        r, g, b = _placeholder_color(seed)
        rgba = np.full((size, size, 4), (r, g, b, 255), dtype=np.uint8)
        return self._mem_put(key, rgba)

    def _mem_get(self, key: str) -> np.ndarray | None:
        value = self._mem.get(key)
        if value is not None:
            self._mem.move_to_end(key)
        return value

    def _mem_put(self, key: str, value: np.ndarray) -> np.ndarray:
        self._mem[key] = value
        self._mem.move_to_end(key)
        while len(self._mem) > self._max_items:
            self._mem.popitem(last=False)
        return value

    def _disk_path(self, key: str) -> Path:
        return self._dir / f"{key}.img"
