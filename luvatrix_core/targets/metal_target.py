from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import torch

from .base import DisplayFrame, RenderTarget


@dataclass
class MetalContext:
    width: int
    height: int
    title: str


class MetalBackend(Protocol):
    def initialize(self, width: int, height: int, title: str) -> MetalContext:
        ...

    def present(self, context: MetalContext, rgba: torch.Tensor, revision: int) -> None:
        ...

    def shutdown(self, context: MetalContext) -> None:
        ...

    def pump_events(self) -> None:
        ...

    def should_close(self) -> bool:
        ...


class MetalPresenter(Protocol):
    def initialize(self) -> None:
        ...

    def present_rgba(self, rgba: torch.Tensor, revision: int) -> None:
        ...

    def shutdown(self) -> None:
        ...

    def pump_events(self) -> None:
        ...

    def should_close(self) -> bool:
        ...


@dataclass
class MetalTarget(RenderTarget):
    presenter: MetalPresenter
    _started: bool = False

    def start(self) -> None:
        if self._started:
            return
        self.presenter.initialize()
        self._started = True

    def present_frame(self, frame: DisplayFrame) -> None:
        if not self._started:
            raise RuntimeError("MetalTarget must be started before presenting frames")
        self.presenter.present_rgba(frame.rgba, revision=frame.revision)

    def stop(self) -> None:
        if not self._started:
            return
        self.presenter.shutdown()
        self._started = False

    def pump_events(self) -> None:
        if not self._started:
            return
        if hasattr(self.presenter, "pump_events"):
            self.presenter.pump_events()

    def should_close(self) -> bool:
        if not self._started:
            return False
        if hasattr(self.presenter, "should_close"):
            return bool(self.presenter.should_close())
        return False
