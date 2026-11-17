from __future__ import annotations

from dataclasses import dataclass

from luvatrix_core.core.scene_graph import SceneFrame
from luvatrix_core.core.scene_rasterizer import rasterize_scene_frame
from luvatrix_core.targets.base import DisplayFrame, RenderTarget
from luvatrix_core.targets.scene_target import SceneRenderTarget


@dataclass
class CpuSceneTarget(SceneRenderTarget):
    """SceneRenderTarget that rasterizes a retained scene and forwards it to a matrix target."""

    target: RenderTarget
    _started: bool = False
    _raster_buffer: object = None
    _last_backing_scale: float = 1.0

    def backing_scale(self) -> float:
        """Display/logical pixel ratio of the last presented frame."""
        return float(self._last_backing_scale)

    def start(self) -> None:
        if self._started:
            return
        self.target.start()
        self._started = True

    def present_scene(self, frame: SceneFrame, target_present_time: float | None = None) -> None:
        _ = target_present_time
        if not self._started:
            raise RuntimeError("CpuSceneTarget must be started before presenting scenes")

        logical = max(1, int(frame.logical_width))
        self._last_backing_scale = max(0.05, float(frame.display_width) / float(logical))
        self._raster_buffer = rasterize_scene_frame(frame, out=self._raster_buffer)
        rgba = self._raster_buffer

        self.target.present_frame(
            DisplayFrame(
                revision=frame.revision,
                width=frame.display_width,
                height=frame.display_height,
                rgba=rgba,
            )
        )

    def stop(self) -> None:
        if not self._started:
            return
        self.target.stop()
        self._started = False

    def pump_events(self) -> None:
        self.target.pump_events()

    def should_close(self) -> bool:
        return self.target.should_close()
