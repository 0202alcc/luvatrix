from __future__ import annotations

import unittest

from luvatrix_core import accel
from luvatrix_core.platform.android.vulkan_target import AndroidVulkanBridge, AndroidVulkanTarget
from luvatrix_core.core.matrix_viewport import MatrixViewport
from luvatrix_core.targets.base import DisplayFrame


class _Presenter:
    def __init__(self) -> None:
        self.calls = []

    def present_rgba(self, rgba, revision: int, width: int, height: int) -> None:
        self.calls.append((rgba, revision, width, height))


class _RegionPresenter(_Presenter):
    def __init__(self) -> None:
        super().__init__()
        self.region_calls = []

    def present_rgba_region(
        self,
        rgba,
        revision: int,
        source_width: int,
        source_height: int,
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> None:
        self.region_calls.append((rgba, revision, source_width, source_height, x, y, width, height))


class _ViewportPresenter(_RegionPresenter):
    def __init__(self) -> None:
        super().__init__()
        self.viewport_calls = []
        self.viewport_rgba_calls = []
        self.viewport_region_calls = []

    def present_viewport(self, revision, source_width, source_height, x, y, width, height, wrap_x, wrap_y) -> None:
        self.viewport_calls.append((revision, source_width, source_height, x, y, width, height, wrap_x, wrap_y))

    def present_rgba_viewport(self, rgba, revision, source_width, source_height, x, y, width, height, wrap_x, wrap_y) -> None:
        self.viewport_rgba_calls.append((rgba, revision, source_width, source_height, x, y, width, height, wrap_x, wrap_y))

    def present_rgba_region_viewport(self, rgba, revision, source_width, source_height, x, y, width, height, viewport_x, viewport_y, viewport_width, viewport_height, wrap_x, wrap_y) -> None:
        self.viewport_region_calls.append((rgba, revision, source_width, source_height, x, y, width, height, viewport_x, viewport_y, viewport_width, viewport_height, wrap_x, wrap_y))


class AndroidVulkanTargetTests(unittest.TestCase):
    def test_viewport_only_frame_uses_resident_gpu_texture_without_rgba_upload(self) -> None:
        presenter = _ViewportPresenter()
        target = AndroidVulkanTarget(AndroidVulkanBridge(presenter))
        target.start()
        viewport = MatrixViewport(x=0, y=2, width=2, height=2, wrap_y=True)

        target.present_frame(DisplayFrame(revision=7, width=2, height=4, rgba=None, viewport=viewport))

        self.assertEqual(presenter.calls, [])
        self.assertEqual(presenter.region_calls, [])
        self.assertEqual(presenter.viewport_calls, [(7, 2, 4, 0, 2, 2, 2, False, True)])

    def test_dirty_viewport_frame_uses_native_partial_upload(self) -> None:
        presenter = _ViewportPresenter()
        target = AndroidVulkanTarget(AndroidVulkanBridge(presenter))
        target.start()
        rgba = accel.from_sequence(list(range(32)), (4, 2, 4))
        viewport = MatrixViewport(x=0, y=1, width=2, height=2)

        target.present_frame(DisplayFrame(revision=8, width=2, height=4, rgba=rgba, dirty_rect=(1, 2, 1, 1), viewport=viewport))

        self.assertEqual(presenter.calls, [])
        self.assertEqual(presenter.viewport_rgba_calls, [])
        self.assertEqual(presenter.viewport_region_calls[0][1:], (8, 2, 4, 1, 2, 1, 1, 0, 1, 2, 2, False, False))
        self.assertEqual(presenter.viewport_region_calls[0][0], bytes([20, 21, 22, 23]))

    def test_present_frame_forwards_only_dirty_region_when_presenter_supports_it(self) -> None:
        presenter = _RegionPresenter()
        target = AndroidVulkanTarget(AndroidVulkanBridge(presenter))
        target.start()
        rgba = accel.from_sequence(list(range(16)), (2, 2, 4))

        target.present_frame(
            DisplayFrame(revision=7, width=2, height=2, rgba=rgba, dirty_rect=(1, 0, 1, 2))
        )

        self.assertEqual(presenter.calls, [])
        self.assertEqual(presenter.region_calls[0][1:], (7, 2, 2, 1, 0, 1, 2))
        self.assertEqual(presenter.region_calls[0][0], bytes([4, 5, 6, 7, 12, 13, 14, 15]))

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

    def test_present_frame_forwards_rgba_bytes(self) -> None:
        presenter = _Presenter()
        target = AndroidVulkanTarget(AndroidVulkanBridge(presenter))
        target.start()
        rgba = accel.from_sequence([10, 20, 30, 40], (1, 1, 4))

        target.present_frame(DisplayFrame(revision=4, width=1, height=1, rgba=rgba))

        self.assertEqual(presenter.calls[0][0], bytes([10, 20, 30, 40]))

    def test_present_frame_rejects_shape_mismatch(self) -> None:
        target = AndroidVulkanTarget(AndroidVulkanBridge(_Presenter()))
        target.start()

        with self.assertRaisesRegex(ValueError, "rgba shape"):
            target.present_frame(DisplayFrame(revision=1, width=2, height=2, rgba=accel.zeros((1, 2, 4))))


if __name__ == "__main__":
    unittest.main()
