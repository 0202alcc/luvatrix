from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import torch

from PIL import Image, ImageDraw, ImageFont

from luvatrix_ui.component_schema import DisplayableArea
from luvatrix_ui.controls.svg_renderer import SVGRenderBatch, SVGRenderCommand
from luvatrix_ui.text.renderer import FontSpec, TextLayoutMetrics, TextMeasureRequest, TextRenderBatch, TextRenderCommand

from luvatrix_core.render.svg import SvgDocument


@dataclass(frozen=True)
class _GlyphBitmap:
    alpha_mask: np.ndarray
    x_offset: int
    y_offset: int
    advance: float


@dataclass
class _FontAtlas:
    key: tuple[str, int]
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    size_px: float
    ascent: float
    descent: float
    line_height: float
    glyphs: dict[str, _GlyphBitmap] = field(default_factory=dict)


@dataclass
class MatrixUIFrameRenderer:
    """Torch-first component-to-matrix renderer for app protocol UI frames."""

    _display: DisplayableArea | None = None
    _frame: torch.Tensor | None = None
    _grid_x: torch.Tensor | None = None
    _grid_y: torch.Tensor | None = None
    _svg_cache: dict[str, SvgDocument] = field(default_factory=dict)
    _font_atlas_cache: dict[tuple[str, int], _FontAtlas] = field(default_factory=dict)
    _bitmap_cache_enabled_default: bool = field(default_factory=lambda: _env_flag("LUVATRIX_SCROLL_BITMAP_CACHE_ENABLED", False))
    _bitmap_cache_enabled_override: bool | None = None
    _bitmap_cache_max_entries: int = field(default_factory=lambda: _env_int("LUVATRIX_SCROLL_BITMAP_CACHE_MAX_ENTRIES", 128, 1, 4096))
    _bitmap_cache_max_pixels: int = field(default_factory=lambda: _env_int("LUVATRIX_SCROLL_BITMAP_CACHE_MAX_PIXELS", 2_000_000, 4096, 16_000_000))
    _svg_bitmap_cache: OrderedDict[tuple[Any, ...], torch.Tensor] = field(default_factory=OrderedDict)
    _text_bitmap_cache: OrderedDict[tuple[Any, ...], torch.Tensor] = field(default_factory=OrderedDict)
    _bitmap_cache_hits: int = 0
    _bitmap_cache_misses: int = 0

    def begin_frame(self, display: DisplayableArea, clear_color: tuple[int, int, int, int]) -> None:
        self._display = display
        width = int(round(display.viewport_width_px or display.content_width_px))
        height = int(round(display.viewport_height_px or display.content_height_px))
        if width <= 0 or height <= 0:
            raise ValueError("frame dimensions must be > 0")
        self._frame = torch.zeros((height, width, 4), dtype=torch.uint8)
        self._frame[:, :, 0] = clear_color[0]
        self._frame[:, :, 1] = clear_color[1]
        self._frame[:, :, 2] = clear_color[2]
        self._frame[:, :, 3] = clear_color[3]
        self._grid_x = torch.arange(width, dtype=torch.float32).unsqueeze(0).expand(height, width)
        self._grid_y = torch.arange(height, dtype=torch.float32).unsqueeze(1).expand(height, width)
        self._bitmap_cache_hits = 0
        self._bitmap_cache_misses = 0

    def set_bitmap_cache_enabled(self, enabled: bool) -> None:
        self._bitmap_cache_enabled_override = bool(enabled)

    def consume_bitmap_cache_stats(self) -> dict[str, int | bool]:
        return {
            "enabled": bool(self._bitmap_cache_enabled()),
            "hits": int(self._bitmap_cache_hits),
            "misses": int(self._bitmap_cache_misses),
            "entry_count": int(len(self._svg_bitmap_cache) + len(self._text_bitmap_cache)),
        }

    def prepare_font(self, font: FontSpec, *, size_px: float, charset: str) -> None:
        atlas = self._ensure_atlas(font, size_px)
        for ch in charset:
            self._ensure_glyph(atlas, ch)

    def measure_text(self, request: TextMeasureRequest) -> TextLayoutMetrics:
        atlas = self._ensure_atlas(request.font, request.font_size_px)
        lines = self._wrap_lines(
            request.text,
            atlas,
            max_width_px=request.max_width_px,
            letter_spacing_px=request.appearance.letter_spacing_px,
        )
        widths = [self._line_advance(line, atlas, request.appearance.letter_spacing_px) for line in lines]
        line_h = max(atlas.line_height, request.font_size_px * request.appearance.line_height_multiplier)
        return TextLayoutMetrics(
            width_px=max(widths) if widths else 0.0,
            height_px=max(request.font_size_px, float(len(lines)) * line_h),
            baseline_px=atlas.ascent,
            line_count=max(1, len(lines)),
        )

    def draw_text_batch(self, batch: TextRenderBatch) -> None:
        if self._frame is None:
            raise RuntimeError("begin_frame must be called before draw_text_batch")
        for command in batch.commands:
            if self._bitmap_cache_enabled() and self._command_is_pixel_aligned(command.x, command.y):
                key = self._text_bitmap_key(command)
                cached = self._text_bitmap_cache.get(key)
                if cached is not None:
                    self._bitmap_cache_hits += 1
                    self._text_bitmap_cache.move_to_end(key)
                    self._blend_bitmap(cached, x=int(round(command.x)), y=int(round(command.y)))
                    continue
                bitmap = self._rasterize_text_bitmap(command)
                if self._bitmap_cacheable(bitmap):
                    self._bitmap_cache_misses += 1
                    self._cache_put(self._text_bitmap_cache, key, bitmap)
                    self._blend_bitmap(bitmap, x=int(round(command.x)), y=int(round(command.y)))
                    continue
            atlas = self._ensure_atlas(command.font, command.font_size_px)
            lines = self._wrap_lines(
                command.text,
                atlas,
                max_width_px=command.max_width_px,
                letter_spacing_px=command.appearance.letter_spacing_px,
            )
            color = _parse_rgba_u8(command.appearance.color_hex, command.appearance.opacity)
            line_h = max(atlas.line_height, command.font_size_px * command.appearance.line_height_multiplier)
            for i, line in enumerate(lines):
                top_y = command.y + i * line_h
                self._draw_line(
                    line,
                    atlas,
                    x=command.x,
                    top_y=top_y,
                    color=color,
                    letter_spacing_px=command.appearance.letter_spacing_px,
                )

    def draw_svg_batch(self, batch: SVGRenderBatch) -> None:
        if self._frame is None or self._grid_x is None or self._grid_y is None:
            raise RuntimeError("begin_frame must be called before draw_svg_batch")
        for command in batch.commands:
            if (
                self._bitmap_cache_enabled()
                and self._command_is_pixel_aligned(command.x, command.y)
                and self._command_is_pixel_aligned(command.width, command.height)
            ):
                key = self._svg_bitmap_key(command)
                cached = self._svg_bitmap_cache.get(key)
                if cached is not None:
                    self._bitmap_cache_hits += 1
                    self._svg_bitmap_cache.move_to_end(key)
                    self._blend_bitmap(cached, x=int(round(command.x)), y=int(round(command.y)))
                    continue
                bitmap = self._rasterize_svg_bitmap(command)
                if self._bitmap_cacheable(bitmap):
                    self._bitmap_cache_misses += 1
                    self._cache_put(self._svg_bitmap_cache, key, bitmap)
                    self._blend_bitmap(bitmap, x=int(round(command.x)), y=int(round(command.y)))
                    continue
            doc = self._doc_for_markup(command.svg_markup)
            self._render_svg_document(doc, command)

    def end_frame(self) -> torch.Tensor:
        if self._frame is None:
            raise RuntimeError("begin_frame must be called before end_frame")
        out = self._frame.clone()
        self._display = None
        self._frame = None
        self._grid_x = None
        self._grid_y = None
        return out

    def _doc_for_markup(self, svg_markup: str) -> SvgDocument:
        key = hashlib.sha256(svg_markup.encode("utf-8")).hexdigest()
        cached = self._svg_cache.get(key)
        if cached is not None:
            return cached
        doc = SvgDocument.from_markup(svg_markup)
        self._svg_cache[key] = doc
        return doc

    def _bitmap_cache_enabled(self) -> bool:
        if self._bitmap_cache_enabled_override is not None:
            return bool(self._bitmap_cache_enabled_override)
        return bool(self._bitmap_cache_enabled_default)

    @staticmethod
    def _command_is_pixel_aligned(*values: float) -> bool:
        for raw in values:
            if abs(float(raw) - round(float(raw))) > 1e-6:
                return False
        return True

    def _bitmap_cacheable(self, bitmap: torch.Tensor) -> bool:
        if bitmap.ndim != 3:
            return False
        h = int(bitmap.shape[0])
        w = int(bitmap.shape[1])
        if h <= 0 or w <= 0:
            return False
        return int(h * w) <= int(self._bitmap_cache_max_pixels)

    def _cache_put(self, cache: OrderedDict[tuple[Any, ...], torch.Tensor], key: tuple[Any, ...], value: torch.Tensor) -> None:
        cache[key] = value.clone()
        cache.move_to_end(key)
        while len(cache) > int(self._bitmap_cache_max_entries):
            cache.popitem(last=False)

    def _svg_bitmap_key(self, command: SVGRenderCommand) -> tuple[Any, ...]:
        return (
            hashlib.sha256(command.svg_markup.encode("utf-8")).hexdigest(),
            int(round(float(command.width))),
            int(round(float(command.height))),
            int(round(float(command.opacity) * 1000)),
        )

    def _text_bitmap_key(self, command: TextRenderCommand) -> tuple[Any, ...]:
        return (
            command.text,
            command.font.family,
            str(command.font.file_path or ""),
            int(command.font.weight),
            str(command.font.slant),
            int(round(float(command.font_size_px) * 100)),
            command.appearance.color_hex,
            int(round(float(command.appearance.opacity) * 1000)),
            int(round(float(command.appearance.letter_spacing_px) * 100)),
            int(round(float(command.appearance.line_height_multiplier) * 100)),
            int(round(float(command.max_width_px) * 100)) if command.max_width_px is not None else None,
        )

    def _rasterize_svg_bitmap(self, command: SVGRenderCommand) -> torch.Tensor:
        width = max(1, int(round(float(command.width))))
        height = max(1, int(round(float(command.height))))
        frame = torch.zeros((height, width, 4), dtype=torch.uint8)
        grid_x = torch.arange(width, dtype=torch.float32).unsqueeze(0).expand(height, width)
        grid_y = torch.arange(height, dtype=torch.float32).unsqueeze(1).expand(height, width)
        saved_frame = self._frame
        saved_grid_x = self._grid_x
        saved_grid_y = self._grid_y
        self._frame = frame
        self._grid_x = grid_x
        self._grid_y = grid_y
        try:
            doc = self._doc_for_markup(command.svg_markup)
            local_cmd = SVGRenderCommand(
                component_id=command.component_id,
                svg_markup=command.svg_markup,
                x=0.0,
                y=0.0,
                width=float(command.width),
                height=float(command.height),
                frame=command.frame,
                opacity=float(command.opacity),
            )
            self._render_svg_document(doc, local_cmd)
            return frame
        finally:
            self._frame = saved_frame
            self._grid_x = saved_grid_x
            self._grid_y = saved_grid_y

    def _rasterize_text_bitmap(self, command: TextRenderCommand) -> torch.Tensor:
        atlas = self._ensure_atlas(command.font, command.font_size_px)
        lines = self._wrap_lines(
            command.text,
            atlas,
            max_width_px=command.max_width_px,
            letter_spacing_px=command.appearance.letter_spacing_px,
        )
        widths = [self._line_advance(line, atlas, command.appearance.letter_spacing_px) for line in lines]
        line_h = max(atlas.line_height, command.font_size_px * command.appearance.line_height_multiplier)
        width = max(1, int(math.ceil(max(widths) if widths else 1.0)))
        height = max(1, int(math.ceil(max(command.font_size_px, float(len(lines)) * line_h))))
        frame = torch.zeros((height, width, 4), dtype=torch.uint8)
        saved_frame = self._frame
        self._frame = frame
        try:
            color = _parse_rgba_u8(command.appearance.color_hex, command.appearance.opacity)
            for i, line in enumerate(lines):
                self._draw_line(
                    line,
                    atlas,
                    x=0.0,
                    top_y=float(i) * float(line_h),
                    color=color,
                    letter_spacing_px=command.appearance.letter_spacing_px,
                )
            return frame
        finally:
            self._frame = saved_frame

    def _blend_bitmap(self, bitmap: torch.Tensor, *, x: int, y: int) -> None:
        if self._frame is None:
            return
        h = int(bitmap.shape[0])
        w = int(bitmap.shape[1])
        if h <= 0 or w <= 0:
            return
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(int(self._frame.shape[1]), int(x + w))
        y1 = min(int(self._frame.shape[0]), int(y + h))
        if x1 <= x0 or y1 <= y0:
            return
        sx0 = x0 - int(x)
        sy0 = y0 - int(y)
        sx1 = sx0 + (x1 - x0)
        sy1 = sy0 + (y1 - y0)
        src = bitmap[sy0:sy1, sx0:sx1].to(torch.float32)
        dst = self._frame[y0:y1, x0:x1].to(torch.float32)
        src_alpha = (src[:, :, 3:4] / 255.0).clamp(0.0, 1.0)
        dst_alpha = (dst[:, :, 3:4] / 255.0).clamp(0.0, 1.0)
        out_alpha = src_alpha + dst_alpha * (1.0 - src_alpha)
        out_rgb = src[:, :, 0:3] * src_alpha + dst[:, :, 0:3] * (1.0 - src_alpha)
        self._frame[y0:y1, x0:x1, 0:3] = torch.clamp(out_rgb, 0, 255).to(torch.uint8)
        self._frame[y0:y1, x0:x1, 3:4] = torch.clamp(out_alpha * 255.0, 0, 255).to(torch.uint8)

    def _ensure_atlas(self, font: FontSpec, size_px: float) -> _FontAtlas:
        if size_px <= 0:
            raise ValueError("font size must be > 0")
        font_path = _resolve_font_path(font)
        key = (font_path, int(round(size_px * 100)))
        cached = self._font_atlas_cache.get(key)
        if cached is not None:
            return cached
        loaded_font = _load_font(font_path, size_px)
        ascent, descent = _font_metrics(loaded_font, size_px)
        line_h = max(size_px, float(ascent + descent))
        atlas = _FontAtlas(
            key=key,
            font=loaded_font,
            size_px=size_px,
            ascent=float(ascent),
            descent=float(descent),
            line_height=line_h,
        )
        self._font_atlas_cache[key] = atlas
        return atlas

    def _ensure_glyph(self, atlas: _FontAtlas, ch: str) -> _GlyphBitmap:
        cached = atlas.glyphs.get(ch)
        if cached is not None:
            return cached
        glyph = _rasterize_glyph(atlas.font, atlas.size_px, ch)
        atlas.glyphs[ch] = glyph
        return glyph

    def _line_advance(self, line: str, atlas: _FontAtlas, letter_spacing_px: float) -> float:
        spacing = float(letter_spacing_px)
        if line == "":
            return 0.0
        total = 0.0
        for i, ch in enumerate(line):
            glyph = self._ensure_glyph(atlas, ch)
            total += glyph.advance
            if i > 0:
                total += spacing
        return total

    def _wrap_lines(
        self,
        text: str,
        atlas: _FontAtlas,
        *,
        max_width_px: float | None,
        letter_spacing_px: float,
    ) -> list[str]:
        if text == "":
            return [""]
        out: list[str] = []
        for raw_line in text.splitlines() or [""]:
            if max_width_px is None:
                out.append(raw_line)
                continue
            words = raw_line.split(" ")
            if not words:
                out.append("")
                continue
            current = words[0]
            for word in words[1:]:
                candidate = f"{current} {word}"
                if self._line_advance(candidate, atlas, letter_spacing_px) <= max_width_px:
                    current = candidate
                else:
                    out.append(current)
                    current = word
            out.append(current)
        return out or [""]

    def _draw_line(
        self,
        line: str,
        atlas: _FontAtlas,
        *,
        x: float,
        top_y: float,
        color: tuple[int, int, int, int],
        letter_spacing_px: float,
    ) -> None:
        cursor = float(x)
        spacing = float(letter_spacing_px)
        for i, ch in enumerate(line):
            glyph = self._ensure_glyph(atlas, ch)
            gx = int(round(cursor + glyph.x_offset))
            gy = int(round(top_y + glyph.y_offset))
            self._blend_alpha_mask(glyph.alpha_mask, x=gx, y=gy, color=color)
            cursor += glyph.advance
            if i > 0:
                cursor += spacing

    def _render_svg_document(self, doc: SvgDocument, command) -> None:
        if self._frame is None or self._grid_x is None or self._grid_y is None:
            return
        vb_x, vb_y, vb_w, vb_h = doc.viewbox
        if vb_w == 0 or vb_h == 0:
            return
        sx = float(command.width) / float(vb_w)
        sy = float(command.height) / float(vb_h)
        x_off = float(command.x)
        y_off = float(command.y)

        for rect in doc.rects:
            if rect.fill is not None:
                x0 = int(round(x_off + (rect.x - vb_x) * sx))
                y0 = int(round(y_off + (rect.y - vb_y) * sy))
                w = max(0, int(round(rect.width * sx)))
                h = max(0, int(round(rect.height * sy)))
                self._blend_rect(x0, y0, w, h, _apply_opacity_u8(rect.fill, command.opacity))
            if rect.stroke is not None and rect.stroke_width > 0:
                sw = max(1, int(round(rect.stroke_width * (abs(sx) + abs(sy)) * 0.5)))
                x0 = int(round(x_off + (rect.x - vb_x) * sx))
                y0 = int(round(y_off + (rect.y - vb_y) * sy))
                w = max(0, int(round(rect.width * sx)))
                h = max(0, int(round(rect.height * sy)))
                stroke = _apply_opacity_u8(rect.stroke, command.opacity)
                self._blend_rect(x0, y0, w, sw, stroke)
                self._blend_rect(x0, y0 + h - sw, w, sw, stroke)
                self._blend_rect(x0, y0, sw, h, stroke)
                self._blend_rect(x0 + w - sw, y0, sw, h, stroke)

        for circle in doc.circles:
            if circle.fill is None and circle.stroke is None:
                continue
            cx = x_off + (circle.cx - vb_x) * sx
            cy = y_off + (circle.cy - vb_y) * sy
            r = max(0.0, float(circle.r) * (abs(sx) + abs(sy)) * 0.5)
            if r <= 0:
                continue
            x0 = int(max(0, int(cx - r - 1)))
            y0 = int(max(0, int(cy - r - 1)))
            x1 = int(min(self._frame.shape[1], int(cx + r + 2)))
            y1 = int(min(self._frame.shape[0], int(cy + r + 2)))
            if x1 <= x0 or y1 <= y0:
                continue
            gx = self._grid_x[y0:y1, x0:x1]
            gy = self._grid_y[y0:y1, x0:x1]
            dist_sq = (gx - cx) ** 2 + (gy - cy) ** 2
            if circle.fill is not None:
                mask = dist_sq <= (r * r)
                self._blend_mask(mask, x=x0, y=y0, color=_apply_opacity_u8(circle.fill, command.opacity))
            if circle.stroke is not None and circle.stroke_width > 0:
                sw = max(1.0, float(circle.stroke_width) * (abs(sx) + abs(sy)) * 0.5)
                inner = max(0.0, r - sw)
                mask = (dist_sq <= (r * r)) & (dist_sq >= (inner * inner))
                self._blend_mask(mask, x=x0, y=y0, color=_apply_opacity_u8(circle.stroke, command.opacity))

    def _blend_rect(self, x: int, y: int, w: int, h: int, color: tuple[int, int, int, int]) -> None:
        if self._frame is None or w <= 0 or h <= 0:
            return
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self._frame.shape[1], x + w)
        y1 = min(self._frame.shape[0], y + h)
        if x1 <= x0 or y1 <= y0:
            return
        alpha = color[3] / 255.0
        if alpha <= 0:
            return
        dst = self._frame[y0:y1, x0:x1, :3].to(torch.float32)
        src = torch.tensor(color[:3], dtype=torch.float32).view(1, 1, 3)
        out = torch.clamp(src * alpha + dst * (1.0 - alpha), 0, 255).to(torch.uint8)
        self._frame[y0:y1, x0:x1, :3] = out
        self._frame[y0:y1, x0:x1, 3] = 255

    def _blend_mask(self, mask: torch.Tensor, *, x: int, y: int, color: tuple[int, int, int, int]) -> None:
        if self._frame is None:
            return
        h, w = mask.shape
        if h <= 0 or w <= 0:
            return
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self._frame.shape[1], x + w)
        y1 = min(self._frame.shape[0], y + h)
        if x1 <= x0 or y1 <= y0:
            return
        sx0 = x0 - x
        sy0 = y0 - y
        sx1 = sx0 + (x1 - x0)
        sy1 = sy0 + (y1 - y0)
        patch_mask = mask[sy0:sy1, sx0:sx1]
        if not bool(patch_mask.any()):
            return
        alpha = color[3] / 255.0
        if alpha <= 0:
            return
        dst = self._frame[y0:y1, x0:x1, :3].to(torch.float32)
        src = torch.tensor(color[:3], dtype=torch.float32).view(1, 1, 3)
        blended = torch.clamp(src * alpha + dst * (1.0 - alpha), 0, 255).to(torch.uint8)
        self._frame[y0:y1, x0:x1, :3] = torch.where(
            patch_mask.unsqueeze(-1),
            blended,
            self._frame[y0:y1, x0:x1, :3],
        )
        self._frame[y0:y1, x0:x1, 3] = 255

    def _blend_alpha_mask(self, mask: np.ndarray, *, x: int, y: int, color: tuple[int, int, int, int]) -> None:
        if self._frame is None:
            return
        h, w = mask.shape
        if h <= 0 or w <= 0:
            return
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self._frame.shape[1], x + w)
        y1 = min(self._frame.shape[0], y + h)
        if x1 <= x0 or y1 <= y0:
            return
        sx0 = x0 - x
        sy0 = y0 - y
        sx1 = sx0 + (x1 - x0)
        sy1 = sy0 + (y1 - y0)

        cov = mask[sy0:sy1, sx0:sx1].astype(np.float32) / 255.0
        src_alpha = cov * (color[3] / 255.0)
        if not np.any(src_alpha > 0):
            return

        patch = self._frame[y0:y1, x0:x1]
        dst_rgb = patch[:, :, :3].to(torch.float32).cpu().numpy()
        dst_alpha = patch[:, :, 3].to(torch.float32).cpu().numpy() / 255.0
        src_rgb = np.asarray(color[:3], dtype=np.float32).reshape(1, 1, 3)

        out_alpha = src_alpha + dst_alpha * (1.0 - src_alpha)
        out_rgb_num = src_rgb * src_alpha[:, :, None] + dst_rgb * dst_alpha[:, :, None] * (1.0 - src_alpha[:, :, None])
        safe = np.where(out_alpha > 1e-6, out_alpha, 1.0)
        out_rgb = out_rgb_num / safe[:, :, None]

        patch[:, :, :3] = torch.from_numpy(np.clip(out_rgb, 0, 255).astype(np.uint8))
        patch[:, :, 3] = torch.from_numpy(np.clip(out_alpha * 255.0, 0, 255).astype(np.uint8))


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _env_int(name: str, default: int, min_value: int, max_value: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return int(default)
    try:
        value = int(raw)
    except ValueError:
        return int(default)
    return max(int(min_value), min(int(max_value), int(value)))


def _resolve_font_path(font: FontSpec) -> str:
    if font.file_path:
        return str(Path(font.file_path).resolve())
    return _resolve_system_font_path(font.family)


@lru_cache(maxsize=64)
def _load_font(font_path: str, size_px: float) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = max(1, int(round(size_px)))
    try:
        return ImageFont.truetype(font_path, size=size)
    except Exception:
        return ImageFont.load_default()


def _font_metrics(font: ImageFont.FreeTypeFont | ImageFont.ImageFont, size_px: float) -> tuple[int, int]:
    try:
        ascent, descent = font.getmetrics()
        return int(max(1, ascent)), int(max(0, descent))
    except Exception:
        return int(max(1, size_px * 0.8)), int(max(0, size_px * 0.2))


def _rasterize_glyph(font: ImageFont.FreeTypeFont | ImageFont.ImageFont, size_px: float, ch: str) -> _GlyphBitmap:
    if ch == "":
        return _GlyphBitmap(alpha_mask=np.zeros((1, 1), dtype=np.uint8), x_offset=0, y_offset=0, advance=0.0)
    left, top, right, bottom = font.getbbox(ch)
    width = max(1, int(right - left))
    height = max(1, int(bottom - top))
    image = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(image)
    draw.text((-left, -top), ch, fill=255, font=font)
    mask = np.asarray(image, dtype=np.uint8)

    try:
        advance = float(font.getlength(ch))
    except Exception:
        advance = float(max(1, right - left))
    if ch == " ":
        advance = max(advance, size_px * 0.33)
    return _GlyphBitmap(alpha_mask=mask, x_offset=int(left), y_offset=int(top), advance=max(1.0, advance))


def _resolve_system_font_path(family: str) -> str:
    wanted = (family.strip() or "Comic Mono").lower().replace(" ", "")
    patterns = (
        wanted,
        "comicmono",
        "menlo",
        "monaco",
        "couriernew",
        "courier",
        "dejavusansmono",
    )
    font_dirs = (
        Path.home() / "Library/Fonts",
        Path("/Library/Fonts"),
        Path("/System/Library/Fonts"),
        Path("/System/Library/Fonts/Supplemental"),
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
    )
    candidates: list[Path] = []
    for base in font_dirs:
        if not base.exists():
            continue
        for ext in ("*.ttf", "*.otf", "*.ttc"):
            candidates.extend(base.rglob(ext))
    for pattern in patterns:
        for path in candidates:
            name = path.name.lower().replace(" ", "")
            stem = path.stem.lower().replace(" ", "")
            if pattern in name or pattern in stem:
                return str(path)
    if candidates:
        return str(candidates[0])
    return ""


def _parse_rgba_u8(hex_color: str, opacity: float) -> tuple[int, int, int, int]:
    value = hex_color.strip()
    if not value.startswith("#"):
        raise ValueError(f"color must be #RRGGBB or #RRGGBBAA, got `{hex_color}`")
    raw = value[1:]
    if len(raw) == 6:
        r = int(raw[0:2], 16)
        g = int(raw[2:4], 16)
        b = int(raw[4:6], 16)
        a = 255
    elif len(raw) == 8:
        r = int(raw[0:2], 16)
        g = int(raw[2:4], 16)
        b = int(raw[4:6], 16)
        a = int(raw[6:8], 16)
    else:
        raise ValueError(f"color must be #RRGGBB or #RRGGBBAA, got `{hex_color}`")
    alpha = int(max(0.0, min(1.0, (a / 255.0) * opacity)) * 255.0)
    return (r, g, b, alpha)


def _apply_opacity_u8(color: tuple[int, int, int, int], opacity: float) -> tuple[int, int, int, int]:
    r, g, b, a = color
    alpha = int(max(0.0, min(1.0, (a / 255.0) * opacity)) * 255.0)
    return (r, g, b, alpha)
