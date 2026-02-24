from __future__ import annotations

import torch
import torch.nn.functional as F


def resize_rgba_bilinear(rgba: torch.Tensor, target_h: int, target_w: int) -> torch.Tensor:
    if target_h <= 0 or target_w <= 0:
        raise ValueError("target dimensions must be > 0")
    src = rgba.to(torch.float32).permute(2, 0, 1).unsqueeze(0)
    out = F.interpolate(src, size=(target_h, target_w), mode="bilinear", align_corners=False)
    out = out.squeeze(0).permute(1, 2, 0).clamp(0, 255).to(torch.uint8)
    return out.contiguous()


def prepare_frame_for_extent(
    rgba: torch.Tensor,
    target_w: int,
    target_h: int,
    preserve_aspect_ratio: bool,
) -> torch.Tensor:
    if target_w <= 0 or target_h <= 0:
        raise ValueError("target dimensions must be > 0")
    src_h, src_w, _ = rgba.shape
    if src_w == target_w and src_h == target_h:
        return rgba
    if not preserve_aspect_ratio:
        return resize_rgba_bilinear(rgba, target_h=target_h, target_w=target_w)

    scale = min(float(target_w) / float(src_w), float(target_h) / float(src_h))
    dst_w = max(1, int(round(src_w * scale)))
    dst_h = max(1, int(round(src_h * scale)))
    resized = resize_rgba_bilinear(rgba, target_h=dst_h, target_w=dst_w)
    canvas = torch.zeros((target_h, target_w, 4), dtype=torch.uint8)
    canvas[:, :, 3] = 255
    y = (target_h - dst_h) // 2
    x = (target_w - dst_w) // 2
    canvas[y : y + dst_h, x : x + dst_w, :] = resized
    return canvas
