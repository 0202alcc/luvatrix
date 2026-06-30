from __future__ import annotations

import math

from luvatrix.app import App


class CubeDemo(App):
    def setup(self) -> None:
        self.t = 0.0

    def update(self, dt: float) -> None:
        self.t += float(dt)

    def render(self) -> None:
        with self.frame(clear=(8, 12, 20, 255)) as frame:
            frame.camera3d(position=(0.0, 1.2, 4.5), target=(0.0, 0.0, 0.0), fov_deg=52.0)
            frame.cube3d(
                center=(0.0, 0.0, 0.0),
                size=1.7,
                rotation=(self.t * 0.8, self.t * 1.1, math.sin(self.t) * 0.25),
                color=(72, 176, 255, 255),
                edge=(245, 250, 255, 255),
            )
            frame.rect(x=28, y=26, width=272, height=54, color=(2, 6, 14, 180), z_index=10)
            frame.text("Luvatrix 3D cube", x=44, y=42, font_size_px=20, color=(235, 246, 255, 255), z_index=11)


def create() -> CubeDemo:
    return CubeDemo()
