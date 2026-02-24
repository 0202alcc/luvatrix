from __future__ import annotations

import unittest

import torch

from luvatrix_core.platform.macos.vulkan_presenter import (
    MacOSVulkanPresenter,
    PresenterState,
    VulkanContext,
)


class _FakeBackend:
    def __init__(self) -> None:
        self.init_calls = 0
        self.present_calls = 0
        self.resize_calls = 0
        self.shutdown_calls = 0
        self.last_context: VulkanContext | None = None
        self.raise_on_init = False
        self.raise_on_present = False
        self.raise_on_resize = False
        self.pumped = 0
        self.close_state = False

    def initialize(self, width: int, height: int, title: str) -> VulkanContext:
        self.init_calls += 1
        if self.raise_on_init:
            raise RuntimeError("init failed")
        self.last_context = VulkanContext(width=width, height=height, title=title)
        return self.last_context

    def present(self, context: VulkanContext, rgba: torch.Tensor, revision: int) -> None:
        self.present_calls += 1
        if self.raise_on_present:
            raise RuntimeError("present failed")
        self.last_context = context

    def resize(self, context: VulkanContext, width: int, height: int) -> VulkanContext:
        self.resize_calls += 1
        if self.raise_on_resize:
            raise RuntimeError("resize failed")
        self.last_context = VulkanContext(width=width, height=height, title=context.title)
        return self.last_context

    def shutdown(self, context: VulkanContext) -> None:
        self.shutdown_calls += 1
        self.last_context = context

    def pump_events(self) -> None:
        self.pumped += 1

    def should_close(self) -> bool:
        return self.close_state


class MacOSVulkanPresenterTests(unittest.TestCase):
    def test_lifecycle_happy_path(self) -> None:
        backend = _FakeBackend()
        presenter = MacOSVulkanPresenter(width=2, height=2, backend=backend)
        presenter.initialize()
        presenter.present_rgba(torch.zeros((2, 2, 4), dtype=torch.uint8), revision=1)
        presenter.shutdown()

        self.assertEqual(backend.init_calls, 1)
        self.assertEqual(backend.present_calls, 1)
        self.assertEqual(backend.shutdown_calls, 1)
        self.assertEqual(presenter.state, PresenterState.STOPPED)

    def test_initialize_is_idempotent_when_ready(self) -> None:
        backend = _FakeBackend()
        presenter = MacOSVulkanPresenter(width=2, height=2, backend=backend)
        presenter.initialize()
        presenter.initialize()
        self.assertEqual(backend.init_calls, 1)

    def test_present_before_initialize_raises(self) -> None:
        presenter = MacOSVulkanPresenter(width=2, height=2, backend=_FakeBackend())
        with self.assertRaises(RuntimeError):
            presenter.present_rgba(torch.zeros((2, 2, 4), dtype=torch.uint8), revision=1)

    def test_shutdown_is_safe_without_initialize(self) -> None:
        backend = _FakeBackend()
        presenter = MacOSVulkanPresenter(width=2, height=2, backend=backend)
        presenter.shutdown()
        presenter.shutdown()
        self.assertEqual(backend.shutdown_calls, 0)
        self.assertEqual(presenter.state, PresenterState.STOPPED)

    def test_invalid_frame_dtype_is_rejected(self) -> None:
        backend = _FakeBackend()
        presenter = MacOSVulkanPresenter(width=2, height=2, backend=backend)
        presenter.initialize()
        with self.assertRaises(ValueError):
            presenter.present_rgba(torch.zeros((2, 2, 4), dtype=torch.float32), revision=1)
        self.assertEqual(backend.present_calls, 0)

    def test_invalid_frame_shape_is_rejected(self) -> None:
        backend = _FakeBackend()
        presenter = MacOSVulkanPresenter(width=2, height=2, backend=backend)
        presenter.initialize()
        with self.assertRaises(ValueError):
            presenter.present_rgba(torch.zeros((1, 2, 4), dtype=torch.uint8), revision=1)
        self.assertEqual(backend.present_calls, 0)

    def test_initialize_failure_transitions_to_failed(self) -> None:
        backend = _FakeBackend()
        backend.raise_on_init = True
        presenter = MacOSVulkanPresenter(width=2, height=2, backend=backend)
        with self.assertRaises(RuntimeError):
            presenter.initialize()
        self.assertEqual(presenter.state, PresenterState.FAILED)
        self.assertIsNotNone(presenter.last_error)

    def test_present_failure_transitions_to_failed(self) -> None:
        backend = _FakeBackend()
        backend.raise_on_present = True
        presenter = MacOSVulkanPresenter(width=2, height=2, backend=backend)
        presenter.initialize()
        with self.assertRaises(RuntimeError):
            presenter.present_rgba(torch.zeros((2, 2, 4), dtype=torch.uint8), revision=1)
        self.assertEqual(presenter.state, PresenterState.FAILED)
        self.assertIsNotNone(presenter.last_error)

    def test_resize_updates_dimensions(self) -> None:
        backend = _FakeBackend()
        presenter = MacOSVulkanPresenter(width=2, height=2, backend=backend)
        presenter.initialize()
        presenter.resize(3, 4)
        self.assertEqual(backend.resize_calls, 1)
        self.assertEqual(presenter.width, 3)
        self.assertEqual(presenter.height, 4)

    def test_resize_failure_transitions_to_failed(self) -> None:
        backend = _FakeBackend()
        backend.raise_on_resize = True
        presenter = MacOSVulkanPresenter(width=2, height=2, backend=backend)
        presenter.initialize()
        with self.assertRaises(RuntimeError):
            presenter.resize(3, 3)
        self.assertEqual(presenter.state, PresenterState.FAILED)

    def test_dimension_limits_enforced(self) -> None:
        with self.assertRaises(ValueError):
            MacOSVulkanPresenter(width=0, height=2, backend=_FakeBackend())
        with self.assertRaises(ValueError):
            MacOSVulkanPresenter(width=2, height=20000, backend=_FakeBackend())

    def test_presenter_default_backend_inherits_aspect_ratio_setting(self) -> None:
        presenter = MacOSVulkanPresenter(width=2, height=2, preserve_aspect_ratio=True)
        self.assertTrue(bool(getattr(presenter.backend, "preserve_aspect_ratio", False)))

    def test_pump_and_should_close_delegate_to_backend(self) -> None:
        backend = _FakeBackend()
        presenter = MacOSVulkanPresenter(width=2, height=2, backend=backend)
        presenter.initialize()
        presenter.pump_events()
        self.assertEqual(backend.pumped, 1)
        self.assertFalse(presenter.should_close())
        backend.close_state = True
        self.assertTrue(presenter.should_close())


if __name__ == "__main__":
    unittest.main()
