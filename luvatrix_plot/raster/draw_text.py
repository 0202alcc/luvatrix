from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from luvatrix_plot.raster.canvas import RGBA


DEFAULT_FONT_FAMILY = "Comic Mono"
DEFAULT_FONT_SIZE_PX = 10.0
MONO_FONT_FALLBACK_PATTERNS = (
    "comicmono",
    "comic mono",
    "menlo",
    "monaco",
    "courier new",
    "courier",
    "dejavusansmono",
    "dejavu sans mono",
)


def draw_text(
    dst: np.ndarray,
    x: int,
    y: int,
    text: str,
    color: RGBA,
    *,
    font_family: str = DEFAULT_FONT_FAMILY,
    font_size_px: float = DEFAULT_FONT_SIZE_PX,
    embolden_px: int = 1,
    background_color: RGBA | None = None,
    rotate_deg: int = 0,
) -> None:
    if not text:
        return
    font = _load_font(font_family=font_family, font_size_px=font_size_px)
    mask = _render_mask(text=text, font=font)
    if embolden_px > 1:
        mask = _embolden(mask, embolden_px)
    mask = _rotate_mask(mask, rotate_deg=rotate_deg)
    _blend_mask(dst, x, y, mask, color, background_color=background_color)


def text_size(
    text: str,
    *,
    font_family: str = DEFAULT_FONT_FAMILY,
    font_size_px: float = DEFAULT_FONT_SIZE_PX,
    rotate_deg: int = 0,
) -> tuple[int, int]:
    font = _load_font(font_family=font_family, font_size_px=font_size_px)
    if not text:
        ascent, descent = font.getmetrics()
        return (0, max(1, int(ascent + descent)))
    left, top, right, bottom = font.getbbox(text)
    w = max(0, int(right - left))
    h = max(1, int(bottom - top))
    turns = _normalize_quarter_turns(rotate_deg)
    if turns % 2 == 1:
        return (h, w)
    return (w, h)


def _blend_mask(
    dst: np.ndarray,
    x: int,
    y: int,
    mask: np.ndarray,
    color: RGBA,
    *,
    background_color: RGBA | None = None,
) -> None:
    h, w = mask.shape
    if h <= 0 or w <= 0:
        return

    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(dst.shape[1], x + w)
    y1 = min(dst.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return

    sx0 = x0 - x
    sy0 = y0 - y
    sx1 = sx0 + (x1 - x0)
    sy1 = sy0 + (y1 - y0)

    cov = mask[sy0:sy1, sx0:sx1].astype(np.float32) / 255.0
    if not np.any(cov > 0) and background_color is None:
        return

    patch = dst[y0:y1, x0:x1]
    dst_rgb = patch[:, :, :3].astype(np.float32)
    dst_alpha = patch[:, :, 3].astype(np.float32) / 255.0

    if background_color is not None:
        bg_alpha = np.full(cov.shape, background_color[3] / 255.0, dtype=np.float32)
        bg_rgb = np.asarray(background_color[:3], dtype=np.float32).reshape(1, 1, 3)
        out_bg_a = bg_alpha + dst_alpha * (1.0 - bg_alpha)
        out_bg_rgb_num = bg_rgb * bg_alpha[:, :, None] + dst_rgb * dst_alpha[:, :, None] * (1.0 - bg_alpha[:, :, None])
        safe_bg_a = np.where(out_bg_a > 1e-6, out_bg_a, 1.0)
        dst_rgb = out_bg_rgb_num / safe_bg_a[:, :, None]
        dst_alpha = out_bg_a

    src_alpha = (color[3] / 255.0) * cov
    if not np.any(src_alpha > 0):
        patch[:, :, :3] = np.clip(dst_rgb, 0, 255).astype(np.uint8)
        patch[:, :, 3] = np.clip(dst_alpha * 255.0, 0, 255).astype(np.uint8)
        return

    src_rgb = np.asarray(color[:3], dtype=np.float32).reshape(1, 1, 3)
    out_alpha = src_alpha + dst_alpha * (1.0 - src_alpha)
    out_rgb_num = src_rgb * src_alpha[:, :, None] + dst_rgb * dst_alpha[:, :, None] * (1.0 - src_alpha[:, :, None])
    safe_alpha = np.where(out_alpha > 1e-6, out_alpha, 1.0)
    out_rgb = out_rgb_num / safe_alpha[:, :, None]

    patch[:, :, :3] = np.clip(out_rgb, 0, 255).astype(np.uint8)
    patch[:, :, 3] = np.clip(out_alpha * 255.0, 0, 255).astype(np.uint8)


def _embolden(mask: np.ndarray, embolden_px: int) -> np.ndarray:
    if embolden_px <= 1:
        return mask
    out = mask.copy()
    for shift in range(1, embolden_px):
        src = mask[:, : max(0, mask.shape[1] - shift)]
        dst = out[:, shift:]
        if src.size == 0 or dst.size == 0:
            break
        np.maximum(dst, src, out=dst)
    return out


@lru_cache(maxsize=128)
def _render_mask(text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> np.ndarray:
    if not text:
        return np.zeros((1, 1), dtype=np.uint8)
    left, top, right, bottom = font.getbbox(text)
    width = max(1, int(right - left))
    height = max(1, int(bottom - top))
    image = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(image)
    draw.text((-left, -top), text, fill=255, font=font)
    return np.asarray(image, dtype=np.uint8)


@lru_cache(maxsize=64)
def _load_font(font_family: str, font_size_px: float) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = max(1, int(round(font_size_px)))
    font_path = _resolve_font_path(font_family)
    if font_path is None:
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(str(font_path), size=size)
    except Exception:
        return ImageFont.load_default()


def _resolve_font_path(font_family: str) -> Path | None:
    wanted = font_family.strip().lower() if font_family.strip() else DEFAULT_FONT_FAMILY.lower()
    patterns = (wanted,) + MONO_FONT_FALLBACK_PATTERNS

    font_dirs = [
        Path.home() / "Library" / "Fonts",
        Path("/Library/Fonts"),
        Path("/System/Library/Fonts"),
        Path("/System/Library/Fonts/Supplemental"),
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
    ]

    candidates: list[Path] = []
    for base in font_dirs:
        if not base.exists():
            continue
        for ext in ("*.ttf", "*.otf", "*.ttc"):
            candidates.extend(base.rglob(ext))

    for pattern in patterns:
        p = pattern.replace(" ", "")
        for path in candidates:
            stem = path.stem.lower().replace(" ", "")
            name = path.name.lower().replace(" ", "")
            if p in stem or p in name:
                return path
    return None


def _normalize_quarter_turns(rotate_deg: int) -> int:
    if rotate_deg % 90 != 0:
        raise ValueError("rotate_deg must be a multiple of 90")
    return (rotate_deg // 90) % 4


def _rotate_mask(mask: np.ndarray, *, rotate_deg: int) -> np.ndarray:
    turns = _normalize_quarter_turns(rotate_deg)
    if turns == 0:
        return mask
    return np.rot90(mask, k=turns)
