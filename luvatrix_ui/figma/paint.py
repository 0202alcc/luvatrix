from __future__ import annotations

from collections.abc import Callable
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .geometry import Affine, Rect

PLACEHOLDER_RGBA = (0.85, 0.85, 0.85, 1.0)


def color_tuple(color: dict[str, Any] | None, opacity: float = 1.0) -> tuple[float, float, float, float]:
    color = color or {}
    return (
        float(color.get("r", 0.0)),
        float(color.get("g", 0.0)),
        float(color.get("b", 0.0)),
        float(color.get("a", 1.0)) * float(opacity),
    )


def premultiplied(rgba: tuple[float, float, float, float]) -> np.ndarray:
    r, g, b, a = rgba
    return np.array([[[r * a, g * a, b * a, a]]], dtype=np.float32)


def visible_paints(paints: Any) -> list[dict[str, Any]]:
    return [p for p in paints or () if isinstance(p, dict) and p.get("visible", True) is not False]


class ImageCache:
    def __init__(self, resolve: Callable[[str], Path | None]) -> None:
        self._resolve = resolve
        self._images: dict[str, np.ndarray | None] = {}

    def get(self, ref: str) -> np.ndarray | None:
        if ref not in self._images:
            path = self._resolve(ref)
            img: np.ndarray | None = None
            if path is not None:
                try:
                    with Image.open(path) as handle:
                        img = _premultiply(np.asarray(handle.convert("RGBA"), dtype=np.float32) / 255.0)
                except OSError:
                    img = None
            self._images[ref] = img
        return self._images[ref]


def _premultiply(rgba: np.ndarray) -> np.ndarray:
    out = rgba.copy()
    out[..., :3] *= out[..., 3:4]
    return out


def _local_uv(rect: Rect, inv: Affine, width: float, height: float) -> tuple[np.ndarray, np.ndarray]:
    x0, y0, x1, y1 = rect
    xs = np.arange(x0, x1, dtype=np.float64) + 0.5
    ys = np.arange(y0, y1, dtype=np.float64) + 0.5
    px, py = np.meshgrid(xs, ys)
    lx = inv.a * px + inv.c * py + inv.tx
    ly = inv.b * px + inv.d * py + inv.ty
    return lx / max(width, 1e-6), ly / max(height, 1e-6)


def _stops(paint: dict[str, Any], opacity: float) -> tuple[np.ndarray, np.ndarray]:
    stops = sorted(paint.get("gradientStops") or (), key=lambda s: float(s.get("position", 0.0)))
    if not stops:
        stops = [{"position": 0.0, "color": {"r": 0, "g": 0, "b": 0, "a": 0}}]
    pos = np.array([float(s.get("position", 0.0)) for s in stops], dtype=np.float64)
    cols = np.concatenate([premultiplied(color_tuple(s.get("color"), opacity))[0] for s in stops], axis=0)
    return pos, cols


def _interp_stops(t: np.ndarray, pos: np.ndarray, cols: np.ndarray) -> np.ndarray:
    out = np.empty(t.shape + (4,), dtype=np.float32)
    for ch in range(4):
        out[..., ch] = np.interp(t, pos, cols[:, ch])
    return out


def _handles(paint: dict[str, Any]) -> list[tuple[float, float]]:
    handles = paint.get("gradientHandlePositions") or []
    pts = [(float(h.get("x", 0.0)), float(h.get("y", 0.0))) for h in handles[:3]]
    defaults = [(0.0, 0.5), (1.0, 0.5), (0.0, 1.0)]
    return pts + defaults[len(pts) :]


def paint_field(
    paint: dict[str, Any],
    rect: Rect,
    tf: Affine,
    size: tuple[float, float],
    images: ImageCache,
    *,
    opacity: float = 1.0,
) -> np.ndarray | None:
    """Premultiplied RGBA for `paint` over device `rect`; may broadcast as (1, 1, 4)."""
    kind = paint.get("type")
    alpha = float(paint.get("opacity", 1.0)) * opacity
    if kind == "SOLID":
        return premultiplied(color_tuple(paint.get("color"), alpha))
    width, height = size
    inv = tf.inverse()
    if kind in {"GRADIENT_LINEAR", "GRADIENT_RADIAL", "GRADIENT_ANGULAR", "GRADIENT_DIAMOND"}:
        u, v = _local_uv(rect, inv, width, height)
        (p0x, p0y), (p1x, p1y), (p2x, p2y) = _handles(paint)
        pos, cols = _stops(paint, alpha)
        if kind == "GRADIENT_LINEAR":
            dx, dy = p1x - p0x, p1y - p0y
            t = ((u - p0x) * dx + (v - p0y) * dy) / max(dx * dx + dy * dy, 1e-12)
        else:
            ax, ay, bx, by = p1x - p0x, p1y - p0y, p2x - p0x, p2y - p0y
            det = ax * by - ay * bx
            if abs(det) < 1e-12:
                return premultiplied(tuple(cols[-1]))  # type: ignore[arg-type]
            qx, qy = u - p0x, v - p0y
            s = (qx * by - qy * bx) / det
            r = (ax * qy - ay * qx) / det
            if kind == "GRADIENT_RADIAL":
                t = np.sqrt(s * s + r * r)
            elif kind == "GRADIENT_DIAMOND":
                t = np.abs(s) + np.abs(r)
            else:
                t = (np.arctan2(r, s) / (2 * math.pi)) % 1.0
        return _interp_stops(np.clip(t, 0.0, 1.0), pos, cols)
    if kind == "IMAGE":
        img = images.get(str(paint.get("imageRef", "")))
        if img is None:
            return premultiplied((*PLACEHOLDER_RGBA[:3], PLACEHOLDER_RGBA[3] * alpha))
        return _image_field(paint, img, rect, tf, inv, size, alpha)
    return None


