from __future__ import annotations

from enum import Enum

import torch
import torch.nn.functional as F


class PresentationMode(str, Enum):
    PIXEL_PRESERVE = "pixel_preserve"
    PRESERVE_ASPECT = "preserve_aspect"
    STRETCH = "stretch"


def normalize_presentation_mode(mode: PresentationMode | str) -> PresentationMode:
    if isinstance(mode, PresentationMode):
        return mode
    return PresentationMode(str(mode))


def resize_rgba_bilinear(rgba: torch.Tensor, target_h: int, target_w: int) -> torch.Tensor:
    if target_h <= 0 or target_w <= 0:
        raise ValueError("target dimensions must be > 0")
    src = rgba.to(torch.float32).permute(2, 0, 1).unsqueeze(0)
    out = F.interpolate(src, size=(target_h, target_w), mode="bilinear", align_corners=False)
    out = out.squeeze(0).permute(1, 2, 0).clamp(0, 255).to(torch.uint8)
    return out.contiguous()


def resize_rgba_nearest(rgba: torch.Tensor, target_h: int, target_w: int) -> torch.Tensor:
    if target_h <= 0 or target_w <= 0:
        raise ValueError("target dimensions must be > 0")
    src = rgba.to(torch.float32).permute(2, 0, 1).unsqueeze(0)
    out = F.interpolate(src, size=(target_h, target_w), mode="nearest")
    out = out.squeeze(0).permute(1, 2, 0).clamp(0, 255).to(torch.uint8)
    return out.contiguous()


def expand_rgba_integer(rgba: torch.Tensor, scale: int) -> torch.Tensor:
    if scale <= 0:
        raise ValueError("scale must be > 0")
    if scale == 1:
        return rgba if rgba.is_contiguous() else rgba.contiguous()
    out = rgba.repeat_interleave(scale, dim=0).repeat_interleave(scale, dim=1)
    return out.contiguous()


def prepare_frame_for_extent(
    rgba: torch.Tensor,
    target_w: int,
    target_h: int,
    presentation_mode: PresentationMode | str = PresentationMode.STRETCH,
    preserve_aspect_ratio: bool | None = None,
) -> torch.Tensor:
    if target_w <= 0 or target_h <= 0:
        raise ValueError("target dimensions must be > 0")
    if preserve_aspect_ratio is not None:
        mode = PresentationMode.PRESERVE_ASPECT if preserve_aspect_ratio else PresentationMode.STRETCH
    else:
        mode = normalize_presentation_mode(presentation_mode)
    src_h, src_w, _ = rgba.shape
    if src_w == target_w and src_h == target_h:
        return rgba
    if mode == PresentationMode.STRETCH:
        return resize_rgba_bilinear(rgba, target_h=target_h, target_w=target_w)
    if mode == PresentationMode.PIXEL_PRESERVE:
        return prepare_pixel_preserve_frame(rgba, target_w=target_w, target_h=target_h)

    scale = min(float(target_w) / float(src_w), float(target_h) / float(src_h))
    dst_w = max(1, int(round(src_w * scale)))
    dst_h = max(1, int(round(src_h * scale)))
    resized = resize_rgba_bilinear(rgba, target_h=dst_h, target_w=dst_w)
    return center_rgba_on_canvas(resized, target_w=target_w, target_h=target_h)


def prepare_pixel_preserve_frame(rgba: torch.Tensor, target_w: int, target_h: int) -> torch.Tensor:
    if target_w <= 0 or target_h <= 0:
        raise ValueError("target dimensions must be > 0")
    src_h, src_w, _ = rgba.shape
    if src_w == target_w and src_h == target_h:
        return rgba if rgba.is_contiguous() else rgba.contiguous()

    scale = min(float(target_w) / float(src_w), float(target_h) / float(src_h))
    if scale >= 1.0:
        integer_scale = max(1, int(scale))
        expanded = expand_rgba_integer(rgba, integer_scale)
        return center_rgba_on_canvas(expanded, target_w=target_w, target_h=target_h)

    dst_w = max(1, int(round(src_w * scale)))
    dst_h = max(1, int(round(src_h * scale)))
    resized = resize_rgba_nearest(rgba, target_h=dst_h, target_w=dst_w)
    return center_rgba_on_canvas(resized, target_w=target_w, target_h=target_h)


def center_rgba_on_canvas(rgba: torch.Tensor, target_w: int, target_h: int) -> torch.Tensor:
    src_h, src_w, _ = rgba.shape
    canvas = torch.zeros((target_h, target_w, 4), dtype=torch.uint8)
    canvas[:, :, 3] = 255
    y = (target_h - src_h) // 2
    x = (target_w - src_w) // 2
    canvas[y : y + src_h, x : x + src_w, :] = rgba
    return canvas
