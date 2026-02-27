from __future__ import annotations

import numpy as np


RGBA = tuple[int, int, int, int]


def new_canvas(width: int, height: int, color: RGBA = (0, 0, 0, 255)) -> np.ndarray:
    canvas = np.zeros((height, width, 4), dtype=np.uint8)
    canvas[:, :, 0] = color[0]
    canvas[:, :, 1] = color[1]
    canvas[:, :, 2] = color[2]
    canvas[:, :, 3] = color[3]
    return canvas


def blit(dst: np.ndarray, src: np.ndarray, x0: int = 0, y0: int = 0) -> None:
    h, w, _ = src.shape
    y1 = min(dst.shape[0], y0 + h)
    x1 = min(dst.shape[1], x0 + w)
    if y0 >= y1 or x0 >= x1:
        return

    view = dst[y0:y1, x0:x1]
    patch = src[: y1 - y0, : x1 - x0]
    alpha = patch[:, :, 3:4].astype(np.float32) / 255.0
    inv = 1.0 - alpha
    view[:, :, :3] = (patch[:, :, :3] * alpha + view[:, :, :3] * inv).astype(np.uint8)
    view[:, :, 3] = 255


def draw_pixel(dst: np.ndarray, x: int, y: int, color: RGBA) -> None:
    if y < 0 or y >= dst.shape[0] or x < 0 or x >= dst.shape[1]:
        return
    a = color[3] / 255.0
    inv = 1.0 - a
    current = dst[y, x, :3].astype(np.float32)
    dst[y, x, 0:3] = (np.asarray(color[0:3], dtype=np.float32) * a + current * inv).astype(np.uint8)
    dst[y, x, 3] = 255


def draw_hline(dst: np.ndarray, x0: int, x1: int, y: int, color: RGBA) -> None:
    if y < 0 or y >= dst.shape[0]:
        return
    xa = max(0, min(x0, x1))
    xb = min(dst.shape[1] - 1, max(x0, x1))
    if xa > xb:
        return
    segment = dst[y, xa : xb + 1]
    a = color[3] / 255.0
    inv = 1.0 - a
    segment[:, :3] = (np.asarray(color[0:3], dtype=np.float32) * a + segment[:, :3].astype(np.float32) * inv).astype(np.uint8)
    segment[:, 3] = 255


def draw_vline(dst: np.ndarray, x: int, y0: int, y1: int, color: RGBA) -> None:
    if x < 0 or x >= dst.shape[1]:
        return
    ya = max(0, min(y0, y1))
    yb = min(dst.shape[0] - 1, max(y0, y1))
    if ya > yb:
        return
    segment = dst[ya : yb + 1, x]
    a = color[3] / 255.0
    inv = 1.0 - a
    segment[:, :3] = (np.asarray(color[0:3], dtype=np.float32) * a + segment[:, :3].astype(np.float32) * inv).astype(np.uint8)
    segment[:, 3] = 255
