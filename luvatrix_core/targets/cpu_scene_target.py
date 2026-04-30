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

    def start(self) -> None:
        if self._started:
            return
        self.target.start()
        self._started = True

    def present_scene(self, frame: SceneFrame) -> None:
        if not self._started:
            raise RuntimeError("CpuSceneTarget must be started before presenting scenes")
        
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
