from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import math


@dataclass
class DynamicSampleAxis:
    sample_count: int
    dx: float = 1.0
    x0: float = 0.0
    samples_seen: int = 0

    def __post_init__(self) -> None:
        if self.sample_count <= 1:
            raise ValueError("sample_count must be > 1")
        if self.dx == 0:
            raise ValueError("dx must be non-zero")

    def reset(self, *, x0: float | None = None, dx: float | None = None) -> None:
        if x0 is not None:
            self.x0 = float(x0)
        if dx is not None:
            if dx == 0:
                raise ValueError("dx must be non-zero")
            self.dx = float(dx)
        self.samples_seen = 0

    @property
    def push_from_right(self) -> bool:
        return self.dx > 0

    @property
    def latest_sample(self) -> int:
        return self.samples_seen - 1

    def on_sample(self) -> int:
        idx = self.samples_seen
        self.samples_seen += 1
        return idx

    def sample_window(self) -> tuple[int, int]:
        end = self.latest_sample
        start = end - (self.sample_count - 1)
        return (start, end)

    def x_for_sample(self, sample_index: int) -> float:
        return self.x0 + float(sample_index) * self.dx

    def x_window(self) -> tuple[float, float]:
        s, e = self.sample_window()
        xs = self.x_for_sample(s)
        xe = self.x_for_sample(e)
        return (xs, xe)

    def x_window_sorted(self) -> tuple[float, float]:
        xs, xe = self.x_window()
        return (min(xs, xe), max(xs, xe))

    def label_visibility_bounds(self) -> tuple[float | None, float | None]:
        # At init x(0)=x0. Hide labels "before first sample" by clipping to x0.
        if self.dx > 0:
            return (self.x0, None)
        return (None, self.x0)


@dataclass(frozen=True)
class Dynamic2DIngestResult:
    status: Literal["advance", "update_current", "out_of_order"]
    bin_index: int
    y_value: float
    gap_bins: int = 0
    x_value: float = 0.0
    x_quantized: float = 0.0
    residual_bins: float = 0.0


@dataclass
class Dynamic2DMonotonicAxis:
    viewport_bins: int
    dx: float
    x0: float = 0.0
    latest_bin: int | None = None

    def __post_init__(self) -> None:
        if self.viewport_bins <= 1:
            raise ValueError("viewport_bins must be > 1")
        if self.dx == 0:
            raise ValueError("dx must be non-zero")
        self._history: dict[int, float] = {}

    def reset(self, *, x0: float | None = None, dx: float | None = None) -> None:
        if x0 is not None:
            self.x0 = float(x0)
        if dx is not None:
            if dx == 0:
                raise ValueError("dx must be non-zero")
            self.dx = float(dx)
        self.latest_bin = None
        self._history.clear()

    @property
    def push_from_right(self) -> bool:
        return self.dx > 0

    def bin_for_x(self, x_value: float) -> int:
        u = (float(x_value) - self.x0) / self.dx
        # Quantize to nearest bin so non-exact dt multiples remain stable.
        nearest = round(u)
        eps = 1e-9 * max(1.0, abs(u))
        if abs(u - nearest) <= eps:
            return int(nearest)
        return int(round(u))

    def x_for_bin(self, bin_index: int) -> float:
        return self.x0 + float(bin_index) * self.dx

    def ingest(self, x_value: float, y_value: float) -> Dynamic2DIngestResult:
        x_raw = float(x_value)
        u = (x_raw - self.x0) / self.dx
        k = self.bin_for_x(x_raw)
        xq = self.x_for_bin(k)
        residual = float(u - float(k))
        y = float(y_value)
        prev = self.latest_bin
        if prev is None:
            self.latest_bin = k
            self._history[k] = y
            return Dynamic2DIngestResult(
                status="advance",
                bin_index=k,
                y_value=y,
                gap_bins=0,
                x_value=x_raw,
                x_quantized=xq,
                residual_bins=residual,
            )

        delta = k - prev
        if delta < 0:
            return Dynamic2DIngestResult(
                status="out_of_order",
                bin_index=k,
                y_value=y,
                gap_bins=0,
                x_value=x_raw,
                x_quantized=xq,
                residual_bins=residual,
            )
        if delta == 0:
            # Same bin: overwrite current bin payload (last-sample-wins policy).
            self._history[k] = y
            return Dynamic2DIngestResult(
                status="update_current",
                bin_index=k,
                y_value=y,
                gap_bins=0,
                x_value=x_raw,
                x_quantized=xq,
                residual_bins=residual,
            )

        gap_bins = max(0, delta - 1)
        self.latest_bin = k
        self._history[k] = y
        return Dynamic2DIngestResult(
            status="advance",
            bin_index=k,
            y_value=y,
            gap_bins=gap_bins,
            x_value=x_raw,
            x_quantized=xq,
            residual_bins=residual,
        )

    def window_bins(self) -> tuple[int, int]:
        end = 0 if self.latest_bin is None else self.latest_bin
        start = end - (self.viewport_bins - 1)
        return (start, end)

    def window_x_sorted(self) -> tuple[float, float]:
        b0, b1 = self.window_bins()
        x0 = self.x_for_bin(b0)
        x1 = self.x_for_bin(b1)
        return (min(x0, x1), max(x0, x1))
