from __future__ import annotations

import numpy as np

from luvatrix_plot.raster.canvas import RGBA, draw_pixel


def draw_polyline(dst: np.ndarray, xs: np.ndarray, ys: np.ndarray, color: RGBA, width: int = 1) -> None:
    if xs.size < 2:
        return
    for i in range(xs.size - 1):
        _draw_line_segment(dst, int(xs[i]), int(ys[i]), int(xs[i + 1]), int(ys[i + 1]), color=color, width=width)


def _draw_line_segment(dst: np.ndarray, x0: int, y0: int, x1: int, y1: int, color: RGBA, width: int) -> None:
    dx = abs(x1 - x0)
    sx = 1 if x0 < x1 else -1
    dy = -abs(y1 - y0)
    sy = 1 if y0 < y1 else -1
    err = dx + dy

    while True:
        _draw_square_brush(dst, x0, y0, color=color, width=width)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def _draw_square_brush(dst: np.ndarray, x: int, y: int, color: RGBA, width: int) -> None:
    radius = max(0, width // 2)
    for yy in range(y - radius, y + radius + 1):
        for xx in range(x - radius, x + radius + 1):
            draw_pixel(dst, xx, yy, color)
