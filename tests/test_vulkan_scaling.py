from __future__ import annotations

import os
import unittest

import torch

from luvatrix_core.platform.vulkan_scaling import RenderScaleController, compute_blit_rect


class VulkanScalingTests(unittest.TestCase):
    def test_compute_blit_rect_stretch(self) -> None:
        self.assertEqual(
            compute_blit_rect(src_w=320, src_h=180, dst_w=800, dst_h=600, preserve_aspect_ratio=False),
            (0, 0, 800, 600),
        )

    def test_compute_blit_rect_preserve_aspect(self) -> None:
        x0, y0, x1, y1 = compute_blit_rect(
            src_w=320, src_h=180, dst_w=800, dst_h=600, preserve_aspect_ratio=True
        )
        self.assertEqual((x0, x1), (0, 800))
        self.assertEqual((y0, y1), (75, 525))

    def test_render_scale_controller_from_env_quantizes(self) -> None:
        old = os.environ.get("LUVATRIX_INTERNAL_RENDER_SCALE")
        os.environ["LUVATRIX_INTERNAL_RENDER_SCALE"] = "0.8"
        try:
            ctl = RenderScaleController.from_env()
            self.assertEqual(ctl.fixed_scale, 0.75)
            self.assertEqual(ctl.effective_scale(), 0.75)
        finally:
            if old is None:
                os.environ.pop("LUVATRIX_INTERNAL_RENDER_SCALE", None)
            else:
                os.environ["LUVATRIX_INTERNAL_RENDER_SCALE"] = old

    def test_scale_frame_reduces_extent(self) -> None:
        ctl = RenderScaleController(
            levels=(1.0, 0.75, 0.5),
            fixed_scale=0.5,
            auto_enabled=False,
            current_scale=0.5,
        )
        src = torch.zeros((120, 200, 4), dtype=torch.uint8)
        out = ctl.scale_frame(src)
        self.assertEqual(tuple(out.shape), (60, 100, 4))

    def test_update_scales_down_and_up(self) -> None:
        ctl = RenderScaleController(
            levels=(1.0, 0.75, 0.5),
            fixed_scale=None,
            auto_enabled=True,
            current_scale=1.0,
        )
        changed_down = ctl.update(elapsed_ms=24.0, enabled=True)
        self.assertTrue(changed_down)
        self.assertEqual(ctl.current_scale, 0.75)
        ctl.cooldown_frames = 0
        ctl.present_time_ema_ms = 8.0
        changed_up = ctl.update(elapsed_ms=8.0, enabled=True)
        self.assertTrue(changed_up)
        self.assertEqual(ctl.current_scale, 1.0)


if __name__ == "__main__":
    unittest.main()
