from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import threading
from typing import Protocol

import torch


class PresenterState(str, Enum):
    UNINITIALIZED = "uninitialized"
    READY = "ready"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class VulkanContext:
    width: int
    height: int
    title: str


class MacOSVulkanBackend(Protocol):
    def initialize(self, width: int, height: int, title: str) -> VulkanContext:
        ...

    def present(self, context: VulkanContext, rgba: torch.Tensor, revision: int) -> None:
        ...

    def resize(self, context: VulkanContext, width: int, height: int) -> VulkanContext:
        ...

    def shutdown(self, context: VulkanContext) -> None:
        ...

    def pump_events(self) -> None:
        ...

    def should_close(self) -> bool:
        ...


class StubMacOSVulkanBackend:
    def initialize(self, width: int, height: int, title: str) -> VulkanContext:
        raise NotImplementedError(
            "macOS Vulkan backend is not implemented yet. Planned pipeline: "
            "create Cocoa window + CAMetalLayer, create Vulkan instance/device/swapchain via MoltenVK, "
            "upload RGBA frame to Vulkan image, and present."
        )

    def present(self, context: VulkanContext, rgba: torch.Tensor, revision: int) -> None:
        raise NotImplementedError("macOS Vulkan frame presentation is not implemented yet.")

    def resize(self, context: VulkanContext, width: int, height: int) -> VulkanContext:
        raise NotImplementedError("macOS Vulkan resize is not implemented yet.")

    def shutdown(self, context: VulkanContext) -> None:
        raise NotImplementedError("macOS Vulkan shutdown is not implemented yet.")

    def pump_events(self) -> None:
        raise NotImplementedError("macOS Vulkan event pump is not implemented yet.")

    def should_close(self) -> bool:
        raise NotImplementedError("macOS Vulkan close-state handling is not implemented yet.")


@dataclass
class MacOSVulkanPresenter:
    width: int
    height: int
    title: str = "Luvatrix"
    preserve_aspect_ratio: bool = False
    backend: MacOSVulkanBackend | None = None
    max_dimension: int = 16384

    def __post_init__(self) -> None:
        self._lock = threading.RLock()
        self._state = PresenterState.UNINITIALIZED
        self._context: VulkanContext | None = None
        self._last_error: Exception | None = None
        if self.backend is None:
            from .vulkan_backend import MoltenVKMacOSBackend

            self.backend = MoltenVKMacOSBackend(preserve_aspect_ratio=self.preserve_aspect_ratio)
        self._validate_dimensions(self.width, self.height)

    @property
    def state(self) -> PresenterState:
        return self._state

    @property
    def last_error(self) -> Exception | None:
        return self._last_error

    def initialize(self) -> None:
        with self._lock:
            if self._state == PresenterState.READY:
                return
            if self._state == PresenterState.FAILED:
                raise RuntimeError("presenter is in FAILED state; create a new presenter instance")
            self._validate_dimensions(self.width, self.height)
            try:
                self._context = self.backend.initialize(self.width, self.height, self.title)
            except Exception as exc:  # noqa: BLE001
                self._state = PresenterState.FAILED
                self._last_error = exc
                raise RuntimeError("failed to initialize macOS Vulkan presenter") from exc
            self._state = PresenterState.READY

    def present_rgba(self, rgba: torch.Tensor, revision: int) -> None:
        with self._lock:
            if self._state != PresenterState.READY:
                raise RuntimeError(f"presenter must be READY to present frames (state={self._state.value})")
            assert self._context is not None
            self._validate_frame(rgba)
            try:
                self.backend.present(self._context, rgba, revision)
            except Exception as exc:  # noqa: BLE001
                self._state = PresenterState.FAILED
                self._last_error = exc
                raise RuntimeError("failed to present frame on macOS Vulkan presenter") from exc

    def resize(self, width: int, height: int) -> None:
        with self._lock:
            if self._state != PresenterState.READY:
                raise RuntimeError(f"presenter must be READY to resize (state={self._state.value})")
            assert self._context is not None
            self._validate_dimensions(width, height)
            try:
                self._context = self.backend.resize(self._context, width, height)
            except Exception as exc:  # noqa: BLE001
                self._state = PresenterState.FAILED
                self._last_error = exc
                raise RuntimeError("failed to resize macOS Vulkan presenter") from exc
            self.width = width
            self.height = height

    def shutdown(self) -> None:
        with self._lock:
            if self._state in (PresenterState.UNINITIALIZED, PresenterState.STOPPED):
                self._state = PresenterState.STOPPED
                return
            if self._context is not None:
                try:
                    self.backend.shutdown(self._context)
                finally:
                    self._context = None
            self._state = PresenterState.STOPPED

    def pump_events(self) -> None:
        with self._lock:
            if self._state != PresenterState.READY:
                return
            self.backend.pump_events()

    def should_close(self) -> bool:
        with self._lock:
            if self._state == PresenterState.STOPPED:
                return True
            if self._state != PresenterState.READY:
                return False
            return self.backend.should_close()

    def _validate_dimensions(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be > 0")
        if width > self.max_dimension or height > self.max_dimension:
            raise ValueError(
                f"width/height exceed max_dimension={self.max_dimension}: got {width}x{height}"
            )

    def _validate_frame(self, rgba: torch.Tensor) -> None:
        if not torch.is_tensor(rgba):
            raise ValueError("rgba frame must be a torch.Tensor")
        if rgba.dtype != torch.uint8:
            raise ValueError(f"rgba frame must use torch.uint8, got {rgba.dtype}")
        if rgba.ndim != 3:
            raise ValueError(f"rgba frame must have 3 dimensions, got {rgba.ndim}")
        if tuple(rgba.shape) != (self.height, self.width, 4):
            raise ValueError(
                f"rgba frame shape mismatch: got {tuple(rgba.shape)} expected {(self.height, self.width, 4)}"
            )
