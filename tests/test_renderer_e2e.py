from __future__ import annotations

import unittest

import torch

from luvatrix_core.core.display_runtime import DisplayRuntime
from luvatrix_core.core.window_matrix import FullRewrite, WindowMatrix, WriteBatch
from luvatrix_core.platform.macos.vulkan_presenter import MacOSVulkanPresenter, VulkanContext
from luvatrix_core.targets.vulkan_target import VulkanTarget


class _RecordingBackend:
    def __init__(self) -> None:
        self.initialized = 0
        self.presented: list[tuple[int, torch.Tensor]] = []
        self.shutdowns = 0

    def initialize(self, width: int, height: int, title: str) -> VulkanContext:
        self.initialized += 1
        return VulkanContext(width=width, height=height, title=title)

    def present(self, context: VulkanContext, rgba: torch.Tensor, revision: int) -> None:
        self.presented.append((revision, rgba.clone()))

    def resize(self, context: VulkanContext, width: int, height: int) -> VulkanContext:
        return VulkanContext(width=width, height=height, title=context.title)

    def shutdown(self, context: VulkanContext) -> None:
        self.shutdowns += 1

    def pump_events(self) -> None:
        return

    def should_close(self) -> bool:
        return False


class RendererE2ETests(unittest.TestCase):
    def test_display_runtime_to_macos_presenter_path(self) -> None:
        matrix = WindowMatrix(height=2, width=2)
        backend = _RecordingBackend()
        presenter = MacOSVulkanPresenter(width=2, height=2, backend=backend)
        target = VulkanTarget(presenter=presenter)
        runtime = DisplayRuntime(matrix=matrix, target=target)
        runtime.start()
        try:
            payload = torch.tensor(
                [
                    [[10, 20, 30, 255], [40, 50, 60, 255]],
                    [[70, 80, 90, 255], [100, 110, 120, 255]],
                ],
                dtype=torch.uint8,
            )
            matrix.submit_write_batch(WriteBatch([FullRewrite(payload)]))
            tick = runtime.run_once(timeout=0.01)
        finally:
            runtime.stop()
        self.assertIsNotNone(tick)
        self.assertEqual(backend.initialized, 1)
        self.assertEqual(backend.shutdowns, 1)
        self.assertEqual(len(backend.presented), 1)
        self.assertEqual(backend.presented[0][0], 1)
        self.assertTrue(torch.equal(backend.presented[0][1], payload))


if __name__ == "__main__":
    unittest.main()
