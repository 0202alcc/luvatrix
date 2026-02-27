from __future__ import annotations

import numpy as np

from luvatrix_plot.raster.canvas import RGBA, draw_pixel


def draw_markers(dst: np.ndarray, xs: np.ndarray, ys: np.ndarray, color: RGBA, size: int = 1) -> None:
    radius = max(0, size // 2)
    for x, y in zip(xs.tolist(), ys.tolist(), strict=False):
        _draw_marker(dst, int(x), int(y), color=color, radius=radius)


def _draw_marker(dst: np.ndarray, x: int, y: int, color: RGBA, radius: int) -> None:
    for yy in range(y - radius, y + radius + 1):
        for xx in range(x - radius, x + radius + 1):
            draw_pixel(dst, xx, yy, color)
