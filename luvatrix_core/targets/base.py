from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from luvatrix_core.core.matrix_viewport import MatrixViewport

if TYPE_CHECKING:
    import torch


@dataclass(frozen=True)
class DisplayFrame:
    revision: int
    width: int
    height: int
    # ``None`` is valid only for a viewport-capable target and means its
    # resident Matrix texture is unchanged.
    rgba: torch.Tensor | None
    # ``None`` means the target must replace its entire backing surface.
    # Otherwise this is an (x, y, width, height) region within ``rgba``.
    dirty_rect: tuple[int, int, int, int] | None = None
    viewport: MatrixViewport | None = None


class RenderTarget(ABC):
    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def present_frame(self, frame: DisplayFrame) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    def pump_events(self) -> None:
        """Optional hook for targets that need explicit event pumping (for example AppKit)."""
        return

    def should_close(self) -> bool:
        """Optional hook for targets that expose window-close state."""
        return False

    def supports_matrix_viewport(self) -> bool:
        """Whether transform-only Matrix frames can reuse resident GPU pixels."""
        return False
