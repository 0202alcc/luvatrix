from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import threading
from typing import TYPE_CHECKING

import torch

from luvatrix_core.targets.metal_target import MetalBackend, MetalContext

if TYPE_CHECKING:
    from .metal_backend import MacOSMetalBackend


class PresenterState(str, Enum):
    UNINITIALIZED = "uninitialized"
    READY = "ready"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class MacOSMetalPresenter:
    width: int
    height: int
    title: str = "Luvatrix"
    backend: MetalBackend | None = None
    bar_color_rgba: tuple[int, int, int, int] = (0, 0, 0, 255)
    resizable: bool = True
    max_dimension: int = 16384

    def __post_init__(self) -> None:
        self._lock = threading.RLock()
        self._state = PresenterState.UNINITIALIZED
        self._context: MetalContext | None = None
        self._last_error: Exception | None = None
        if self.backend is None:
            from .metal_backend import MacOSMetalBackend
            self.backend = MacOSMetalBackend(
                bar_color_rgba=self.bar_color_rgba,
                resizable=self.resizable,
            )
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
                raise RuntimeError("failed to initialize macOS Metal presenter") from exc
            self._state = PresenterState.READY

    def present_rgba(self, rgba: torch.Tensor, revision: int) -> None:
        with self._lock:
            if self._state != PresenterState.READY:
                raise RuntimeError(
                    f"presenter must be READY to present frames (state={self._state.value})"
                )
            assert self._context is not None
            self._validate_frame(rgba)
            try:
                self.backend.present(self._context, rgba, revision)
            except Exception as exc:  # noqa: BLE001
                self._state = PresenterState.FAILED
                self._last_error = exc
                raise RuntimeError("failed to present frame on macOS Metal presenter") from exc

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

    def _validate_frame(self, rgba) -> None:
        if not (hasattr(rgba, "shape") and hasattr(rgba, "ndim")):
            raise ValueError("rgba frame must be an array with .shape and .ndim")
        if rgba.ndim != 3 or rgba.shape[2] != 4:
            raise ValueError(f"rgba frame must have shape (H, W, 4), got {tuple(rgba.shape)}")
