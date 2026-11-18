"""CPU scene rasterizer layer compositing.

The macOS Metal target draws CpuLayerNode/ImageNode textures with standard
source-alpha blending, so an art buffer alpha-clipped to a rounded
silhouette (Spotify Light's pill thumb, round 28) shows whatever is behind
it at the transparent pixels. The CPU rasterizer must composite the same
way — a straight copy paints the clipped corners' stale RGB and the two
render paths diverge.
"""
from __future__ import annotations

import numpy as np

from luvatrix_core.core.scene_graph import (
    CpuLayerNode,
    RectNode,
    SceneFrame,
)
from luvatrix_core.core.scene_rasterizer import rasterize_scene_frame


def _frame(nodes) -> SceneFrame:
    return SceneFrame(
        revision=1,
        logical_width=8,
        logical_height=8,
        display_width=8,
        display_height=8,
        ts_ns=0,
        nodes=tuple(nodes),
    )


class TestLayerAlphaBlending:
    def test_transparent_pixels_show_the_backdrop(self):
        nodes = [
            RectNode(x=0, y=0, width=8, height=8, color_rgba=(20, 30, 40, 255), z_index=0),
            CpuLayerNode(x=0, y=0, width=2, height=2,
                         rgba=np.array([[(200, 100, 50, 0)] * 2] * 2, dtype=np.uint8),
                         z_index=1),
        ]
        img = rasterize_scene_frame(_frame(nodes))
        assert tuple(int(v) for v in img[0, 0, :3]) == (20, 30, 40), \
            "alpha-0 layer pixels must not paint over the backdrop"

    def test_opaque_pixels_paint_and_half_alpha_blends(self):
        rgba = np.zeros((2, 2, 4), dtype=np.uint8)
        rgba[0, 0] = (200, 100, 50, 255)
        rgba[0, 1] = (200, 100, 50, 128)
        nodes = [
            RectNode(x=0, y=0, width=8, height=8, color_rgba=(0, 0, 0, 255), z_index=0),
            CpuLayerNode(x=0, y=0, width=2, height=2, rgba=rgba, z_index=1),
        ]
        img = rasterize_scene_frame(_frame(nodes))
        assert tuple(int(v) for v in img[0, 0, :3]) == (200, 100, 50), "opaque paints as-is"
        blended = img[0, 1, :3].astype(int)
        expected = np.array([200, 100, 50]) * (128 / 255.0)
        assert all(abs(blended[i] - round(expected[i])) <= 1 for i in range(3)), \
            f"alpha 128 over black must halve the channels, got {tuple(blended)}"

    def test_partial_alpha_respects_the_backdrop_color(self):
        nodes = [
            RectNode(x=0, y=0, width=8, height=8, color_rgba=(255, 255, 255, 255), z_index=0),
            CpuLayerNode(x=0, y=0, width=1, height=1,
                         rgba=np.array([[(0, 0, 0, 128)]], dtype=np.uint8), z_index=1),
        ]
        img = rasterize_scene_frame(_frame(nodes))
        lum = int(img[0, 0, :3].sum()) / 3
        assert 120 <= lum <= 135, f"black at half alpha over white must land mid-gray, got {lum}"
