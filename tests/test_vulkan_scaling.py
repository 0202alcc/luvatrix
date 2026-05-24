from __future__ import annotations

import os
import unittest

import torch

from luvatrix_core.platform.frame_pipeline import PresentationMode
from luvatrix_core.platform.vulkan_scaling import RenderScaleController, compute_blit_rect


class VulkanScalingTests(unittest.TestCase):
    def test_compute_blit_rect_stretch(self) -> None:
        self.assertEqual(
            compute_blit_rect(
                src_w=320,
                src_h=180,
                dst_w=800,
                dst_h=600,
                presentation_mode=PresentationMode.STRETCH,
            ),
            ((0, 0, 320, 180), (0, 0, 800, 600)),
        )

    def test_compute_blit_rect_preserve_aspect(self) -> None:
        src_offsets, dst_offsets = compute_blit_rect(
            src_w=320,
            src_h=180,
            dst_w=800,
            dst_h=600,
            presentation_mode=PresentationMode.PRESERVE_ASPECT,
        )
        self.assertEqual(src_offsets, (0, 0, 320, 180))
        self.assertEqual(dst_offsets[:2], (0, 75))
        self.assertEqual(dst_offsets[2:], (800, 525))

    def test_compute_blit_rect_pixel_preserve_uses_integer_scale(self) -> None:
        src_offsets, dst_offsets = compute_blit_rect(
            src_w=3,
            src_h=2,
            dst_w=10,
            dst_h=8,
            presentation_mode=PresentationMode.PIXEL_PRESERVE,
        )
        self.assertEqual(src_offsets, (0, 0, 3, 2))
        self.assertEqual(dst_offsets, (0, 1, 9, 7))

    def test_compute_blit_rect_crop_fit_src_is_larger(self) -> None:
        """Stream 4032x3024 into 800x600 canvas — centered crop/downscale, dst fills surface."""
        src_offsets, dst_offsets = compute_blit_rect(
            src_w=4032,
            src_h=3024,
            dst_w=800,
            dst_h=600,
            presentation_mode=PresentationMode.CROP_FIT,
        )
        # scale = max(800/4032, 600/3024) ≈ 0.198; finalized ≈ 800×600
        self.assertEqual(dst_offsets, (0, 0, 800, 600))
        self.assertEqual(src_offsets, (0, 0, 800, 600))

    def test_compute_blit_rect_crop_fit_asymmetric_crop(self) -> None:
        """3840×2160 into 393×852: horizontal is cropped, vertical fills exactly."""
        src_offsets, dst_offsets = compute_blit_rect(
            src_w=3840,
            src_h=2160,
            dst_w=393,
            dst_h=852,
            presentation_mode=PresentationMode.CROP_FIT,
        )
        # scale = max(393/3840, 852/2160) ≈ 0.3944
        # finalized_w ≈ 1515, finalized_h ≈ 852
        self.assertEqual(dst_offsets, (0, 0, 393, 852))
        self.assertEqual(src_offsets[1], 0)          # vertical: no crop
        self.assertEqual(src_offsets[3], 852)
        self.assertGreater(src_offsets[0], 0)         # horizontal: cropped (barber pole)

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
