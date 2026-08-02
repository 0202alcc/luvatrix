from __future__ import annotations

from dataclasses import dataclass

from luvatrix_core import accel
from luvatrix_core.core.matrix_viewport import MatrixViewport
from luvatrix_core.targets.base import DisplayFrame, RenderTarget


@dataclass
class AndroidVulkanBridge:
    """Protocol-like wrapper for the Kotlin/JNI Vulkan bridge."""

    presenter: object

    def supports_rgba_region(self) -> bool:
        method = getattr(self.presenter, "presentRgbaRegion", None) or getattr(self.presenter, "present_rgba_region", None)
        return callable(method)

    def supports_matrix_viewport(self) -> bool:
        return all(
            callable(getattr(self.presenter, name, None)) or callable(getattr(self.presenter, snake, None))
            for name, snake in (
                ("presentViewport", "present_viewport"),
                ("presentRgbaViewport", "present_rgba_viewport"),
            )
        )

    def supports_rgba_region_viewport(self) -> bool:
        method = getattr(self.presenter, "presentRgbaRegionViewport", None) or getattr(
            self.presenter, "present_rgba_region_viewport", None
        )
        return callable(method)

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

    def present_rgba_region(
        self,
        rgba: object,
        revision: int,
        source_width: int,
        source_height: int,
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> None:
        method = getattr(self.presenter, "presentRgbaRegion", None) or getattr(self.presenter, "present_rgba_region", None)
        if not callable(method):
            raise RuntimeError("Android Vulkan bridge must expose presentRgbaRegion/present_rgba_region")
        contiguous = accel.to_contiguous_numpy(rgba)
        if hasattr(contiguous, "tobytes"):
            payload = contiguous.tobytes()
        elif hasattr(contiguous, "_data"):
            payload = bytes(contiguous._data)
        else:
            payload = bytes(contiguous)
        method(payload, int(revision), int(source_width), int(source_height), int(x), int(y), int(width), int(height))

    def present_viewport(self, revision: int, source_width: int, source_height: int, viewport: MatrixViewport) -> None:
        method = getattr(self.presenter, "presentViewport", None) or getattr(self.presenter, "present_viewport", None)
        if not callable(method):
            raise RuntimeError("Android Vulkan bridge must expose presentViewport/present_viewport")
        method(int(revision), int(source_width), int(source_height), int(viewport.x), int(viewport.y), int(viewport.width), int(viewport.height), bool(viewport.wrap_x), bool(viewport.wrap_y))

    def present_rgba_viewport(self, rgba: object, revision: int, source_width: int, source_height: int, viewport: MatrixViewport) -> None:
        method = getattr(self.presenter, "presentRgbaViewport", None) or getattr(self.presenter, "present_rgba_viewport", None)
        if not callable(method):
            raise RuntimeError("Android Vulkan bridge must expose presentRgbaViewport/present_rgba_viewport")
        method(_rgba_bytes(rgba), int(revision), int(source_width), int(source_height), int(viewport.x), int(viewport.y), int(viewport.width), int(viewport.height), bool(viewport.wrap_x), bool(viewport.wrap_y))

    def present_rgba_region_viewport(
        self,
        rgba: object,
        revision: int,
        source_width: int,
        source_height: int,
        x: int,
        y: int,
        width: int,
        height: int,
        viewport: MatrixViewport,
    ) -> None:
        method = getattr(self.presenter, "presentRgbaRegionViewport", None) or getattr(
            self.presenter, "present_rgba_region_viewport", None
        )
        if not callable(method):
            raise RuntimeError("Android Vulkan bridge must expose presentRgbaRegionViewport/present_rgba_region_viewport")
        method(_rgba_bytes(rgba), int(revision), int(source_width), int(source_height), int(x), int(y), int(width), int(height), int(viewport.x), int(viewport.y), int(viewport.width), int(viewport.height), bool(viewport.wrap_x), bool(viewport.wrap_y))


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

    def supports_matrix_viewport(self) -> bool:
        return self._bridge.supports_matrix_viewport()

    def present_frame(self, frame: DisplayFrame) -> None:
        if not self._started:
            raise RuntimeError("AndroidVulkanTarget.present_frame called before start")
        if frame.rgba is None:
            if frame.viewport is None or not self.supports_matrix_viewport():
                raise ValueError("rgba may be omitted only for a supported Matrix viewport frame")
            self._bridge.present_viewport(frame.revision, frame.width, frame.height, frame.viewport)
            self.frames_presented += 1
            self.last_revision = int(frame.revision)
            return
        shape = getattr(frame.rgba, "shape", None)
        if tuple(shape or ()) != (frame.height, frame.width, 4):
            raise ValueError(f"rgba shape must be {(frame.height, frame.width, 4)}, got {shape!r}")
        if frame.viewport is not None and self.supports_matrix_viewport():
            dirty_rect = frame.dirty_rect
            if dirty_rect is not None and self._bridge.supports_rgba_region_viewport():
                x, y, width, height = (int(value) for value in dirty_rect)
                if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > frame.width or y + height > frame.height:
                    raise ValueError(f"dirty_rect {dirty_rect!r} exceeds frame bounds")
                self._bridge.present_rgba_region_viewport(
                    frame.rgba[y : y + height, x : x + width, :],
                    frame.revision,
                    frame.width,
                    frame.height,
                    x,
                    y,
                    width,
                    height,
                    frame.viewport,
                )
            else:
                self._bridge.present_rgba_viewport(frame.rgba, frame.revision, frame.width, frame.height, frame.viewport)
            self.frames_presented += 1
            self.last_revision = int(frame.revision)
            return
        dirty_rect = frame.dirty_rect
        if dirty_rect is not None and self._bridge.supports_rgba_region():
            x, y, width, height = (int(value) for value in dirty_rect)
            if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > frame.width or y + height > frame.height:
                raise ValueError(f"dirty_rect {dirty_rect!r} exceeds frame bounds")
            self._bridge.present_rgba_region(
                frame.rgba[y : y + height, x : x + width, :],
                frame.revision,
                frame.width,
                frame.height,
                x,
                y,
                width,
                height,
            )
        else:
            self._bridge.present_rgba(frame.rgba, frame.revision, frame.width, frame.height)
        self.frames_presented += 1
        self.last_revision = int(frame.revision)


def _rgba_bytes(rgba: object) -> bytes:
    contiguous = accel.to_contiguous_numpy(rgba)
    if hasattr(contiguous, "tobytes"):
        return contiguous.tobytes()
    if hasattr(contiguous, "_data"):
        return bytes(contiguous._data)
    return bytes(contiguous)
