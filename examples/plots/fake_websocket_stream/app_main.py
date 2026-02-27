from __future__ import annotations

import math
import os

import numpy as np

from luvatrix_plot import Dynamic2DStreamBuffer, figure
from luvatrix_plot.compile import compile_full_rewrite_batch


class FakeWebsocketStreamApp:
    def __init__(self) -> None:
        self._width = 0
        self._height = 0
        self._t = 0.0
        self._latest_x = 0.0
        self._accepted = 0
        self._rejected = 0
        self._rng = np.random.default_rng(int(os.getenv("LUVATRIX_FAKE_WS_SEED", "42")))

        dx = float(os.getenv("LUVATRIX_FAKE_WS_DX", "0.1"))
        bins = max(16, int(os.getenv("LUVATRIX_FAKE_WS_WINDOW_BINS", "120")))
        self._gap_prob = min(0.5, max(0.0, float(os.getenv("LUVATRIX_FAKE_WS_GAP_PROB", "0.1"))))
        self._max_gap_bins = max(1, int(os.getenv("LUVATRIX_FAKE_WS_MAX_GAP_BINS", "3")))
        self._ooo_prob = min(0.3, max(0.0, float(os.getenv("LUVATRIX_FAKE_WS_OOO_PROB", "0.03"))))
        self._packets_per_tick = max(1, int(os.getenv("LUVATRIX_FAKE_WS_PACKETS_PER_TICK", "2")))
        self._stream = Dynamic2DStreamBuffer(viewport_bins=bins, dx=dx, x0=0.0)

    def init(self, ctx) -> None:
        self._t = 0.0
        self._latest_x = 0.0
        self._accepted = 0
        self._rejected = 0
        self._stream.reset(x0=0.0)
        snap = ctx.read_matrix_snapshot()
        self._height, self._width, _ = snap.shape

    def loop(self, ctx, dt: float) -> None:
        self._t += max(0.0, dt)
        for _ in range(self._packets_per_tick):
            # Simulate sparse websocket cadence with occasional x gaps.
            step_bins = 1
            if self._rng.random() < self._gap_prob:
                step_bins += int(self._rng.integers(1, self._max_gap_bins + 1))
            self._latest_x += self._stream.dx * float(step_bins)

            y = (
                0.72 * math.sin(2.2 * self._latest_x)
                + 0.31 * math.cos(0.8 * self._latest_x)
                + 0.10 * math.sin(8.0 * self._latest_x)
                + float(self._rng.normal(0.0, 0.03))
            )

            # Rare out-of-order packet to exercise rejection behavior.
            x_value = self._latest_x
            if self._accepted > 8 and self._rng.random() < self._ooo_prob:
                back_bins = int(self._rng.integers(1, 3))
                x_value = self._latest_x - self._stream.dx * float(back_bins)

            out = self._stream.ingest(x_value, y)
            if out.status == "out_of_order":
                self._rejected += 1
            else:
                self._accepted += 1

        fig = figure(width=self._width, height=self._height)
        ax = fig.axes(
            title="Fake Websocket 2-D Stream",
            x_label_bottom="x",
            y_label_left="y",
        )
        ax.set_dynamic_defaults()
        ax.set_limit_hysteresis(enabled=False)
        ax.set_major_tick_steps(x=max(abs(self._stream.dx) * 10.0, abs(self._stream.dx)), y=0.2)
        ax.plot(x=self._stream.x_values, y=self._stream.y_values, color=(255, 170, 70), width=1, alpha=0.9)
        ax.scatter(x=self._stream.x_values, y=self._stream.y_values, color=(90, 190, 255), size=2, alpha=0.95)
        frame = fig.to_rgba()
        ctx.submit_write_batch(compile_full_rewrite_batch(frame))
        return None

    def stop(self, ctx) -> None:
        return None


def create() -> FakeWebsocketStreamApp:
    return FakeWebsocketStreamApp()
