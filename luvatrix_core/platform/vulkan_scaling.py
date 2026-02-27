from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Sequence

import torch

from .frame_pipeline import resize_rgba_bilinear


@dataclass
class RenderScaleController:
    levels: tuple[float, ...]
    fixed_scale: float | None
    auto_enabled: bool
    current_scale: float
    present_time_ema_ms: float | None = None
    cooldown_frames: int = 0

    @classmethod
    def from_env(
        cls,
        *,
        levels: Sequence[float] = (1.0, 0.75, 0.5),
        fixed_env_var: str = "LUVATRIX_INTERNAL_RENDER_SCALE",
        auto_env_var: str = "LUVATRIX_AUTO_RENDER_SCALE",
        auto_default: str = "1",
    ) -> "RenderScaleController":
        level_tuple = tuple(float(x) for x in levels)
        fixed = _parse_fixed_scale(level_tuple, fixed_env_var)
        auto_enabled = os.getenv(auto_env_var, auto_default).strip() == "1"
        current = fixed if fixed is not None else 1.0
        return cls(
            levels=level_tuple,
            fixed_scale=fixed,
            auto_enabled=auto_enabled,
            current_scale=current,
        )

    def effective_scale(self) -> float:
        if self.fixed_scale is not None:
            return self.fixed_scale
        return self.current_scale

    def scale_frame(self, rgba: torch.Tensor) -> torch.Tensor:
        scale = self.effective_scale()
        if scale >= 0.999:
            return rgba
        src_h, src_w, _ = rgba.shape
        target_w = max(1, int(round(float(src_w) * scale)))
        target_h = max(1, int(round(float(src_h) * scale)))
        return resize_rgba_bilinear(rgba, target_h=target_h, target_w=target_w)

    def update(self, *, elapsed_ms: float, enabled: bool) -> bool:
        if not enabled:
            return False
        if self.fixed_scale is not None:
            self.current_scale = self.fixed_scale
            return False
        if not self.auto_enabled:
            return False
        alpha = 0.15
        if self.present_time_ema_ms is None:
            self.present_time_ema_ms = elapsed_ms
        else:
            self.present_time_ema_ms = (1.0 - alpha) * self.present_time_ema_ms + alpha * elapsed_ms
        if self.cooldown_frames > 0:
            self.cooldown_frames -= 1
            return False
        idx = self.levels.index(self.current_scale)
        assert self.present_time_ema_ms is not None
        if self.present_time_ema_ms > 17.0 and idx < (len(self.levels) - 1):
            self.current_scale = self.levels[idx + 1]
            self.cooldown_frames = 30
            return True
        if self.present_time_ema_ms < 10.0 and idx > 0:
            self.current_scale = self.levels[idx - 1]
            self.cooldown_frames = 60
            return True
        return False


def compute_blit_rect(
    *,
    src_w: int,
    src_h: int,
    dst_w: int,
    dst_h: int,
    preserve_aspect_ratio: bool,
) -> tuple[int, int, int, int]:
    if src_w <= 0 or src_h <= 0 or dst_w <= 0 or dst_h <= 0:
        return (0, 0, 0, 0)
    if not preserve_aspect_ratio:
        return (0, 0, dst_w, dst_h)
    scale = min(float(dst_w) / float(src_w), float(dst_h) / float(src_h))
    blit_w = max(1, int(round(src_w * scale)))
    blit_h = max(1, int(round(src_h * scale)))
    x0 = (dst_w - blit_w) // 2
    y0 = (dst_h - blit_h) // 2
    return (x0, y0, x0 + blit_w, y0 + blit_h)


def _parse_fixed_scale(levels: tuple[float, ...], env_var: str) -> float | None:
    raw = os.getenv(env_var, "").strip()
    if raw == "":
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return min(levels, key=lambda x: abs(x - value))
