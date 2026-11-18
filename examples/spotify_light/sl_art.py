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


def rounded_rgba(rgba: np.ndarray, radius_px: float) -> np.ndarray:
    """Copy of square RGBA art alpha-clipped to a rounded-rect silhouette.

    4x supersampled coverage keeps the arc smooth (a hard 1px step reads as
    jaggies on Retina). The source — usually an ArtCache entry shared with
    other consumers — is never mutated; ``radius_px`` is in BUFFER pixels,
    so Retina-sized buffers take a proportionally larger radius.
    """
    size = int(rgba.shape[0])
    radius = max(0.0, min(float(radius_px), size / 2.0))
    if radius <= 0.0:
        return rgba.copy()
    ss = 4
    grid = (np.arange(size * ss, dtype=np.float32) + 0.5) / ss
    xs, ys = np.meshgrid(grid, grid)
    half = size / 2.0
    qx = np.abs(xs - half) - (half - radius)
    qy = np.abs(ys - half) - (half - radius)
    dist = np.hypot(np.maximum(qx, 0.0), np.maximum(qy, 0.0)) + np.minimum(
        np.maximum(qx, qy), 0.0)
    inside = dist <= radius
    coverage = inside.reshape(size, ss, size, ss).mean(axis=(1, 3))
    out = rgba.copy()
    out[:, :, 3] = np.round(out[:, :, 3].astype(np.float32) * coverage).astype(np.uint8)
    return out


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

    def masked(self, rgba: np.ndarray, radius_px: float, *, key: str) -> np.ndarray:
        """Rounded variant of an already-cached image, memoized under its own
        key so the square original stays intact for other consumers and the
        mask is computed once per (image, radius, buffer size)."""
        mask_key = _cache_key(f"mask:{key}|{float(radius_px):.2f}", int(rgba.shape[0]))
        cached = self._mem_get(mask_key)
        if cached is not None:
            return cached
        return self._mem_put(mask_key, rounded_rgba(rgba, radius_px))

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
