from __future__ import annotations

import math
import os
from pathlib import Path

import numpy as np

from luvatrix_plot import Dynamic2DMonotonicAxis, figure
from luvatrix_plot.compile import compile_full_rewrite_batch, compile_replace_patches_batch
from luvatrix_plot.scales import build_transform, map_to_pixels


class DynamicPlot2DApp:
    def __init__(self) -> None:
        self._t = 0.0
        self._window_bins = max(16, int(os.getenv("LUVATRIX_DYNAMIC2D_WINDOW_BINS", "120")))
        self._x_values = np.full(self._window_bins, np.nan, dtype=np.float64)
        self._y_values = np.full(self._window_bins, np.nan, dtype=np.float64)
        dx = float(os.getenv("LUVATRIX_DYNAMIC2D_DX", "0.1"))
        self._axis = Dynamic2DMonotonicAxis(viewport_bins=self._y_values.size, dx=dx, x0=0.0)
        # Optional synthetic gaps for stress testing sparse streams; disabled by default.
        self._gap_period = int(os.getenv("LUVATRIX_DYNAMIC2D_GAP_PERIOD", "0"))
        self._gap_bins = int(os.getenv("LUVATRIX_DYNAMIC2D_GAP_BINS", "3"))
        self._x_actual = 0.0
        self._tick = 0
        self._fig = None
        self._ax = None
        self._static_rgba: np.ndarray | None = None
        self._data_plot_rect: tuple[int, int, int, int] | None = None
        self._y_limits: tuple[float, float] | None = None
        self._width = 0
        self._height = 0
        self._frame_idx = 0
        self._debug_pixels = os.getenv("LUVATRIX_PLOT_DEBUG_PIXELS", "").strip().lower() in {"1", "true", "yes", "on"}
        self._debug_pixels_path = Path(
            os.getenv("LUVATRIX_PLOT_DEBUG_PIXELS_PATH", "/tmp/luvatrix_dynamic2d_pixels.csv")
        )

    def init(self, ctx) -> None:
        self._t = 0.0
        self._axis.reset(x0=0.0)
        self._x_actual = 0.0
        self._tick = 0
        self._x_values[:] = np.nan
        self._y_values[:] = np.nan
        self._fig = None
        self._ax = None
        self._static_rgba = None
        self._data_plot_rect = None
        self._y_limits = None
        self._frame_idx = 0
        if self._debug_pixels:
            self._debug_pixels_path.parent.mkdir(parents=True, exist_ok=True)
            self._debug_pixels_path.write_text(
                "frame,slot,x,y,px,py,plot_w,plot_h,xmin,xmax,ymin,ymax\n",
                encoding="utf-8",
            )
        snap = ctx.read_matrix_snapshot()
        self._height, self._width, _ = snap.shape

    def loop(self, ctx, dt: float) -> None:
        self._t += max(0.0, dt)
        # First sample lands exactly at x0; then one bin per frame by default.
        gap = 0 if self._tick == 0 else 1
        if self._gap_period > 0 and self._tick > 0 and self._tick % self._gap_period == 0:
            gap = max(1, self._gap_bins)
        self._x_actual += self._axis.dx * float(gap)
        self._tick += 1
        y = (
            0.72 * math.sin(2.1 * self._t)
            + 0.31 * math.cos(0.9 * self._t)
            + 0.11 * math.sin(8.8 * self._t)
        )

        ingest = self._axis.ingest(self._x_actual, y)
        if ingest.status == "out_of_order":
            return None
        self._update_value_window(
            ingest.gap_bins,
            ingest.x_value,
            ingest.y_value,
            update_only=(ingest.status == "update_current"),
        )

        snap = ctx.read_matrix_snapshot()
        h, w, _ = snap.shape
        if h != self._height or w != self._width:
            self._height = h
            self._width = w
            self._render_full(ctx)
            return None

        if self._fig is None or self._ax is None or self._static_rgba is None or self._data_plot_rect is None:
            self._render_full(ctx)
            return None

        y_finite = self._y_values[np.isfinite(self._y_values)]
        if y_finite.size == 0:
            return None
        y_min = float(np.min(y_finite))
        y_max = float(np.max(y_finite))
        if self._y_limits is None:
            self._render_full(ctx)
            return None
        lim_min, lim_max = self._y_limits
        if y_min < lim_min or y_max > lim_max:
            self._render_full(ctx)
            return None

        # Plot plane patch (sample-index domain).
        x0, y0, pw, ph = self._data_plot_rect
        frame = self._fig.to_rgba()
        self._frame_idx += 1
        if self._debug_pixels:
            self._dump_pixel_trace(plot_w=pw, plot_h=ph)
        data_patch = frame[y0 : y0 + ph, x0 : x0 + pw]
        patch = self._static_rgba[y0 : y0 + ph, x0 : x0 + pw].copy()
        alpha = data_patch[:, :, 3:4].astype(np.float32) / 255.0
        inv = 1.0 - alpha
        patch[:, :, :3] = (data_patch[:, :, :3] * alpha + patch[:, :, :3] * inv).astype(np.uint8)
        patch[:, :, 3] = 255
        patches: list[tuple[int, int, np.ndarray]] = [(x0, y0, patch)]

        # X-rule patch must use the exact x-limits used for the current frame
        # transform; otherwise tick labels drift relative to plotted points.
        limits = self._ax.last_limits()
        if limits is None:
            x_rule_patch = None
        else:
            x_rule_patch = self._ax.render_x_rule_patch(
                limits.xmin,
                limits.xmax,
                visible_min=0.0,
            )
        if x_rule_patch is not None:
            patches.append(x_rule_patch)
        ctx.submit_write_batch(compile_replace_patches_batch(patches))
        return None

    def _dump_pixel_trace(self, *, plot_w: int, plot_h: int) -> None:
        if self._ax is None:
            return
        limits = self._ax.last_limits()
        if limits is None:
            return
        mask = np.isfinite(self._x_values) & np.isfinite(self._y_values)
        if not np.any(mask):
            return
        x = self._x_values[mask]
        y = self._y_values[mask]
        slots = np.flatnonzero(mask)
        transform = build_transform(limits, width=plot_w, height=plot_h)
        px, py = map_to_pixels(x, y, transform, width=plot_w, height=plot_h)
        lines = []
        for i, slot in enumerate(slots.tolist()):
            lines.append(
                f"{self._frame_idx},{slot},{x[i]:.17g},{y[i]:.17g},{int(px[i])},{int(py[i])},"
                f"{plot_w},{plot_h},{limits.xmin:.17g},{limits.xmax:.17g},{limits.ymin:.17g},{limits.ymax:.17g}\n"
            )
        with self._debug_pixels_path.open("a", encoding="utf-8") as f:
            f.writelines(lines)

    def _update_value_window(self, gap_bins: int, x_value: float, y_value: float, *, update_only: bool) -> None:
        if update_only:
            if self._axis.push_from_right:
                self._x_values[-1] = x_value
                self._y_values[-1] = y_value
            else:
                self._x_values[0] = x_value
                self._y_values[0] = y_value
            return
        shift = max(1, int(gap_bins) + 1)
        n = self._y_values.size
        if self._axis.push_from_right:
            if shift >= n:
                self._x_values[:] = np.nan
                self._y_values[:] = np.nan
                self._x_values[-1] = x_value
                self._y_values[-1] = y_value
                return
            self._x_values[:] = np.roll(self._x_values, -shift)
            self._y_values[:] = np.roll(self._y_values, -shift)
            self._x_values[-shift:] = np.nan
            self._y_values[-shift:] = np.nan
            self._x_values[-1] = x_value
            self._y_values[-1] = y_value
            return
        if shift >= n:
            self._x_values[:] = np.nan
            self._y_values[:] = np.nan
            self._x_values[0] = x_value
            self._y_values[0] = y_value
            return
        self._x_values[:] = np.roll(self._x_values, shift)
        self._y_values[:] = np.roll(self._y_values, shift)
        self._x_values[:shift] = np.nan
        self._y_values[:shift] = np.nan
        self._x_values[0] = x_value
        self._y_values[0] = y_value

    def _render_full(self, ctx) -> None:
        self._fig = figure(width=self._width, height=self._height)
        self._ax = self._fig.axes(
            title="Dynamic 2-D Scatter",
            x_label_bottom="x",
            y_label_left="y",
        )
        # For dynamic debugging, keep limits raw so oldest visible x maps directly to y-axis.
        self._ax.set_limit_hysteresis(enabled=False)
        self._ax.set_dynamic_defaults()
        self._ax.set_major_tick_steps(x=max(abs(self._axis.dx) * 8.0, abs(self._axis.dx)), y=0.2)
        self._ax.plot(x=self._x_values, y=self._y_values, color=(255, 170, 70), width=1, alpha=0.9)
        self._ax.scatter(x=self._x_values, y=self._y_values, color=(90, 190, 255), size=2, alpha=0.95)

        frame = self._fig.to_rgba()
        ctx.submit_write_batch(compile_full_rewrite_batch(frame))

        if self._ax is None:
            self._static_rgba = None
            self._data_plot_rect = None
            self._y_limits = None
            return
        self._static_rgba = self._ax.last_static_rgba()
        self._data_plot_rect = self._ax.last_plot_rect()
        limits = self._ax.last_limits()
        self._y_limits = None if limits is None else (limits.ymin, limits.ymax)

    def stop(self, ctx) -> None:
        return None


def create() -> DynamicPlot2DApp:
    return DynamicPlot2DApp()
