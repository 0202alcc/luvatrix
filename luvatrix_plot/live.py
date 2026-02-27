from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from luvatrix_plot.dynamic_axis import Dynamic2DIngestResult, Dynamic2DMonotonicAxis
from luvatrix_plot.raster import draw_markers, draw_polyline
from luvatrix_plot.scales import DataLimits, build_transform, map_to_pixels


@dataclass
class SampleToXMapper:
    sample_count: int
    x_values: np.ndarray | None = None

    def __post_init__(self) -> None:
        if self.sample_count <= 1:
            raise ValueError("sample_count must be > 1")
        if self.x_values is None:
            self.x_values = np.linspace(0.0, float(self.sample_count - 1), self.sample_count, dtype=np.float64)
        else:
            arr = np.asarray(self.x_values, dtype=np.float64)
            if arr.shape != (self.sample_count,):
                raise ValueError("x_values shape does not match sample_count")
            self.x_values = arr.copy()

    def reset(self, *, latest_x: float, step: float) -> None:
        if step <= 0:
            raise ValueError("step must be > 0")
        start = float(latest_x) - float(step) * float(self.sample_count - 1)
        self.x_values = np.linspace(start, float(latest_x), self.sample_count, dtype=np.float64)

    def push(self, x_value: float) -> None:
        self.x_values = np.roll(self.x_values, -1)
        self.x_values[-1] = float(x_value)

    def window(self) -> tuple[float, float]:
        return (float(self.x_values[0]), float(self.x_values[-1]))

    def x_for_sample(self, sample_index: int) -> float:
        return float(self.x_values[int(sample_index)])


@dataclass
class IncrementalPlotState:
    width: int
    height: int
    plot_rect: tuple[int, int, int, int]
    y_limits: DataLimits
    series_values: np.ndarray
    data_plane: np.ndarray
    line_color: tuple[int, int, int, int]
    line_width: int
    marker_color: tuple[int, int, int, int]
    marker_size: int
    push_from_right: bool = True

    def can_fast_path(
        self,
        *,
        width: int,
        height: int,
        next_values: np.ndarray,
        y_limits: DataLimits,
    ) -> bool:
        if width != self.width or height != self.height:
            return False
        if next_values.shape != self.series_values.shape:
            return False
        if next_values.size < 2:
            return False
        if self.push_from_right:
            if not np.allclose(self.series_values[1:], next_values[:-1], rtol=0.0, atol=1e-12):
                return False
        else:
            if not np.allclose(self.series_values[:-1], next_values[1:], rtol=0.0, atol=1e-12):
                return False
        # Transform must remain stable for the fast path.
        if abs(y_limits.ymin - self.y_limits.ymin) > 1e-12 or abs(y_limits.ymax - self.y_limits.ymax) > 1e-12:
            return False
        return True

    def advance_one(self, next_values: np.ndarray) -> np.ndarray:
        _, _, plot_w, plot_h = self.plot_rect
        self.data_plane[:, :, :] = 0

        transform = build_transform(
            limits=DataLimits(
                xmin=0.0,
                xmax=float(next_values.size - 1),
                ymin=self.y_limits.ymin,
                ymax=self.y_limits.ymax,
            ),
            width=plot_w,
            height=plot_h,
        )
        xvals = np.arange(next_values.size, dtype=np.float64)
        yvals = next_values.astype(np.float64, copy=False)
        px, py = map_to_pixels(xvals, yvals, transform, plot_w, plot_h)

        draw_polyline(
            self.data_plane,
            px.astype(np.int32),
            py.astype(np.int32),
            color=self.line_color,
            width=self.line_width,
        )
        draw_markers(
            self.data_plane,
            px.astype(np.int32),
            py.astype(np.int32),
            color=self.marker_color,
            size=max(2, self.marker_size),
        )
        self.series_values = next_values.copy()
        return self.data_plane


@dataclass
class Dynamic2DStreamBuffer:
    """Rolling 2-D stream buffer for monotonic x-series (e.g. websocket ticks)."""

    viewport_bins: int
    dx: float
    x0: float = 0.0

    def __post_init__(self) -> None:
        if self.viewport_bins <= 1:
            raise ValueError("viewport_bins must be > 1")
        if self.dx == 0:
            raise ValueError("dx must be non-zero")
        self.axis = Dynamic2DMonotonicAxis(viewport_bins=self.viewport_bins, dx=self.dx, x0=self.x0)
        self.x_values = np.full(self.viewport_bins, np.nan, dtype=np.float64)
        self.y_values = np.full(self.viewport_bins, np.nan, dtype=np.float64)

    def reset(self, *, x0: float | None = None, dx: float | None = None) -> None:
        if x0 is not None:
            self.x0 = float(x0)
        if dx is not None:
            if dx == 0:
                raise ValueError("dx must be non-zero")
            self.dx = float(dx)
        self.axis.reset(x0=self.x0, dx=self.dx)
        self.x_values[:] = np.nan
        self.y_values[:] = np.nan

    def ingest(self, x_value: float, y_value: float) -> Dynamic2DIngestResult:
        out = self.axis.ingest(x_value, y_value)
        if out.status == "out_of_order":
            return out
        if out.status == "update_current":
            if self.axis.push_from_right:
                self.x_values[-1] = out.x_value
                self.y_values[-1] = out.y_value
            else:
                self.x_values[0] = out.x_value
                self.y_values[0] = out.y_value
            return out

        shift = max(1, int(out.gap_bins) + 1)
        n = self.viewport_bins
        if self.axis.push_from_right:
            if shift >= n:
                self.x_values[:] = np.nan
                self.y_values[:] = np.nan
                self.x_values[-1] = out.x_value
                self.y_values[-1] = out.y_value
                return out
            self.x_values[:] = np.roll(self.x_values, -shift)
            self.y_values[:] = np.roll(self.y_values, -shift)
            self.x_values[-shift:] = np.nan
            self.y_values[-shift:] = np.nan
            self.x_values[-1] = out.x_value
            self.y_values[-1] = out.y_value
            return out

        if shift >= n:
            self.x_values[:] = np.nan
            self.y_values[:] = np.nan
            self.x_values[0] = out.x_value
            self.y_values[0] = out.y_value
            return out
        self.x_values[:] = np.roll(self.x_values, shift)
        self.y_values[:] = np.roll(self.y_values, shift)
        self.x_values[:shift] = np.nan
        self.y_values[:shift] = np.nan
        self.x_values[0] = out.x_value
        self.y_values[0] = out.y_value
        return out

    def finite_count(self) -> int:
        return int(np.count_nonzero(np.isfinite(self.x_values) & np.isfinite(self.y_values)))
