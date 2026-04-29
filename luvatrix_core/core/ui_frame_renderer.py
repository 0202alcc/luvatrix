from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import math
import os
from pathlib import Path
import sys
from typing import Any

try:
    import torch
    import torch.nn.functional as F
    _HAS_TORCH = True
except ImportError:
    torch = None  # type: ignore[assignment]
    F = None  # type: ignore[assignment]
    _HAS_TORCH = False

from luvatrix_core import accel

np = getattr(accel, "_np", None)
if np is None and _HAS_TORCH:
    try:
        import numpy as np  # type: ignore[no-redef]
    except ImportError:
        np = None
_HAS_NUMPY = np is not None

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
except ImportError:
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    ImageFont = None  # type: ignore[assignment]
    _HAS_PIL = False

from luvatrix_ui.component_schema import DisplayableArea
from luvatrix_ui.controls.stained_glass_button import StainedGlassButtonRenderBatch, StainedGlassButtonRenderCommand
from luvatrix_ui.controls.svg_renderer import SVGRenderBatch, SVGRenderCommand
from luvatrix_ui.text.renderer import FontSpec, TextAppearance, TextLayoutMetrics, TextMeasureRequest, TextRenderBatch, TextRenderCommand

from luvatrix_core.render.svg import SvgDocument

@dataclass(frozen=True)
class _GlyphBitmap:
    alpha_mask: object
    x_offset: int
    y_offset: int
    advance: float


