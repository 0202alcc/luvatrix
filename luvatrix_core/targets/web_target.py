from __future__ import annotations

from .base import DisplayFrame, RenderTarget


class WebTarget(RenderTarget):
    def start(self) -> None:
        raise NotImplementedError("Web target is not implemented yet.")

    def present_frame(self, frame: DisplayFrame) -> None:
        raise NotImplementedError("Web target is not implemented yet.")

    def stop(self) -> None:
        raise NotImplementedError("Web target is not implemented yet.")
