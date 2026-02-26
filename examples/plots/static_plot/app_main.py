from __future__ import annotations

import numpy as np

from luvatrix_plot import figure


class StaticPlotApp:
    def __init__(self) -> None:
        # Pre-generated 1-D numeric data.
        self._data = np.asarray(
            [
                2.0,
                2.4,
                2.1,
                3.0,
                2.8,
                3.2,
                3.6,
                3.1,
                3.9,
                4.3,
                4.0,
                4.7,
                4.5,
                4.9,
                5.2,
                5.0,
                5.5,
                5.8,
                5.4,
                6.1,
            ],
            dtype=np.float64,
        )

    def init(self, ctx) -> None:
        snapshot = ctx.read_matrix_snapshot()
        h, w, _ = snapshot.shape

        fig = figure(width=w, height=h)
        ax = fig.axes(
            title="Static 1-D Plot",
            x_label_bottom="index",
            y_label_left="value",
        )
        ax.plot(y=self._data, color=(255, 170, 70), width=1)
        ax.scatter(y=self._data, color=(90, 190, 255), size=3)

        ctx.submit_write_batch(fig.compile_write_batch())

    def loop(self, ctx, dt: float) -> None:
        # Intentionally no updates; this example stays static.
        return None

    def stop(self, ctx) -> None:
        return None


def create() -> StaticPlotApp:
    return StaticPlotApp()
