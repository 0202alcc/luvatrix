from __future__ import annotations

import math

import numpy as np

from luvatrix_plot import figure


class PlotDemoApp:
    def __init__(self) -> None:
        self._t = 0.0
        self._values = np.zeros(240, dtype=np.float64)

    def init(self, ctx) -> None:
        self._t = 0.0

    def loop(self, ctx, dt: float) -> None:
        self._t += max(0.0, dt)
        x = self._t
        next_value = (
            0.65 * math.sin(2.5 * x)
            + 0.35 * math.cos(1.3 * x)
            + 0.15 * math.sin(9.0 * x)
        )
        self._values = np.roll(self._values, -1)
        self._values[-1] = next_value

        snap = ctx.read_matrix_snapshot()
        h, w, _ = snap.shape

        fig = figure(width=w, height=h)
        ax = fig.axes(
            title="Luvatrix Plot Demo",
            x_label_bottom="sample",
            y_label_left="signal",
        )
        ax.set_limit_hysteresis(enabled=True, deadband_ratio=0.12, shrink_rate=0.06)
        ax.plot(y=self._values, color=(255, 170, 70), width=1)
        ax.scatter(y=self._values, color=(90, 190, 255), size=1, alpha=0.8)

        ctx.submit_write_batch(fig.compile_write_batch())

    def stop(self, ctx) -> None:
        return None


def create() -> PlotDemoApp:
    return PlotDemoApp()
