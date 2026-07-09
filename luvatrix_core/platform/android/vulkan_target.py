from __future__ import annotations

from dataclasses import dataclass

from luvatrix_core import accel
from luvatrix_core.targets.base import DisplayFrame, RenderTarget


@dataclass
class AndroidVulkanBridge:
    """Protocol-like wrapper for the Kotlin/JNI Vulkan bridge."""

    presenter: object

    def present_rgba(self, rgba: object, revision: int, width: int, height: int) -> None:
        method = getattr(self.presenter, "presentRgba", None) or getattr(self.presenter, "present_rgba", None)
        if not callable(method):
            raise RuntimeError("Android Vulkan bridge must expose presentRgba/present_rgba")
        contiguous = accel.to_contiguous_numpy(rgba)
        if hasattr(contiguous, "tobytes"):
            payload = contiguous.tobytes()
        elif hasattr(contiguous, "_data"):
            payload = bytes(contiguous._data)
        else:
            payload = bytes(contiguous)
        method(payload, int(revision), int(width), int(height))


class AndroidVulkanTarget(RenderTarget):
    def __init__(self, bridge: AndroidVulkanBridge) -> None:
        self._bridge = bridge
        self._started = False
        self.frames_presented = 0
        self.last_revision: int | None = None

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False

    def present_frame(self, frame: DisplayFrame) -> None:
        if not self._started:
            raise RuntimeError("AndroidVulkanTarget.present_frame called before start")
        shape = getattr(frame.rgba, "shape", None)
        if tuple(shape or ()) != (frame.height, frame.width, 4):
            raise ValueError(f"rgba shape must be {(frame.height, frame.width, 4)}, got {shape!r}")
        self._bridge.present_rgba(frame.rgba, frame.revision, frame.width, frame.height)
        self.frames_presented += 1
        self.last_revision = int(frame.revision)
