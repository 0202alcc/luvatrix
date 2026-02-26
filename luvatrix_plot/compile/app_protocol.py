from __future__ import annotations

import numpy as np
import torch

from luvatrix_core.core.window_matrix import FullRewrite, WriteBatch


def compile_full_rewrite_batch(frame_rgba: np.ndarray) -> WriteBatch:
    if frame_rgba.dtype != np.uint8:
        raise ValueError("frame_rgba must be uint8")
    if frame_rgba.ndim != 3 or frame_rgba.shape[2] != 4:
        raise ValueError("frame_rgba must have shape (H, W, 4)")

    tensor = torch.from_numpy(np.ascontiguousarray(frame_rgba))
    return WriteBatch([FullRewrite(tensor)])
