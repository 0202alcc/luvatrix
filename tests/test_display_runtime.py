from __future__ import annotations

import unittest
import torch

from luvatrix_core.core.display_runtime import DisplayRuntime
from luvatrix_core.core.window_matrix import FullRewrite, WindowMatrix, WriteBatch
from luvatrix_core.targets.base import DisplayFrame
from luvatrix_core.targets.vulkan_target import VulkanTarget
from luvatrix_core.targets.web_target import WebTarget


class _FakePresenter:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.presented: list[tuple[int, torch.Tensor]] = []
        self.pumped = 0
        self.closed = False

    def initialize(self) -> None:
        self.started += 1

    def present_rgba(self, rgba: torch.Tensor, revision: int) -> None:
        self.presented.append((revision, rgba.clone()))

    def shutdown(self) -> None:
        self.stopped += 1

    def pump_events(self) -> None:
        self.pumped += 1

    def should_close(self) -> bool:
        return self.closed


class _CloseAwareTarget:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.pumped = 0

    def start(self) -> None:
        self.started += 1

    def present_frame(self, frame: DisplayFrame) -> None:
        return

    def stop(self) -> None:
        self.stopped += 1

    def pump_events(self) -> None:
        self.pumped += 1

    def should_close(self) -> bool:
        return self.pumped >= 3


class DisplayRuntimeTests(unittest.TestCase):
    def test_run_once_presents_committed_frame(self) -> None:
        matrix = WindowMatrix(height=2, width=2)
        presenter = _FakePresenter()
        target = VulkanTarget(presenter=presenter)
        runtime = DisplayRuntime(matrix=matrix, target=target)
        target.start()
        payload = torch.tensor(
            [
                [[1, 2, 3, 255], [4, 5, 6, 255]],
                [[7, 8, 9, 255], [10, 11, 12, 255]],
            ],
            dtype=torch.uint8,
        )
        matrix.submit_write_batch(WriteBatch([FullRewrite(payload)]))
        tick = runtime.run_once(timeout=0.01)
        target.stop()

        self.assertIsNotNone(tick)
        assert tick is not None
        self.assertEqual(tick.event.revision, 1)
        self.assertEqual(tick.frame.revision, 1)
        self.assertEqual(presenter.started, 1)
        self.assertEqual(presenter.stopped, 1)
        self.assertEqual(len(presenter.presented), 1)
        self.assertTrue(torch.equal(presenter.presented[0][1], payload))

    def test_run_once_without_event_returns_none(self) -> None:
        matrix = WindowMatrix(height=1, width=1)
        presenter = _FakePresenter()
        target = VulkanTarget(presenter=presenter)
        runtime = DisplayRuntime(matrix=matrix, target=target)
        target.start()
        tick = runtime.run_once(timeout=0.01)
        target.stop()
        self.assertIsNone(tick)
        self.assertEqual(len(presenter.presented), 0)

    def test_vulkan_target_requires_start(self) -> None:
        presenter = _FakePresenter()
        target = VulkanTarget(presenter=presenter)
        with self.assertRaises(RuntimeError):
            target.present_frame(
                DisplayFrame(
                    revision=1,
                    width=1,
                    height=1,
                    rgba=torch.zeros((1, 1, 4), dtype=torch.uint8),
                )
            )

    def test_web_target_raises_not_implemented(self) -> None:
        target = WebTarget()
        with self.assertRaises(NotImplementedError):
            target.start()

    def test_run_once_coalesces_to_latest_revision(self) -> None:
        matrix = WindowMatrix(height=1, width=1)
        presenter = _FakePresenter()
        target = VulkanTarget(presenter=presenter)
        runtime = DisplayRuntime(matrix=matrix, target=target)
        target.start()
        matrix.submit_write_batch(
            WriteBatch([FullRewrite(torch.tensor([[[1, 0, 0, 255]]], dtype=torch.uint8))])
        )
        matrix.submit_write_batch(
            WriteBatch([FullRewrite(torch.tensor([[[2, 0, 0, 255]]], dtype=torch.uint8))])
        )
        tick = runtime.run_once(timeout=0.01)
        target.stop()

        self.assertIsNotNone(tick)
        assert tick is not None
        self.assertEqual(tick.event.revision, 2)
        self.assertEqual(tick.frame.revision, 2)
        self.assertEqual(tick.frame.rgba[0, 0, 0].item(), 2)
        self.assertEqual(matrix.pending_call_blit_count(), 0)

    def test_run_main_thread_stops_when_target_closes(self) -> None:
        matrix = WindowMatrix(height=1, width=1)
        target = _CloseAwareTarget()
        runtime = DisplayRuntime(matrix=matrix, target=target)

        runtime.run_main_thread(timeout=0.0, idle_sleep=0.0)

        self.assertEqual(target.started, 1)
        self.assertEqual(target.stopped, 1)
        self.assertGreaterEqual(target.pumped, 3)

    def test_run_main_thread_rejects_negative_idle_sleep(self) -> None:
        matrix = WindowMatrix(height=1, width=1)
        presenter = _FakePresenter()
        target = VulkanTarget(presenter=presenter)
        runtime = DisplayRuntime(matrix=matrix, target=target)

        with self.assertRaises(ValueError):
            runtime.run_main_thread(idle_sleep=-0.01)

    def test_vulkan_target_delegates_pump_and_close(self) -> None:
        presenter = _FakePresenter()
        target = VulkanTarget(presenter=presenter)
        self.assertFalse(target.should_close())
        target.start()
        target.pump_events()
        self.assertEqual(presenter.pumped, 1)
        self.assertFalse(target.should_close())
        presenter.closed = True
        self.assertTrue(target.should_close())
        target.stop()


if __name__ == "__main__":
    unittest.main()
