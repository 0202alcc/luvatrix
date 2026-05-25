from __future__ import annotations

import unittest

from luvatrix_core import accel
from luvatrix_core.platform.android.vulkan_target import AndroidVulkanBridge, AndroidVulkanTarget
from luvatrix_core.targets.base import DisplayFrame


class _Presenter:
    def __init__(self) -> None:
        self.calls = []

    def present_rgba(self, rgba, revision: int, width: int, height: int) -> None:
        self.calls.append((rgba, revision, width, height))


class AndroidVulkanTargetTests(unittest.TestCase):
    def test_present_frame_requires_start(self) -> None:
        target = AndroidVulkanTarget(AndroidVulkanBridge(_Presenter()))
        frame = DisplayFrame(revision=1, width=2, height=2, rgba=accel.zeros((2, 2, 4)))

        with self.assertRaisesRegex(RuntimeError, "before start"):
            target.present_frame(frame)

    def test_present_frame_validates_shape_and_forwards(self) -> None:
        presenter = _Presenter()
        target = AndroidVulkanTarget(AndroidVulkanBridge(presenter))
        target.start()

        target.present_frame(DisplayFrame(revision=3, width=2, height=2, rgba=accel.zeros((2, 2, 4))))

        self.assertEqual(target.frames_presented, 1)
        self.assertEqual(target.last_revision, 3)
        self.assertEqual(presenter.calls[0][1:], (3, 2, 2))
        self.assertIsInstance(presenter.calls[0][0], bytes)
        self.assertEqual(len(presenter.calls[0][0]), 16)

    def test_present_frame_converts_rgba_to_android_bgra_bytes(self) -> None:
        presenter = _Presenter()
        target = AndroidVulkanTarget(AndroidVulkanBridge(presenter))
        target.start()
        rgba = accel.from_sequence([10, 20, 30, 40], (1, 1, 4))

        target.present_frame(DisplayFrame(revision=4, width=1, height=1, rgba=rgba))

        self.assertEqual(presenter.calls[0][0], bytes([30, 20, 10, 40]))

    def test_present_frame_rejects_shape_mismatch(self) -> None:
        target = AndroidVulkanTarget(AndroidVulkanBridge(_Presenter()))
        target.start()

        with self.assertRaisesRegex(ValueError, "rgba shape"):
            target.present_frame(DisplayFrame(revision=1, width=2, height=2, rgba=accel.zeros((1, 2, 4))))


if __name__ == "__main__":
    unittest.main()
