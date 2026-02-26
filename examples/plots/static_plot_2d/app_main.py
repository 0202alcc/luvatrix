from __future__ import annotations

import numpy as np

from luvatrix_plot import figure


class StaticPlot2DApp:
    def __init__(self) -> None:
        # Static 2-D path (x and y both explicit).
        self._x = np.asarray(
            [
                -4.0,
                -3.5,
                -3.0,
                -2.5,
                -2.0,
                -1.5,
                -1.0,
                -0.5,
                0.0,
                0.5,
                1.0,
                1.5,
                2.0,
                2.5,
                3.0,
                3.5,
                4.0,
            ],
            dtype=np.float64,
        )
        self._y = np.asarray(
            [
                1.5,
                2.2,
                2.9,
                3.4,
                3.8,
                4.1,
                4.3,
                4.4,
                4.45,
                4.4,
                4.3,
                4.1,
                3.8,
                3.4,
                2.9,
                2.2,
                1.5,
            ],
            dtype=np.float64,
        )

    def init(self, ctx) -> None:
        snapshot = ctx.read_matrix_snapshot()
        h, w, _ = snapshot.shape

        fig = figure(width=w, height=h)
        ax = fig.axes(
            title="Static 2-D Plot",
            x_label_bottom="x",
            y_label_left="y",
        )
        ax.plot(x=self._x, y=self._y, color=(255, 170, 70), width=1)
        ax.scatter(x=self._x, y=self._y, color=(90, 190, 255), size=2)

        ctx.submit_write_batch(fig.compile_write_batch())

    def loop(self, ctx, dt: float) -> None:
        # Static example; no updates after first frame.
        return None

    def stop(self, ctx) -> None:
        return None


def create() -> StaticPlot2DApp:
    return StaticPlot2DApp()