def _image_field(
    paint: dict[str, Any],
    img: np.ndarray,
    rect: Rect,
    tf: Affine,
    inv: Affine,
    size: tuple[float, float],
    alpha: float,
) -> np.ndarray:
    width, height = size
    ih, iw = img.shape[:2]
    mode = str(paint.get("scaleMode", "FILL")).upper()
    u, v = _local_uv(rect, inv, width, height)
    lx, ly = u * width, v * height
    device_scale = tf.mean_scale
    valid: np.ndarray | None = None
    if mode == "TILE":
        factor = float(paint.get("scalingFactor", 1.0)) or 1.0
        target = (iw * factor * device_scale, ih * factor * device_scale)
        img = _resample(img, target)
        th, tw = img.shape[:2]
        ix = np.mod(lx * device_scale, tw)
        iy = np.mod(ly * device_scale, th)
        return _bilinear(img, ix, iy, wrap=True) * alpha
    transform = paint.get("imageTransform")
    if mode in {"STRETCH", "CROP"} and isinstance(transform, list) and len(transform) == 2:
        t = Affine.from_figma(transform)
        iu = t.a * u + t.c * v + t.tx
        iv = t.b * u + t.d * v + t.ty
        target = (width * device_scale / max(t.a, 1e-6), height * device_scale / max(t.d, 1e-6))
    else:
        if mode == "FIT":
            k = min(width / iw, height / ih)
        elif mode == "STRETCH":
            k = 0.0
        else:
            k = max(width / iw, height / ih)
        if k == 0.0:
            iu, iv = u, v
            target = (width * device_scale, height * device_scale)
        else:
            dw, dh = iw * k, ih * k
            iu = (lx - (width - dw) / 2) / dw
            iv = (ly - (height - dh) / 2) / dh
            target = (dw * device_scale, dh * device_scale)
            if mode == "FIT":
                valid = (iu >= 0) & (iu <= 1) & (iv >= 0) & (iv <= 1)
    img = _resample(img, target)
    th, tw = img.shape[:2]
    out = _bilinear(img, iu * tw - 0.5, iv * th - 0.5, wrap=False)
    if valid is not None:
        out *= valid[..., None]
    return out * alpha


def _resample(img: np.ndarray, target: tuple[float, float]) -> np.ndarray:
    tw, th = max(1, int(round(target[0]))), max(1, int(round(target[1])))
    ih, iw = img.shape[:2]
    if tw >= iw and th >= ih:
        return img
    tw, th = min(tw, iw), min(th, ih)
    channels = [Image.fromarray(np.ascontiguousarray(img[..., ch], dtype=np.float32)).resize((tw, th), Image.BOX) for ch in range(4)]
    return np.stack([np.asarray(ch, dtype=np.float32) for ch in channels], axis=-1)


def _bilinear(img: np.ndarray, x: np.ndarray, y: np.ndarray, *, wrap: bool) -> np.ndarray:
    h, w = img.shape[:2]
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx = (x - x0)[..., None].astype(np.float32)
    fy = (y - y0)[..., None].astype(np.float32)
    if wrap:
        xa, xb = np.mod(x0, w), np.mod(x0 + 1, w)
        ya, yb = np.mod(y0, h), np.mod(y0 + 1, h)
    else:
        xa, xb = np.clip(x0, 0, w - 1), np.clip(x0 + 1, 0, w - 1)
        ya, yb = np.clip(y0, 0, h - 1), np.clip(y0 + 1, 0, h - 1)
    top = img[ya, xa] * (1 - fx) + img[ya, xb] * fx
    bottom = img[yb, xa] * (1 - fx) + img[yb, xb] * fx
    return (top * (1 - fy) + bottom * fy).astype(np.float32)
