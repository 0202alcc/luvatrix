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
    ClearNode,
    CpuLayerNode,
    RectNode,
    RoundedRectNode,
    SceneFrame,
)
from luvatrix_core.core.scene_rasterizer import _blend_alpha_mask, rasterize_scene_frame


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


class TestFillAlphaSurvives:
    """SL-38 whole-window material: the scene's alpha'd fills must reach the
    framebuffer with their alpha INTACT — the behind-window material shows
    through covered-but-translucent pixels exactly like it shows through
    unpainted gaps. The MCP app_screenshot readback rasters this same path,
    so a forced-opaque alpha here also lies about the layer to probes."""

    def test_rect_fill_alpha_survives_over_transparent_clear(self):
        nodes = [
            ClearNode(color_rgba=(0, 0, 0, 0)),
            RectNode(x=2, y=2, width=4, height=4, color_rgba=(16, 16, 16, 166), z_index=1),
        ]
        img = rasterize_scene_frame(_frame(nodes))
        assert abs(int(img[3, 3, 3]) - 166) <= 2, \
            f"covered pixel keeps the fill alpha, got {int(img[3, 3, 3])}"
        assert int(img[0, 0, 3]) == 0, "unpainted gaps keep the clear alpha"

    def test_stacked_fills_composite_source_over_alpha(self):
        nodes = [
            ClearNode(color_rgba=(0, 0, 0, 0)),
            RectNode(x=0, y=0, width=8, height=8, color_rgba=(16, 16, 16, 64), z_index=1),
            RectNode(x=2, y=2, width=4, height=4, color_rgba=(16, 16, 16, 166), z_index=2),
        ]
        img = rasterize_scene_frame(_frame(nodes))
        a_lo = 64 / 255.0
        a_hi = 166 / 255.0
        expected = round(255 * (a_hi + a_lo * (1.0 - a_hi)))
        assert abs(int(img[3, 3, 3]) - expected) <= 2, \
            f"stacked fills composite alpha source-over, got {int(img[3, 3, 3])} want ~{expected}"
        assert abs(int(img[0, 0, 3]) - 64) <= 2, \
            f"singly-covered pixel keeps its own alpha, got {int(img[0, 0, 3])}"

    def test_rounded_rect_fill_alpha_survives(self):
        nodes = [
            ClearNode(color_rgba=(0, 0, 0, 0)),
            RoundedRectNode(x=1, y=1, width=6, height=6, radius=2,
                            color_rgba=(16, 16, 16, 166), z_index=1),
        ]
        img = rasterize_scene_frame(_frame(nodes))
        assert abs(int(img[4, 4, 3]) - 166) <= 2, \
            f"rounded fill keeps its alpha, got {int(img[4, 4, 3])}"

    def test_alpha_mask_blend_keeps_color_alpha(self):
        """Glyph/mask compositing: coverage*color_alpha must composite into
        the destination alpha, not stomp it opaque (text over the material)."""
        import numpy as np

        out = np.zeros((4, 4, 4), dtype=np.uint8)
        mask = np.full((2, 2), 255, dtype=np.uint8)
        _blend_alpha_mask(out, mask, x=1, y=1, color=(255, 255, 255, 200))
        assert abs(int(out[1, 1, 3]) - 200) <= 2, \
            f"full-ink pixel keeps the text color alpha, got {int(out[1, 1, 3])}"
        assert int(out[0, 0, 3]) == 0, "uncovered pixels stay transparent"

    def test_opaque_fill_still_writes_255(self):
        nodes = [
            ClearNode(color_rgba=(0, 0, 0, 0)),
            RectNode(x=2, y=2, width=4, height=4, color_rgba=(255, 255, 255, 255), z_index=1),
        ]
        img = rasterize_scene_frame(_frame(nodes))
        assert int(img[3, 3, 3]) == 255, "opaque fragments stay opaque"


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