@dataclass
class _FontAtlas:
    key: tuple[str, int]
    font: object
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
    _frame_buffer: object | None = None
    _frame_buffer_shape: tuple[int, int, int] | None = None
    _grid_shape: tuple[int, int] | None = None
    _scale_x: float = 1.0
    _scale_y: float = 1.0
    _svg_cache: dict[str, SvgDocument] = field(default_factory=dict)
    _font_atlas_cache: dict[tuple[str, int], _FontAtlas] = field(default_factory=dict)
    _bitmap_cache_enabled_default: bool = field(default_factory=lambda: _env_flag("LUVATRIX_SCROLL_BITMAP_CACHE_ENABLED", False))
    _bitmap_cache_enabled_override: bool | None = None
    _bitmap_cache_max_entries: int = field(default_factory=lambda: _env_int("LUVATRIX_SCROLL_BITMAP_CACHE_MAX_ENTRIES", 128, 1, 4096))
    _bitmap_cache_max_pixels: int = field(default_factory=lambda: _env_int("LUVATRIX_SCROLL_BITMAP_CACHE_MAX_PIXELS", 2_000_000, 4096, 16_000_000))
    _svg_bitmap_cache: OrderedDict[tuple[Any, ...], torch.Tensor] = field(default_factory=OrderedDict)
    _text_bitmap_cache: OrderedDict[tuple[Any, ...], torch.Tensor] = field(default_factory=OrderedDict)
    _stained_glass_backdrop_cache: OrderedDict[tuple[Any, ...], tuple[str, torch.Tensor]] = field(default_factory=OrderedDict)
    _stained_glass_cache_max_entries: int = field(
        default_factory=lambda: _env_int("LUVATRIX_STAINED_GLASS_CACHE_MAX_ENTRIES", 64, 1, 1024)
    )
    _bitmap_cache_hits: int = 0
    _bitmap_cache_misses: int = 0
    _stained_glass_cache_hits: int = 0
    _stained_glass_cache_misses: int = 0
    _last_font_source: str = "uninitialized"

    def begin_frame(self, display: DisplayableArea, clear_color: tuple[int, int, int, int]) -> None:
        self._display = display
        width = int(round(display.viewport_width_px or display.content_width_px))
        height = int(round(display.viewport_height_px or display.content_height_px))
        if width <= 0 or height <= 0:
            raise ValueError("frame dimensions must be > 0")
        self._scale_x = float(width) / max(1.0, float(display.content_width_px))
        self._scale_y = float(height) / max(1.0, float(display.content_height_px))
        frame_shape = (height, width, 4)
        if self._frame_buffer is None or self._frame_buffer_shape != frame_shape:
            self._frame_buffer = accel.zeros(frame_shape)
            self._frame_buffer_shape = frame_shape
        self._frame = self._frame_buffer
        self._frame[:, :, 0] = clear_color[0]
        self._frame[:, :, 1] = clear_color[1]
        self._frame[:, :, 2] = clear_color[2]
        self._frame[:, :, 3] = clear_color[3]
        grid_shape = (height, width)
        if self._grid_shape != grid_shape:
            if _HAS_TORCH:
                self._grid_x = torch.arange(width, dtype=torch.float32).unsqueeze(0).expand(height, width)
                self._grid_y = torch.arange(height, dtype=torch.float32).unsqueeze(1).expand(height, width)
            elif _HAS_NUMPY:
                self._grid_x = np.broadcast_to(np.arange(width, dtype=np.float32).reshape(1, width), (height, width))
                self._grid_y = np.broadcast_to(np.arange(height, dtype=np.float32).reshape(height, 1), (height, width))
            else:
                self._grid_x = None
                self._grid_y = None
            self._grid_shape = grid_shape
        self._bitmap_cache_hits = 0
        self._bitmap_cache_misses = 0
        self._stained_glass_cache_hits = 0
        self._stained_glass_cache_misses = 0

    def set_bitmap_cache_enabled(self, enabled: bool) -> None:
        self._bitmap_cache_enabled_override = bool(enabled)

    def consume_bitmap_cache_stats(self) -> dict[str, int | bool]:
        return {
            "enabled": bool(self._bitmap_cache_enabled()),
            "hits": int(self._bitmap_cache_hits),
            "misses": int(self._bitmap_cache_misses),
            "entry_count": int(len(self._svg_bitmap_cache) + len(self._text_bitmap_cache)),
        }

    def consume_stained_glass_cache_stats(self) -> dict[str, int]:
        return {
            "hits": int(self._stained_glass_cache_hits),
            "misses": int(self._stained_glass_cache_misses),
            "entry_count": int(len(self._stained_glass_backdrop_cache)),
        }

    def diagnostics(self) -> dict[str, object]:
        return {
            "torch": bool(_HAS_TORCH),
            "numpy": bool(_HAS_NUMPY),
            "pil": bool(_HAS_PIL),
            "accel": accel.BACKEND,
            "font_source": self._last_font_source,
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
            command = self._scale_text_command(command)
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
                    font_weight=int(command.font.weight),
                )

    def draw_svg_batch(self, batch: SVGRenderBatch) -> None:
        if self._frame is None or self._grid_x is None or self._grid_y is None:
            if self._frame is None:
                raise RuntimeError("begin_frame must be called before draw_svg_batch")
            return
        for command in batch.commands:
            command = self._scale_svg_command(command)
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

    def draw_stained_glass_button_batch(self, batch: StainedGlassButtonRenderBatch) -> None:
        if self._frame is None:
            raise RuntimeError("begin_frame must be called before draw_stained_glass_button_batch")
        for command in batch.commands:
            self._render_stained_glass_button(self._scale_stained_glass_button_command(command))

    def end_frame(self) -> torch.Tensor:
        if self._frame is None:
            raise RuntimeError("begin_frame must be called before end_frame")
        out = accel.clone(self._frame)
        self._display = None
        self._frame = None
        self._scale_x = 1.0
        self._scale_y = 1.0
        return out

    def _scale_text_command(self, command: TextRenderCommand) -> TextRenderCommand:
        sx = float(self._scale_x)
        sy = float(self._scale_y)
        if abs(sx - 1.0) <= 1e-9 and abs(sy - 1.0) <= 1e-9:
            return command
        return TextRenderCommand(
            component_id=command.component_id,
            text=command.text,
            x=float(command.x) * sx,
            y=float(command.y) * sy,
            frame=command.frame,
            font=command.font,
            font_size_px=float(command.font_size_px) * sy,
            appearance=TextAppearance(
                color_hex=command.appearance.color_hex,
                opacity=command.appearance.opacity,
                letter_spacing_px=float(command.appearance.letter_spacing_px) * sx,
                line_height_multiplier=command.appearance.line_height_multiplier,
                underline=command.appearance.underline,
                strike=command.appearance.strike,
            ),
            max_width_px=(float(command.max_width_px) * sx if command.max_width_px is not None else None),
        )

    def _scale_svg_command(self, command: SVGRenderCommand) -> SVGRenderCommand:
        sx = float(self._scale_x)
        sy = float(self._scale_y)
        if abs(sx - 1.0) <= 1e-9 and abs(sy - 1.0) <= 1e-9:
            return command
        return SVGRenderCommand(
            component_id=command.component_id,
            svg_markup=command.svg_markup,
            x=float(command.x) * sx,
            y=float(command.y) * sy,
            width=float(command.width) * sx,
            height=float(command.height) * sy,
            frame=command.frame,
            opacity=float(command.opacity),
        )

    def _scale_stained_glass_button_command(
        self,
        command: StainedGlassButtonRenderCommand,
    ) -> StainedGlassButtonRenderCommand:
        sx = float(self._scale_x)
        sy = float(self._scale_y)
        s = (sx + sy) * 0.5
        if abs(sx - 1.0) <= 1e-9 and abs(sy - 1.0) <= 1e-9:
            return command
        return StainedGlassButtonRenderCommand(
            component_id=command.component_id,
            x=float(command.x) * sx,
            y=float(command.y) * sy,
            width=float(command.width) * sx,
            height=float(command.height) * sy,
            frame=command.frame,
            opacity=command.opacity,
            corner_radius_px=float(command.corner_radius_px) * s,
            kernel_size=max(3, int(round(float(command.kernel_size) * s)) | 1),
            sigma_px=float(command.sigma_px) * s,
            convolution_strength=command.convolution_strength,
            scatter_sigma_px=float(command.scatter_sigma_px) * s,
            refract_px=float(command.refract_px) * s,
            refract_calm_radius=command.refract_calm_radius,
            refract_transition=command.refract_transition,
            chromatic_aberration_px=float(command.chromatic_aberration_px) * s,
            tint_delta_rgba=command.tint_delta_rgba,
            color_filter_rgb=command.color_filter_rgb,
            pane_mix=command.pane_mix,
            edge_highlight_alpha=command.edge_highlight_alpha,
            depth_highlight_alpha=command.depth_highlight_alpha,
            depth_shadow_alpha=command.depth_shadow_alpha,
            rim_darken_alpha=command.rim_darken_alpha,
            label=command.label,
            label_color_hex=command.label_color_hex,
            label_font=command.label_font,
            label_font_size_px=float(command.label_font_size_px) * sy,
            backdrop_cache_enabled=command.backdrop_cache_enabled,
            roi_inset_px=float(command.roi_inset_px) * s,
            downsample_factor=command.downsample_factor,
        )

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

    def _bitmap_cacheable(self, bitmap: object) -> bool:
        if bitmap.ndim != 3:
            return False
        h = int(bitmap.shape[0])
        w = int(bitmap.shape[1])
        if h <= 0 or w <= 0:
            return False
        return int(h * w) <= int(self._bitmap_cache_max_pixels)

    def _cache_put(self, cache: OrderedDict[tuple[Any, ...], object], key: tuple[Any, ...], value: object) -> None:
        cache[key] = accel.clone(value)
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
        frame = accel.zeros((height, width, 4))
        if _HAS_TORCH:
            grid_x = torch.arange(width, dtype=torch.float32).unsqueeze(0).expand(height, width)
            grid_y = torch.arange(height, dtype=torch.float32).unsqueeze(1).expand(height, width)
        elif _HAS_NUMPY:
            grid_x = np.broadcast_to(np.arange(width, dtype=np.float32).reshape(1, width), (height, width))
            grid_y = np.broadcast_to(np.arange(height, dtype=np.float32).reshape(height, 1), (height, width))
        else:
            return frame
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
        frame = accel.zeros((height, width, 4))
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
        if self._frame is None or not _HAS_NUMPY:
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
        src = _as_float32_array(bitmap[sy0:sy1, sx0:sx1])
        dst = _as_float32_array(self._frame[y0:y1, x0:x1])
        src_alpha = np.clip(src[:, :, 3:4] / 255.0, 0.0, 1.0)
        dst_alpha = np.clip(dst[:, :, 3:4] / 255.0, 0.0, 1.0)
        out_alpha = src_alpha + dst_alpha * (1.0 - src_alpha)
        out_rgb = src[:, :, 0:3] * src_alpha + dst[:, :, 0:3] * (1.0 - src_alpha)
        self._frame[y0:y1, x0:x1, 0:3] = _from_uint8_array(np.clip(out_rgb, 0, 255).astype(np.uint8))
        self._frame[y0:y1, x0:x1, 3:4] = _from_uint8_array(np.clip(out_alpha * 255.0, 0, 255).astype(np.uint8))

    def _render_stained_glass_button(self, command: StainedGlassButtonRenderCommand) -> None:
        if self._frame is None:
            return
        if not _HAS_TORCH:
            self._render_button_placeholder(command)
            return
        x = int(round(float(command.x)))
        y = int(round(float(command.y)))
        w = max(1, int(round(float(command.width))))
        h = max(1, int(round(float(command.height))))
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(int(self._frame.shape[1]), x + w)
        y1 = min(int(self._frame.shape[0]), y + h)
        if x1 <= x0 or y1 <= y0:
            return
        roi_inset_px = max(0, int(round(float(command.roi_inset_px))))
        rx0 = min(x1 - 1, max(x0, x0 + roi_inset_px))
        ry0 = min(y1 - 1, max(y0, y0 + roi_inset_px))
        rx1 = max(rx0 + 1, min(x1, x1 - roi_inset_px))
        ry1 = max(ry0 + 1, min(y1, y1 - roi_inset_px))
        backdrop = self._frame[ry0:ry1, rx0:rx1].to(torch.float32)
        patch_h = int(backdrop.shape[0])
        patch_w = int(backdrop.shape[1])
        if patch_h <= 0 or patch_w <= 0:
            return
        base = backdrop[:, :, 0:3].permute(2, 0, 1).unsqueeze(0) / 255.0
        downsample_factor = max(1, int(command.downsample_factor))
        process_base = base
        if downsample_factor > 1 and patch_h >= 4 and patch_w >= 4:
            target_h = max(2, int(round(float(patch_h) / float(downsample_factor))))
            target_w = max(2, int(round(float(patch_w) / float(downsample_factor))))
            process_base = F.interpolate(base, size=(target_h, target_w), mode="bilinear", align_corners=False)
        proc_h = int(process_base.shape[-2])
        proc_w = int(process_base.shape[-1])

        kernel_size = max(3, int(command.kernel_size))
        if kernel_size % 2 == 0:
            kernel_size += 1
        if downsample_factor > 1:
            kernel_size = max(3, int(round(float(kernel_size) / float(downsample_factor))))
            if kernel_size % 2 == 0:
                kernel_size += 1
        sigma = max(0.1, float(command.sigma_px))
        if downsample_factor > 1:
            sigma = max(0.1, sigma / float(downsample_factor))
        edge_proximity = self._rounded_rect_edge_proximity(
            h=proc_h,
            w=proc_w,
            corner_radius_px=float(command.corner_radius_px),
            device=process_base.device,
        )
        calm = max(0.0, min(1.0, float(command.refract_calm_radius)))
        transition = max(0.01, float(command.refract_transition))
        edge_start = calm
        edge_sigmoid_2d = self._edge_sigmoid_gate(edge_proximity, edge_start=edge_start, transition=transition)
        edge_sigmoid = edge_sigmoid_2d.unsqueeze(0).unsqueeze(0)
        edge_kernel_size = max(kernel_size + 2, kernel_size * 3 - 2)
        if edge_kernel_size % 2 == 0:
            edge_kernel_size += 1
        edge_sigma = sigma * (float(edge_kernel_size) / float(kernel_size)) * 1.15
        blur_center = self._gaussian_blur_rgb(process_base, kernel_size=kernel_size, sigma=sigma)
        blur_edge = self._gaussian_blur_rgb(process_base, kernel_size=edge_kernel_size, sigma=edge_sigma)
        blurred = torch.clamp(blur_center * (1.0 - edge_sigmoid) + blur_edge * edge_sigmoid, 0.0, 1.0)

        strength = max(0.0, float(command.convolution_strength))
        inv_center_conv_gain = edge_sigmoid
        scattered = torch.clamp(process_base + (blurred - process_base) * (strength * inv_center_conv_gain), 0.0, 1.0)

        scatter_sigma = max(0.0, float(command.scatter_sigma_px))
        if scatter_sigma > 0.05:
            if downsample_factor > 1:
                scatter_sigma = max(0.05, scatter_sigma / float(downsample_factor))
            scatter_kernel = max(3, int(round(scatter_sigma * 2.0)) * 2 + 1)
            scatter_blur = self._gaussian_blur_rgb(scattered, kernel_size=scatter_kernel, sigma=max(0.1, scatter_sigma))
            edge_mix = torch.clamp(inv_center_conv_gain * 0.9, 0.0, 1.0)
            scattered = torch.clamp(scattered * (1.0 - edge_mix) + scatter_blur * edge_mix, 0.0, 1.0)

        refract_px = float(command.refract_px)
        refract_calm_radius = float(command.refract_calm_radius)
        refract_transition = float(command.refract_transition)
        chroma_px = float(command.chromatic_aberration_px)
        if downsample_factor > 1:
            refract_px = refract_px / float(downsample_factor)
            chroma_px = chroma_px / float(downsample_factor)
        refracted = self._refract_with_aberration(
            scattered,
            refract_px=refract_px,
            refract_calm_radius=refract_calm_radius,
            refract_transition=refract_transition,
            corner_radius_px=float(command.corner_radius_px),
            chroma_px=chroma_px,
        )

        tint = torch.tensor(command.tint_delta_rgba[0:3], dtype=torch.float32).view(1, 3, 1, 1) / 255.0
        refracted = torch.clamp(refracted + tint, 0.0, 1.0)
        filter_rgb = torch.tensor(command.color_filter_rgb, dtype=torch.float32).view(1, 3, 1, 1)
        filtered = torch.clamp(refracted * filter_rgb, 0.0, 1.0)
        pane_mix = max(0.0, min(1.0, float(command.pane_mix)))
        pane = torch.clamp(refracted * (1.0 - pane_mix) + filtered * pane_mix, 0.0, 1.0)
        if downsample_factor > 1 and (proc_h != patch_h or proc_w != patch_w):
            pane = F.interpolate(pane, size=(patch_h, patch_w), mode="bilinear", align_corners=False)

        mask = self._rounded_rect_mask(h=patch_h, w=patch_w, radius=float(command.corner_radius_px))
        alpha = mask * max(0.0, min(1.0, float(command.opacity)))
        _, _, gy = self._radial_and_y_maps(h=patch_h, w=patch_w, device=base.device)
        edge_proximity_full = self._rounded_rect_edge_proximity(
            h=patch_h,
            w=patch_w,
            corner_radius_px=float(command.corner_radius_px),
            device=base.device,
        )

        # Depth cues are restricted to a thin rounded-rect perimeter ring so the interior
        # remains optically clear while edges read as a raised prism.
        depth_edge_gate = self._edge_sigmoid_gate(edge_proximity_full, edge_start=0.955, transition=0.009) * mask
        top_gloss = (
            depth_edge_gate
            * torch.pow(torch.clamp(1.0 - gy, 0.0, 1.0), 1.35)
            * max(0.0, float(command.depth_highlight_alpha))
        )
        bottom_shadow = (
            depth_edge_gate
            * torch.pow(torch.clamp(gy, 0.0, 1.0), 1.2)
            * max(0.0, float(command.depth_shadow_alpha))
        )
        rim_shadow = depth_edge_gate * max(0.0, float(command.rim_darken_alpha))
        depth_dark = torch.clamp(bottom_shadow * 0.55 + rim_shadow * 0.9, 0.0, 0.9)
        pane = torch.clamp(pane * (1.0 - depth_dark.unsqueeze(0).unsqueeze(0)), 0.0, 1.0)
        gloss_tint = torch.tensor([1.0, 0.92, 0.9], dtype=torch.float32, device=base.device).view(1, 3, 1, 1)
        pane = torch.clamp(pane + gloss_tint * top_gloss.unsqueeze(0).unsqueeze(0), 0.0, 1.0)

        dst = backdrop[:, :, 0:3] / 255.0
        src = pane.squeeze(0).permute(1, 2, 0)
        out_rgb = src * alpha.unsqueeze(-1) + dst * (1.0 - alpha.unsqueeze(-1))
        out_rgba = torch.zeros_like(backdrop)
        out_rgba[:, :, 0:3] = torch.clamp(out_rgb * 255.0, 0.0, 255.0)
        out_rgba[:, :, 3] = backdrop[:, :, 3]

        edge_alpha = max(0.0, min(1.0, float(command.edge_highlight_alpha)))
        if edge_alpha > 0.0:
            edge = self._edge_mask(mask)
            edge_color = torch.tensor([1.0, 1.0, 1.0], dtype=torch.float32).view(1, 1, 3)
            out_patch = out_rgba[:, :, 0:3] / 255.0
            out_patch = edge_color * (edge * edge_alpha).unsqueeze(-1) + out_patch * (1.0 - (edge * edge_alpha).unsqueeze(-1))
            out_rgba[:, :, 0:3] = torch.clamp(out_patch * 255.0, 0.0, 255.0)

        out_patch = out_rgba.to(torch.uint8)
        if bool(command.backdrop_cache_enabled):
            cache_key = (
                str(command.component_id),
                int(rx0),
                int(ry0),
                int(rx1),
                int(ry1),
                int(downsample_factor),
                int(kernel_size),
                round(float(command.sigma_px), 4),
                round(float(command.convolution_strength), 4),
                round(float(command.scatter_sigma_px), 4),
                round(float(command.refract_px), 4),
                round(float(command.refract_calm_radius), 4),
                round(float(command.refract_transition), 4),
                round(float(command.chromatic_aberration_px), 4),
                tuple(round(float(v), 4) for v in command.tint_delta_rgba),
                tuple(round(float(v), 4) for v in command.color_filter_rgb),
                round(float(command.pane_mix), 4),
                round(float(command.edge_highlight_alpha), 4),
                round(float(command.depth_highlight_alpha), 4),
                round(float(command.depth_shadow_alpha), 4),
                round(float(command.rim_darken_alpha), 4),
                round(float(command.corner_radius_px), 4),
                round(float(command.opacity), 4),
            )
            backdrop_digest = hashlib.sha256(backdrop.to(torch.uint8).contiguous().cpu().numpy().tobytes()).hexdigest()
            cached = self._stained_glass_backdrop_cache.get(cache_key)
            if cached is not None and cached[0] == backdrop_digest:
                self._stained_glass_cache_hits += 1
                self._stained_glass_backdrop_cache.move_to_end(cache_key)
                out_patch = cached[1].clone()
            else:
                self._stained_glass_cache_misses += 1
                self._stained_glass_backdrop_cache[cache_key] = (backdrop_digest, out_patch.clone())
                self._stained_glass_backdrop_cache.move_to_end(cache_key)
                while len(self._stained_glass_backdrop_cache) > int(self._stained_glass_cache_max_entries):
                    self._stained_glass_backdrop_cache.popitem(last=False)

        self._frame[ry0:ry1, rx0:rx1] = out_patch

        label = str(command.label)
        if label.strip():
            self._draw_button_label(
                text=label,
                x=float(rx0),
                y=float(ry0),
                w=float(patch_w),
                h=float(patch_h),
                color_hex=str(command.label_color_hex),
                font=command.label_font,
                font_size_px=float(command.label_font_size_px),
            )

    def _gaussian_blur_rgb(self, rgb_bchw: torch.Tensor, *, kernel_size: int, sigma: float) -> torch.Tensor:
        kernel = _gaussian_kernel_1d(kernel_size, sigma, device=rgb_bchw.device)
        kx = kernel.view(1, 1, 1, kernel_size).repeat(3, 1, 1, 1)
        ky = kernel.view(1, 1, kernel_size, 1).repeat(3, 1, 1, 1)
        pad_x = kernel_size // 2
        pad_mode_x = "reflect" if int(rgb_bchw.shape[-1]) > pad_x else "replicate"
        padded_x = F.pad(rgb_bchw, (pad_x, pad_x, 0, 0), mode=pad_mode_x)
        blur_x = F.conv2d(padded_x, kx, groups=3)
        pad_y = kernel_size // 2
        pad_mode_y = "reflect" if int(blur_x.shape[-2]) > pad_y else "replicate"
        padded_y = F.pad(blur_x, (0, 0, pad_y, pad_y), mode=pad_mode_y)
        return F.conv2d(padded_y, ky, groups=3)

    def _refract_with_aberration(
        self,
        rgb_bchw: torch.Tensor,
        *,
        refract_px: float,
        refract_calm_radius: float,
        refract_transition: float,
        corner_radius_px: float,
        chroma_px: float,
    ) -> torch.Tensor:
        b, c, h, w = rgb_bchw.shape
        _ = b
        if h <= 1 or w <= 1:
            return rgb_bchw
        gy = torch.linspace(0.0, 1.0, h, dtype=torch.float32, device=rgb_bchw.device).view(h, 1).expand(h, w)
        gx = torch.linspace(0.0, 1.0, w, dtype=torch.float32, device=rgb_bchw.device).view(1, w).expand(h, w)
        # Shape-aware sigmoid: uses rounded-rect edge distance (not circular radius).
        edge_proximity = self._rounded_rect_edge_proximity(
            h=h,
            w=w,
            corner_radius_px=corner_radius_px,
            device=rgb_bchw.device,
        )
        calm = max(0.0, min(1.0, float(refract_calm_radius)))
        transition = max(0.01, float(refract_transition))
        edge_start = calm
        edge_sigmoid = self._edge_sigmoid_gate(edge_proximity, edge_start=edge_start, transition=transition)
        center_floor = 0.0
        refract_gain = center_floor + (1.0 - center_floor) * edge_sigmoid
        dx = torch.sin(gy * math.pi * 2.0) * refract_px * refract_gain / max(float(w), 1.0)
        dy = torch.cos(gx * math.pi * 2.0) * refract_px * 0.65 * refract_gain / max(float(h), 1.0)
        grid_x = (gx + dx) * 2.0 - 1.0
        grid_y = (gy + dy) * 2.0 - 1.0
        grid = torch.stack((grid_x, grid_y), dim=-1).unsqueeze(0)
        sampled = F.grid_sample(rgb_bchw, grid, mode="bilinear", padding_mode="border", align_corners=True)
        if abs(chroma_px) <= 1e-6:
            return sampled
        chroma_dx = chroma_px / max(float(w), 1.0)
        grid_r = torch.stack((torch.clamp(grid_x + chroma_dx, -1.0, 1.0), grid_y), dim=-1).unsqueeze(0)
        grid_b = torch.stack((torch.clamp(grid_x - chroma_dx, -1.0, 1.0), grid_y), dim=-1).unsqueeze(0)
        red = F.grid_sample(rgb_bchw[:, 0:1], grid_r, mode="bilinear", padding_mode="border", align_corners=True)
        blue = F.grid_sample(rgb_bchw[:, 2:3], grid_b, mode="bilinear", padding_mode="border", align_corners=True)
        sampled[:, 0:1] = red
        sampled[:, 2:3] = blue
        return sampled

    @staticmethod
    def _radial_weight_maps(*, h: int, w: int, device: torch.device) -> tuple[torch.Tensor, torch.Tensor]:
        gy = torch.linspace(0.0, 1.0, h, dtype=torch.float32, device=device).view(h, 1).expand(h, w)
        gx = torch.linspace(0.0, 1.0, w, dtype=torch.float32, device=device).view(1, w).expand(h, w)
        nx = (gx - 0.5) * 2.0
        ny = (gy - 0.5) * 2.0
        radius = torch.sqrt(torch.clamp(nx * nx + ny * ny, 0.0, 1.0))
        center_gain_2d = torch.pow(torch.clamp(1.0 - radius, 0.0, 1.0), 1.35)
        edge_gain_2d = 1.0 - center_gain_2d
        return (center_gain_2d.unsqueeze(0).unsqueeze(0), edge_gain_2d.unsqueeze(0).unsqueeze(0))

    @staticmethod
    def _rounded_rect_edge_proximity(*, h: int, w: int, corner_radius_px: float, device: torch.device) -> torch.Tensor:
        yy = torch.arange(h, dtype=torch.float32, device=device).view(h, 1).expand(h, w)
        xx = torch.arange(w, dtype=torch.float32, device=device).view(1, w).expand(h, w)
        cx = (float(w) - 1.0) * 0.5
        cy = (float(h) - 1.0) * 0.5
        px = torch.abs(xx - cx)
        py = torch.abs(yy - cy)
        hx = max(1e-3, float(w) * 0.5)
        hy = max(1e-3, float(h) * 0.5)
        r = max(0.0, min(float(corner_radius_px), min(hx, hy)))
        bx = max(1e-3, hx - r)
        by = max(1e-3, hy - r)
        qx = torch.clamp(px - bx, min=0.0)
        qy = torch.clamp(py - by, min=0.0)
        outside = torch.sqrt(qx * qx + qy * qy)
        inside = torch.minimum(torch.maximum(px - bx, py - by), torch.tensor(0.0, dtype=torch.float32, device=device))
        sdf = outside + inside - r
        inward = torch.clamp(-sdf, min=0.0)
        max_inward = max(1e-3, min(hx, hy))
        inward_norm = torch.clamp(inward / max_inward, 0.0, 1.0)
        return 1.0 - inward_norm

    @staticmethod
    def _edge_sigmoid_gate(edge_proximity: torch.Tensor, *, edge_start: float, transition: float) -> torch.Tensor:
        # Normalized logistic gate:
        # - exactly 0 at interior baseline (edge_proximity=0)
        # - smooth sigmoid rise near edge_start
        # - approaches 1 near outer edge
        t = max(1e-4, float(transition))
        x0 = float(edge_start)
        raw = torch.sigmoid((edge_proximity - x0) / t)
        baseline = 1.0 / (1.0 + math.exp((x0 / t)))
        denom = max(1e-6, 1.0 - baseline)
        gated = torch.clamp((raw - baseline) / denom, 0.0, 1.0)
        return gated

    @staticmethod
    def _radial_and_y_maps(*, h: int, w: int, device: torch.device) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        gy = torch.linspace(0.0, 1.0, h, dtype=torch.float32, device=device).view(h, 1).expand(h, w)
        gx = torch.linspace(0.0, 1.0, w, dtype=torch.float32, device=device).view(1, w).expand(h, w)
        nx = (gx - 0.5) * 2.0
        ny = (gy - 0.5) * 2.0
        radius = torch.sqrt(torch.clamp(nx * nx + ny * ny, 0.0, 1.0))
        center_gain_2d = torch.pow(torch.clamp(1.0 - radius, 0.0, 1.0), 1.35)
        edge_gain_2d = 1.0 - center_gain_2d
        return (center_gain_2d, edge_gain_2d, gy)

    @staticmethod
    def _rounded_rect_mask(*, h: int, w: int, radius: float) -> torch.Tensor:
        r = max(0.0, min(float(radius), min(float(w), float(h)) * 0.5))
        if r <= 0.0:
            return torch.ones((h, w), dtype=torch.float32)
        yy = torch.arange(h, dtype=torch.float32).view(h, 1).expand(h, w)
        xx = torch.arange(w, dtype=torch.float32).view(1, w).expand(h, w)
        mask = torch.ones((h, w), dtype=torch.float32)
        corners = (
            (r - 0.5, r - 0.5),
            (w - r - 0.5, r - 0.5),
            (r - 0.5, h - r - 0.5),
            (w - r - 0.5, h - r - 0.5),
        )
        for cx, cy in corners:
            dx = xx - cx
            dy = yy - cy
            circle = ((dx * dx + dy * dy) <= (r * r)).to(torch.float32)
            region_x = (xx < r) if cx < w * 0.5 else (xx >= w - r)
            region_y = (yy < r) if cy < h * 0.5 else (yy >= h - r)
            corner_region = region_x & region_y
            mask = torch.where(corner_region, circle, mask)
        return mask

    @staticmethod
    def _edge_mask(mask: torch.Tensor) -> torch.Tensor:
        h, w = mask.shape
        if h < 3 or w < 3:
            return torch.zeros_like(mask)
        core = mask[1:-1, 1:-1]
        inner = core * mask[0:-2, 1:-1] * mask[2:, 1:-1] * mask[1:-1, 0:-2] * mask[1:-1, 2:]
        edge = torch.zeros_like(mask)
        edge[1:-1, 1:-1] = torch.clamp(core - inner, 0.0, 1.0)
        return edge

    def _draw_button_label(
        self,
        *,
        text: str,
        x: float,
        y: float,
        w: float,
        h: float,
        color_hex: str,
        font: FontSpec,
        font_size_px: float,
    ) -> None:
        if self._frame is None:
            return
        atlas = self._ensure_atlas(font, max(1.0, float(font_size_px)))
        lines = self._wrap_lines(text, atlas, max_width_px=max(4.0, w - 12.0), letter_spacing_px=0.0)
        widths = [self._line_advance(line, atlas, 0.0) for line in lines]
        line_h = max(atlas.line_height, float(font_size_px) * 1.15)
        block_h = max(float(font_size_px), float(len(lines)) * line_h)
        color = _parse_rgba_u8(color_hex, 1.0)
        top = float(y) + max(0.0, (h - block_h) * 0.5)
        for i, line in enumerate(lines):
            line_w = widths[i] if i < len(widths) else 0.0
            left = float(x) + max(0.0, (w - line_w) * 0.5)
            self._draw_line(
                line,
                atlas,
                x=left,
                top_y=top + float(i) * line_h,
                color=color,
                letter_spacing_px=0.0,
                font_weight=int(font.weight),
            )

    def _render_button_placeholder(self, command: StainedGlassButtonRenderCommand) -> None:
        x = int(round(float(command.x)))
        y = int(round(float(command.y)))
        w = max(1, int(round(float(command.width))))
        h = max(1, int(round(float(command.height))))
        self._blend_rect(x, y, w, h, _parse_rgba_u8("#334155", 0.72))
        self._blend_rect(x, y, w, 1, _parse_rgba_u8("#e2e8f0", 0.45))
        self._draw_button_label(
            text=str(command.label),
            x=float(x),
            y=float(y),
            w=float(w),
            h=float(h),
            color_hex=command.label_color_hex,
            font=command.label_font,
            font_size_px=float(command.label_font_size_px),
        )

    def _ensure_atlas(self, font: FontSpec, size_px: float) -> _FontAtlas:
        if size_px <= 0:
            raise ValueError("font size must be > 0")
        font_path = _resolve_font_path(font)
        key = (font_path, int(round(size_px * 100)))
        cached = self._font_atlas_cache.get(key)
        if cached is not None:
            return cached
        loaded_font = _load_font(font_path, size_px)
        self._last_font_source = _font_source_label(loaded_font, font_path)
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
        font_weight: int = 400,
    ) -> None:
        cursor = float(x)
        spacing = float(letter_spacing_px)
        synthetic_bold_steps = max(0, min(3, int(round((int(font_weight) - 400) / 160.0))))
        bold_offsets: tuple[tuple[int, int], ...] = ((1, 0), (0, 1), (1, 1))
        for i, ch in enumerate(line):
            glyph = self._ensure_glyph(atlas, ch)
            gx = int(round(cursor + glyph.x_offset))
            gy = int(round(top_y + glyph.y_offset))
            self._blend_alpha_mask(glyph.alpha_mask, x=gx, y=gy, color=color)
            if synthetic_bold_steps > 0:
                for dx, dy in bold_offsets[:synthetic_bold_steps]:
                    self._blend_alpha_mask(glyph.alpha_mask, x=gx + dx, y=gy + dy, color=color)
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
        if self._frame is None or w <= 0 or h <= 0 or not _HAS_NUMPY:
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
        dst = _as_float32_array(self._frame[y0:y1, x0:x1, :3])
        src = np.asarray(color[:3], dtype=np.float32).reshape(1, 1, 3)
        out = np.clip(src * alpha + dst * (1.0 - alpha), 0, 255).astype(np.uint8)
        self._frame[y0:y1, x0:x1, :3] = _from_uint8_array(out)
        self._frame[y0:y1, x0:x1, 3] = 255

    def _blend_mask(self, mask: object, *, x: int, y: int, color: tuple[int, int, int, int]) -> None:
        if self._frame is None or not _HAS_NUMPY:
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
        patch_mask_np = _as_bool_array(patch_mask)
        if not bool(np.any(patch_mask_np)):
            return
        alpha = color[3] / 255.0
        if alpha <= 0:
            return
        dst = _as_float32_array(self._frame[y0:y1, x0:x1, :3])
        src = np.asarray(color[:3], dtype=np.float32).reshape(1, 1, 3)
        blended = np.clip(src * alpha + dst * (1.0 - alpha), 0, 255).astype(np.uint8)
        current = _as_uint8_array(self._frame[y0:y1, x0:x1, :3])
        out = np.where(patch_mask_np[:, :, None], blended, current)
        self._frame[y0:y1, x0:x1, :3] = _from_uint8_array(out)
        self._frame[y0:y1, x0:x1, 3] = 255

    def _blend_alpha_mask(self, mask: object, *, x: int, y: int, color: tuple[int, int, int, int]) -> None:
        if not _HAS_NUMPY:
            self._blend_alpha_mask_pure(mask, x=x, y=y, color=color)
            return
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
        dst_rgb = _as_float32_array(patch[:, :, :3])
        dst_alpha = _as_float32_array(patch[:, :, 3]) / 255.0
        src_rgb = np.asarray(color[:3], dtype=np.float32).reshape(1, 1, 3)

        out_alpha = src_alpha + dst_alpha * (1.0 - src_alpha)
        out_rgb_num = src_rgb * src_alpha[:, :, None] + dst_rgb * dst_alpha[:, :, None] * (1.0 - src_alpha[:, :, None])
        safe = np.where(out_alpha > 1e-6, out_alpha, 1.0)
        out_rgb = out_rgb_num / safe[:, :, None]

        patch[:, :, :3] = _from_uint8_array(np.clip(out_rgb, 0, 255).astype(np.uint8))
        patch[:, :, 3] = _from_uint8_array(np.clip(out_alpha * 255.0, 0, 255).astype(np.uint8))

    def _blend_alpha_mask_pure(self, mask: object, *, x: int, y: int, color: tuple[int, int, int, int]) -> None:
        if self._frame is None or not hasattr(self._frame, "_data"):
            return
        mask_shape = getattr(mask, "shape", None)
        if mask_shape is None or len(mask_shape) != 2:
            return
        h, w = int(mask_shape[0]), int(mask_shape[1])
        frame_h, frame_w, frame_c = self._frame.shape
        if frame_c != 4:
            return
        mask_data = getattr(mask, "_data", None)
        if mask_data is None:
            return
        for my in range(h):
            fy = int(y) + my
            if fy < 0 or fy >= frame_h:
                continue
            for mx in range(w):
                fx = int(x) + mx
                if fx < 0 or fx >= frame_w:
                    continue
                coverage = int(mask_data[my * w + mx])
                if coverage <= 0:
                    continue
                src_a = (coverage / 255.0) * (float(color[3]) / 255.0)
                base = (fy * frame_w + fx) * 4
                dst_a = self._frame._data[base + 3] / 255.0
                out_a = src_a + dst_a * (1.0 - src_a)
                safe = out_a if out_a > 1e-6 else 1.0
                for ci in range(3):
                    dst = float(self._frame._data[base + ci])
                    src = float(color[ci])
                    out = (src * src_a + dst * dst_a * (1.0 - src_a)) / safe
                    self._frame._data[base + ci] = max(0, min(255, int(round(out))))
                self._frame._data[base + 3] = max(0, min(255, int(round(out_a * 255.0))))


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
    if not _HAS_PIL:
        return _FallbackFont(size_px)
    size = max(1, int(round(size_px)))
    try:
        return ImageFont.truetype(font_path, size=size)
    except Exception:
        return ImageFont.load_default()


