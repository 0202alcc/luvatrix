from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import torch


@dataclass(frozen=True)
class DisplayFrame:
    revision: int
    width: int
    height: int
    rgba: torch.Tensor


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
