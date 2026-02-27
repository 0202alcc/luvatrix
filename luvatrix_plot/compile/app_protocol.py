from __future__ import annotations

import numpy as np
import torch

from luvatrix_core.core.window_matrix import FullRewrite, ReplaceRect, WriteBatch


def compile_full_rewrite_batch(frame_rgba: np.ndarray) -> WriteBatch:
    if frame_rgba.dtype != np.uint8:
        raise ValueError("frame_rgba must be uint8")
    if frame_rgba.ndim != 3 or frame_rgba.shape[2] != 4:
        raise ValueError("frame_rgba must have shape (H, W, 4)")

    tensor = torch.from_numpy(np.ascontiguousarray(frame_rgba))
    return WriteBatch([FullRewrite(tensor)])


def compile_replace_rect_batch(frame_rgba: np.ndarray, x: int, y: int, width: int, height: int) -> WriteBatch:
    if frame_rgba.dtype != np.uint8:
        raise ValueError("frame_rgba must be uint8")
    if frame_rgba.ndim != 3 or frame_rgba.shape[2] != 4:
        raise ValueError("frame_rgba must have shape (H, W, 4)")
    if width <= 0 or height <= 0:
        raise ValueError("rect width/height must be > 0")
    if x < 0 or y < 0:
        raise ValueError("rect x/y must be >= 0")
    if x + width > frame_rgba.shape[1] or y + height > frame_rgba.shape[0]:
        raise ValueError("rect exceeds frame bounds")
    patch = torch.from_numpy(np.ascontiguousarray(frame_rgba[y : y + height, x : x + width]))
    return WriteBatch([ReplaceRect(x=x, y=y, width=width, height=height, rect_h_w_4=patch)])


def compile_replace_patch_batch(patch_rgba: np.ndarray, x: int, y: int) -> WriteBatch:
    if patch_rgba.dtype != np.uint8:
        raise ValueError("patch_rgba must be uint8")
    if patch_rgba.ndim != 3 or patch_rgba.shape[2] != 4:
        raise ValueError("patch_rgba must have shape (H, W, 4)")
    if x < 0 or y < 0:
        raise ValueError("rect x/y must be >= 0")
    height, width, _ = patch_rgba.shape
    if width <= 0 or height <= 0:
        raise ValueError("patch width/height must be > 0")
    patch = torch.from_numpy(np.ascontiguousarray(patch_rgba))
    return WriteBatch([ReplaceRect(x=x, y=y, width=width, height=height, rect_h_w_4=patch)])


def compile_replace_patches_batch(patches: list[tuple[int, int, np.ndarray]]) -> WriteBatch:
    ops: list[ReplaceRect] = []
    for x, y, patch_rgba in patches:
        if patch_rgba.dtype != np.uint8:
            raise ValueError("patch_rgba must be uint8")
        if patch_rgba.ndim != 3 or patch_rgba.shape[2] != 4:
            raise ValueError("patch_rgba must have shape (H, W, 4)")
        if x < 0 or y < 0:
            raise ValueError("rect x/y must be >= 0")
        height, width, _ = patch_rgba.shape
        if width <= 0 or height <= 0:
            continue
        patch = torch.from_numpy(np.ascontiguousarray(patch_rgba))
        ops.append(ReplaceRect(x=x, y=y, width=width, height=height, rect_h_w_4=patch))
    if not ops:
        raise ValueError("patches must include at least one non-empty patch")
    return WriteBatch(ops)
