from __future__ import annotations

import unittest

import torch

from luvatrix_core.platform.frame_pipeline import prepare_frame_for_extent, resize_rgba_bilinear


class FramePipelineTests(unittest.TestCase):
    def test_resize_rgba_bilinear_updates_shape(self) -> None:
        frame = torch.zeros((2, 3, 4), dtype=torch.uint8)
        out = resize_rgba_bilinear(frame, target_h=5, target_w=7)
        self.assertEqual(tuple(out.shape), (5, 7, 4))
        self.assertEqual(out.dtype, torch.uint8)

    def test_prepare_frame_stretch_mode_fills_target(self) -> None:
        frame = torch.zeros((2, 4, 4), dtype=torch.uint8)
        frame[:, :, 0] = 120
        frame[:, :, 3] = 255
        out = prepare_frame_for_extent(frame, target_w=8, target_h=8, preserve_aspect_ratio=False)
        self.assertEqual(tuple(out.shape), (8, 8, 4))
        # Stretch mode should not introduce letterbox bars.
        self.assertGreater(out[:, :, 0].float().mean().item(), 0.0)

    def test_prepare_frame_preserve_aspect_letterboxes(self) -> None:
        frame = torch.zeros((2, 4, 4), dtype=torch.uint8)
        frame[:, :, 1] = 200
        frame[:, :, 3] = 255
        out = prepare_frame_for_extent(frame, target_w=8, target_h=8, preserve_aspect_ratio=True)
        self.assertEqual(tuple(out.shape), (8, 8, 4))
        # 2:1 source into 1:1 target => top/bottom bars are black.
        self.assertEqual(int(out[0, :, 0].sum().item()), 0)
        self.assertEqual(int(out[0, :, 1].sum().item()), 0)
        self.assertEqual(int(out[0, :, 2].sum().item()), 0)
        self.assertTrue(torch.all(out[0, :, 3] == 255))
        # Center row contains scaled content.
        self.assertGreater(int(out[4, :, 1].sum().item()), 0)

    def test_prepare_frame_rejects_invalid_target(self) -> None:
        frame = torch.zeros((2, 2, 4), dtype=torch.uint8)
        with self.assertRaises(ValueError):
            prepare_frame_for_extent(frame, target_w=0, target_h=2, preserve_aspect_ratio=True)


if __name__ == "__main__":
    unittest.main()