def _font_source_label(font: object, font_path: str) -> str:
    if isinstance(font, _FallbackFont):
        return "fallback-bitmap"
    path = str(font_path or "").strip()
    if path:
        name = Path(path).name
        if name:
            return name
    return "pil-default"


def _font_metrics(font: ImageFont.FreeTypeFont | ImageFont.ImageFont, size_px: float) -> tuple[int, int]:
    if isinstance(font, _FallbackFont):
        return font.getmetrics()
    try:
        ascent, descent = font.getmetrics()
        return int(max(1, ascent)), int(max(0, descent))
    except Exception:
        return int(max(1, size_px * 0.8)), int(max(0, size_px * 0.2))


def _rasterize_glyph(font: ImageFont.FreeTypeFont | ImageFont.ImageFont, size_px: float, ch: str) -> _GlyphBitmap:
    if isinstance(font, _FallbackFont):
        return font.rasterize(ch)
    if ch == "":
        return _GlyphBitmap(alpha_mask=_zeros_mask(1, 1), x_offset=0, y_offset=0, advance=0.0)
    left, top, right, bottom = font.getbbox(ch)
    width = max(1, int(right - left))
    height = max(1, int(bottom - top))
    image = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(image)
    draw.text((-left, -top), ch, fill=255, font=font)
    mask = _mask_from_pillow_image(image)

    try:
        advance = float(font.getlength(ch))
    except Exception:
        advance = float(max(1, right - left))
    if ch == " ":
        advance = max(advance, size_px * 0.33)
    return _GlyphBitmap(alpha_mask=mask, x_offset=int(left), y_offset=int(top), advance=max(1.0, advance))


