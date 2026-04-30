from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from luvatrix_core.core.scene_graph import SceneFrame
from luvatrix_core.targets.base import RenderTarget


class SceneRenderTarget(Protocol):
    def start(self) -> None:
        ...

    def present_scene(self, frame: SceneFrame, target_present_time: float | None = None) -> None:
        ...

    def stop(self) -> None:
        ...

    def pump_events(self) -> None:
        ...

    def should_close(self) -> bool:
        ...


@dataclass
class SceneTargetAdapter(RenderTarget):
    """RenderTarget-compatible wrapper around a scene target.

    The matrix present path is intentionally unsupported; this adapter is used
    only so UnifiedRuntime can share lifecycle/event code while routing scene
    frames through present_scene().
    """

    scene_target: SceneRenderTarget
    _started: bool = False

    def start(self) -> None:
        if self._started:
            return
        self.scene_target.start()
        self._started = True

    def present_frame(self, frame) -> None:
        raise RuntimeError("SceneTargetAdapter does not accept DisplayFrame; use present_scene")

    def present_scene(self, frame: SceneFrame, target_present_time: float | None = None) -> None:
        if not self._started:
            raise RuntimeError("SceneTargetAdapter must be started before presenting scenes")
        self.scene_target.present_scene(frame, target_present_time=target_present_time)

    def stop(self) -> None:
        if not self._started:
            return
        self.scene_target.stop()
        self._started = False

    def pump_events(self) -> None:
        if self._started:
            self.scene_target.pump_events()

    def should_close(self) -> bool:
        if not self._started:
            return False
        return bool(self.scene_target.should_close())
