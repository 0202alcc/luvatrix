from __future__ import annotations

import os
import numpy as np

from luvatrix_plot import DynamicSampleAxis, IncrementalPlotState, figure
from luvatrix_plot.compile import compile_full_rewrite_batch, compile_replace_patches_batch
from luvatrix_plot.scales import DataLimits


class PlotDemoApp:
    def __init__(self) -> None:
        self._t = 0.0
        self._values = np.zeros(240, dtype=np.float64)
        dx = float(os.getenv("LUVATRIX_PLOT_DX", "1.0"))
        self._axis = DynamicSampleAxis(sample_count=self._values.size, dx=dx, x0=0.0)
        self._incremental: IncrementalPlotState | None = None
        self._static_rgba: np.ndarray | None = None
        self._ax = None
        self._width = 0
        self._height = 0

    def init(self, ctx) -> None:
        self._t = 0.0
        self._axis.reset(x0=0.0)
        self._values.fill(0.0)
        snap = ctx.read_matrix_snapshot()
        self._height, self._width, _ = snap.shape

    def loop(self, ctx, dt: float) -> None:
        next_value = float(self._signal(np.asarray([self._t], dtype=np.float64))[0])
        self._t += max(0.0, dt)
        _ = self._axis.on_sample()
        if self._axis.push_from_right:
            self._values = np.roll(self._values, -1)
            self._values[-1] = next_value
        else:
            self._values = np.roll(self._values, 1)
            self._values[0] = next_value

        snap = ctx.read_matrix_snapshot()
        h, w, _ = snap.shape
        if h != self._height or w != self._width:
            self._height = h
            self._width = w
            self._render_full(ctx)
            return None

        state = self._incremental
        ax = self._ax
        static = self._static_rgba
        if state is None or static is None or ax is None:
            self._render_full(ctx)
            return None

        next_limits = state.y_limits
        y_min = float(self._values.min())
        y_max = float(self._values.max())
        if y_min < next_limits.ymin or y_max > next_limits.ymax:
            # Safe fallback if limits would need to expand.
            self._render_full(ctx)
            return None

        if not state.can_fast_path(
            width=w,
            height=h,
            next_values=self._values,
            y_limits=next_limits,
        ):
            self._render_full(ctx)
            return None

        data_plane = state.advance_one(self._values)
        x0, y0, _, _ = state.plot_rect
        patch = static[y0 : y0 + data_plane.shape[0], x0 : x0 + data_plane.shape[1]].copy()
        alpha = data_plane[:, :, 3:4].astype(np.float32) / 255.0
        inv = 1.0 - alpha
        patch[:, :, :3] = (data_plane[:, :, :3] * alpha + patch[:, :, :3] * inv).astype(np.uint8)
        patch[:, :, 3] = 255
        patches: list[tuple[int, int, np.ndarray]] = [(x0, y0, patch)]
        xr0, xr1 = self._axis.x_window_sorted()
        visible_min, visible_max = self._axis.label_visibility_bounds()
        x_rule_patch = ax.render_x_rule_patch(xr0, xr1, visible_min=visible_min, visible_max=visible_max)
        if x_rule_patch is not None:
            patches.append(x_rule_patch)
        ctx.submit_write_batch(compile_replace_patches_batch(patches))
        return None

    def _signal(self, x: np.ndarray) -> np.ndarray:
        return (
            0.65 * np.sin(2.5 * x)
            + 0.35 * np.cos(1.3 * x)
            + 0.15 * np.sin(9.0 * x)
        )

    def _render_full(self, ctx) -> None:
        fig = figure(width=self._width, height=self._height)
        ax = fig.axes(
            title="Luvatrix Plot Demo",
            x_label_bottom="x",
            y_label_left="signal",
        )
        ax.set_limit_hysteresis(enabled=True, deadband_ratio=0.12, shrink_rate=0.06)
        ax.set_major_tick_steps(x=20.0 * abs(self._axis.dx), y=0.2)
        ax.set_dynamic_defaults()
        ax.plot(y=self._values, color=(255, 170, 70), width=1)
        ax.scatter(y=self._values, color=(90, 190, 255), size=1, alpha=0.8)
        frame = fig.to_rgba()
        ctx.submit_write_batch(compile_full_rewrite_batch(frame))

        plot_rect = ax.last_plot_rect()
        static_rgba = ax.last_static_rgba()
        data_rgba = ax.last_data_rgba()
        limits = ax.last_limits()
        if plot_rect is None or static_rgba is None or data_rgba is None or limits is None:
            self._incremental = None
            self._static_rgba = None
            return
        x0, y0, pw, ph = plot_rect
        self._static_rgba = static_rgba
        self._ax = ax
        self._incremental = IncrementalPlotState(
            width=self._width,
            height=self._height,
            plot_rect=plot_rect,
            y_limits=DataLimits(xmin=0.0, xmax=float(self._values.size - 1), ymin=limits.ymin, ymax=limits.ymax),
            series_values=self._values.copy(),
            data_plane=data_rgba[y0 : y0 + ph, x0 : x0 + pw].copy(),
            line_color=(255, 170, 70, 255),
            line_width=1,
            marker_color=(90, 190, 255, 204),
            marker_size=2,
            push_from_right=self._axis.push_from_right,
        )

    def stop(self, ctx) -> None:
        return None


def create() -> PlotDemoApp:
    return PlotDemoApp()
