from __future__ import annotations

import os
import time
import numpy as np

from luvatrix_plot import figure


class StaticPlot2DApp:
    def __init__(self) -> None:
        # Static 2-D paths (x and y both explicit) for two series.
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
        self._y_2 = np.asarray(
            [
                1.2,
                1.8,
                2.3,
                2.7,
                3.0,
                3.2,
                3.3,
                3.35,
                3.4,
                3.35,
                3.3,
                3.2,
                3.0,
                2.7,
                2.3,
                1.8,
                1.2,
            ],
            dtype=np.float64,
        )
        self._fig = None
        self._ax = None
        self._pointer_x = 0.0
        self._pointer_y = 0.0
        self._pointer_down = False
        self._legend_dirty = False
        self._last_render_ns = 0
        self._drag_render_interval_ns = int(1_000_000_000 / 45)  # cap drag redraws at ~45 FPS
        self._debug = os.getenv("LUVATRIX_PLOT_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}

    def init(self, ctx) -> None:
        snapshot = ctx.read_matrix_snapshot()
        h, w, _ = snapshot.shape

        self._fig = figure(width=w, height=h)
        self._ax = self._fig.axes(
            title="Static 2-D Plot",
            x_label_bottom="x",
            y_label_left="y",
        )
        self._ax.plot(x=self._x, y=self._y, color=(255, 170, 70), width=1, label="upper arc")
        self._ax.scatter(x=self._x, y=self._y, color=(90, 190, 255), size=2)
        self._ax.plot(x=self._x, y=self._y_2, color=(103, 204, 131), width=1, label="lower arc")
        self._ax.scatter(x=self._x, y=self._y_2, color=(241, 227, 145), size=2)

        self._submit_frame(ctx)
        self._last_render_ns = time.time_ns()
        if self._debug and self._ax is not None:
            print(f"[plot-debug] init legend_bounds={self._ax.legend_bounds()}")

    def loop(self, ctx, dt: float) -> None:
        _ = dt
        if self._ax is None:
            return None
        events = ctx.poll_hdi_events(max_events=64)
        if self._debug and events:
            print(f"[plot-debug] events={len(events)}")
        for event in events:
            if event.status != "OK" or not isinstance(event.payload, dict):
                continue
            if self._debug:
                print(
                    "[plot-debug] event",
                    f"device={event.device}",
                    f"type={event.event_type}",
                    f"payload={event.payload}",
                )
            if event.event_type == "pointer_move":
                self._pointer_x = float(event.payload.get("x", self._pointer_x))
                self._pointer_y = float(event.payload.get("y", self._pointer_y))
                continue
            if event.event_type == "click":
                self._pointer_x = float(event.payload.get("x", self._pointer_x))
                self._pointer_y = float(event.payload.get("y", self._pointer_y))
                button = int(event.payload.get("button", -1))
                phase = str(event.payload.get("phase", ""))
                if button == 0 and phase == "down":
                    self._pointer_down = True
                elif button == 0 and phase == "up":
                    self._pointer_down = False

        if self._debug:
            print(
                "[plot-debug] drag_check",
                f"pointer=({self._pointer_x:.1f},{self._pointer_y:.1f})",
                f"down={self._pointer_down}",
                f"legend_bounds={self._ax.legend_bounds()}",
            )
        moved = self._ax.update_legend_drag(self._pointer_x, self._pointer_y, self._pointer_down)
        if moved:
            self._legend_dirty = True
            if self._debug:
                print(f"[plot-debug] legend moved -> {self._ax.legend_bounds()}")
        if self._legend_dirty:
            now_ns = time.time_ns()
            # Coalesce high-frequency pointer updates while dragging.
            if (not self._pointer_down) or (now_ns - self._last_render_ns >= self._drag_render_interval_ns):
                dirty = self._ax.take_legend_dirty_rect()
                self._submit_incremental_frame(ctx, dirty)
                self._last_render_ns = now_ns
                self._legend_dirty = False
        return None

    def stop(self, ctx) -> None:
        return None

    def _submit_frame(self, ctx) -> None:
        if self._fig is None:
            return
        ctx.submit_write_batch(self._fig.compile_write_batch())

    def _submit_incremental_frame(self, ctx, dirty_rect: tuple[int, int, int, int] | None) -> None:
        if self._fig is None:
            return
        if dirty_rect is None:
            ctx.submit_write_batch(self._fig.compile_write_batch())
            return
        ctx.submit_write_batch(self._fig.compile_incremental_write_batch(dirty_rect))


def create() -> StaticPlot2DApp:
    return StaticPlot2DApp()