class _FallbackFont:
    """Small bitmap font used on embedded targets without Pillow."""

    def __init__(self, size_px: float) -> None:
        self.size_px = max(1.0, float(size_px))
        self.scale = max(1, int(round(self.size_px / 7.0)))
        self.height = 7 * self.scale
        self.width = 5 * self.scale

    def getmetrics(self) -> tuple[int, int]:
        return int(self.height), max(1, int(round(self.scale)))

    def rasterize(self, ch: str) -> _GlyphBitmap:
        if ch == "":
            return _GlyphBitmap(alpha_mask=_zeros_mask(1, 1), x_offset=0, y_offset=0, advance=0.0)
        if ch == " ":
            return _GlyphBitmap(
                alpha_mask=_zeros_mask(self.height, max(1, 3 * self.scale)),
                x_offset=0,
                y_offset=0,
                advance=float(max(1, 3 * self.scale)),
            )
        pattern = _FALLBACK_GLYPHS.get(ch.lower(), _FALLBACK_GLYPHS["?"])
        mask = _mask_from_pattern(pattern, self.scale)
        return _GlyphBitmap(
            alpha_mask=mask,
            x_offset=0,
            y_offset=0,
            advance=float(mask.shape[1] + self.scale),
        )


_FALLBACK_GLYPHS: dict[str, tuple[str, ...]] = {
    "a": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "b": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "c": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "d": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "e": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "f": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "g": ("01111", "10000", "10000", "10011", "10001", "10001", "01111"),
    "h": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "i": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "j": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "k": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "l": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "m": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "n": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "o": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "p": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "r": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "s": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "t": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "u": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "v": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "w": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "x": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    ":": ("00000", "00100", "00100", "00000", "00100", "00100", "00000"),
    "_": ("00000", "00000", "00000", "00000", "00000", "00000", "11111"),
    "|": ("00100", "00100", "00100", "00100", "00100", "00100", "00100"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    ",": ("00000", "00000", "00000", "00000", "00000", "00100", "01000"),
    "?": ("01110", "10001", "00001", "00010", "00100", "00000", "00100"),
}


def _zeros_mask(height: int, width: int) -> object:
    height = max(1, int(height))
    width = max(1, int(width))
    if _HAS_NUMPY:
        return np.zeros((height, width), dtype=np.uint8)
    return accel.zeros((height, width))


def _mask_from_pillow_image(image: object) -> object:
    if _HAS_NUMPY:
        return np.asarray(image, dtype=np.uint8)
    width, height = image.size
    mask = accel.zeros((height, width))
    data = bytes(image.tobytes())
    mask._data[: len(data)] = data
    return mask


def _mask_from_pattern(pattern: tuple[str, ...], scale: int) -> object:
    scale = max(1, int(scale))
    height = max(1, len(pattern) * scale)
    width = max(1, (len(pattern[0]) if pattern else 1) * scale)
    if _HAS_NUMPY:
        rows = []
        for row in pattern:
            bits = [255 if item == "1" else 0 for item in row]
            expanded = np.repeat(np.asarray(bits, dtype=np.uint8), scale)
            rows.extend([expanded] * scale)
        return np.vstack(rows) if rows else np.zeros((height, width), dtype=np.uint8)
    mask = accel.zeros((height, width))
    for py, row in enumerate(pattern):
        for px, item in enumerate(row):
            if item != "1":
                continue
            for sy in range(scale):
                y = py * scale + sy
                for sx in range(scale):
                    x = px * scale + sx
                    mask._data[y * width + x] = 255
    return mask


def _as_uint8_array(value: object) -> object:
    if not _HAS_NUMPY:
        return value
    if _HAS_TORCH and torch.is_tensor(value):
        return value.detach().cpu().numpy().astype(np.uint8, copy=False)
    return np.asarray(value, dtype=np.uint8)


def _as_float32_array(value: object) -> object:
    if not _HAS_NUMPY:
        return value
    if _HAS_TORCH and torch.is_tensor(value):
        return value.detach().cpu().numpy().astype(np.float32, copy=False)
    return np.asarray(value, dtype=np.float32)


def _as_bool_array(value: object) -> object:
    if not _HAS_NUMPY:
        return value
    if _HAS_TORCH and torch.is_tensor(value):
        return value.detach().cpu().numpy().astype(bool, copy=False)
    return np.asarray(value, dtype=bool)


def _from_uint8_array(value: object) -> object:
    if not _HAS_NUMPY:
        return value
    if _HAS_TORCH:
        return torch.from_numpy(np.asarray(value, dtype=np.uint8))
    return np.asarray(value, dtype=np.uint8)


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
    py_packages_dir = Path(__file__).resolve().parents[2]
    bundled_font_dirs = [
        py_packages_dir / "luvatrix_assets" / "fonts",
        py_packages_dir / "assets" / "fonts",
    ]
    for entry in sys.path:
        if entry:
            bundled_font_dirs.append(Path(entry) / "luvatrix_assets" / "fonts")
    extra_font_dirs = [
        Path(item)
        for item in os.getenv("LUVATRIX_FONT_DIRS", "").split(os.pathsep)
        if item.strip()
    ]
    font_dirs = (
        *extra_font_dirs,
        *bundled_font_dirs,
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


def _gaussian_kernel_1d(kernel_size: int, sigma: float, *, device: torch.device) -> torch.Tensor:
    ks = max(3, int(kernel_size))
    if ks % 2 == 0:
        ks += 1
    s = max(0.1, float(sigma))
    radius = ks // 2
    x = torch.arange(-radius, radius + 1, dtype=torch.float32, device=device)
    kernel = torch.exp(-(x * x) / (2.0 * s * s))
    kernel_sum = torch.sum(kernel)
    if float(kernel_sum) <= 1e-9:
        return torch.ones((ks,), dtype=torch.float32, device=device) / float(ks)
    return kernel / kernel_sum
