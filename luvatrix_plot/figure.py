from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

import numpy as np

from luvatrix_plot.adapters import normalize_xy
from luvatrix_plot.compile import compile_full_rewrite_batch, compile_replace_patch_batch, compile_replace_rect_batch
from luvatrix_plot.errors import PlotDataError
from luvatrix_plot.raster import (
    LayerCache,
    blit,
    draw_hline,
    draw_markers,
    draw_polyline,
    draw_text,
    draw_vline,
    new_canvas,
    text_size,
)
from luvatrix_plot.raster.canvas import draw_pixel
from luvatrix_plot.scales import (
    DataLimits,
    build_transform,
    compute_limits,
    downsample_by_pixel_column,
    format_ticks_for_axis,
    generate_nice_ticks,
    infer_resolution,
    map_to_pixels,
    preferred_major_step_from_resolution,
)
from luvatrix_plot.series import SeriesSpec, SeriesStyle


def _coerce_color(color: tuple[int, int, int] | tuple[int, int, int, int], alpha: float) -> tuple[int, int, int, int]:
    if len(color) == 3:
        r, g, b = color
        a = int(max(0.0, min(1.0, alpha)) * 255)
        return (r, g, b, a)
    r, g, b, a = color
    out_a = int(max(0.0, min(1.0, alpha)) * a)
    return (r, g, b, out_a)


def _union_rect(
    a: tuple[int, int, int, int] | None,
    b: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    if a is None:
        return b
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax1 = ax + aw
    ay1 = ay + ah
    bx1 = bx + bw
    by1 = by + bh
    x0 = min(ax, bx)
    y0 = min(ay, by)
    x1 = max(ax1, bx1)
    y1 = max(ay1, by1)
    return (x0, y0, x1 - x0, y1 - y0)


def _inject_zero_tick(ticks: np.ndarray, *, vmin: float, vmax: float) -> np.ndarray:
    if ticks.size == 0:
        return ticks
    if vmin > 0.0 or vmax < 0.0:
        return ticks
    step = float(abs(ticks[1] - ticks[0])) if ticks.size > 1 else 1.0
    if np.any(np.isclose(ticks, 0.0, rtol=0.0, atol=max(1e-12, step * 1e-9))):
        return ticks
    return np.sort(np.append(ticks, 0.0))


def _contiguous_true_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    runs: list[tuple[int, int]] = []
    start = int(idx[0])
    prev = int(idx[0])
    for v in idx[1:]:
        iv = int(v)
        if iv == prev + 1:
            prev = iv
            continue
        runs.append((start, prev + 1))
        start = iv
        prev = iv
    runs.append((start, prev + 1))
    return runs


def _draw_filled_rect(
    canvas: np.ndarray,
    *,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int, int],
) -> None:
    left = max(0, min(int(x0), int(x1)))
    right = min(canvas.shape[1] - 1, max(int(x0), int(x1)))
    top = max(0, min(int(y0), int(y1)))
    bottom = min(canvas.shape[0] - 1, max(int(y0), int(y1)))
    if right < left or bottom < top:
        return
    for yy in range(top, bottom + 1):
        draw_hline(canvas, left, right, yy, color)


@dataclass(frozen=True)
class FigureStyle:
    background: tuple[int, int, int, int] = (12, 16, 23, 255)


@dataclass(frozen=True)
class ReferenceLine:
    axis: Literal["x", "y"]
    value: float
    color: tuple[int, int, int, int]
    width: int = 1


@dataclass(frozen=True)
class LegendEntry:
    label: str
    mode: str
    color: tuple[int, int, int, int]
    marker_size: int


@dataclass(frozen=True)
class LegendLayout:
    entries: tuple[LegendEntry, ...]
    plot_x0: int
    plot_y0: int
    plot_w: int
    plot_h: int
    legend_font_px: float
    swatch_w: int
    swatch_h: int
    item_gap: int
    pad: int
    item_h: int
    box_w: int
    box_h: int


@dataclass(frozen=True)
class XTickLabelLayout:
    rotate_deg: int
    stride: int
    font_px: float
    italic: bool
    max_w: int
    max_h: int


@dataclass
class Axes:
    figure: "Figure"
    title: str = ""
    x_label_bottom: str = "index"
    y_label_left: str = "value"
    x_label_top: str | None = None
    y_label_right: str | None = None
    show_top_axis: bool = False
    show_right_axis: bool = False

    _series: list[SeriesSpec] = field(default_factory=list)
    _cache: LayerCache = field(default_factory=LayerCache)
    _previous_limits: DataLimits | None = None

    # plot region gutters
    _gutter_left: int = 64
    _gutter_right: int = 16
    _gutter_top: int = 24
    _gutter_bottom: int = 40

    # style
    frame_color: tuple[int, int, int, int] = (60, 67, 78, 255)
    plot_bg_color: tuple[int, int, int, int] = (20, 26, 36, 255)
    grid_color: tuple[int, int, int, int] = (44, 53, 66, 255)
    minor_dot_grid_color: tuple[int, int, int, int] = (225, 232, 242, 90)
    show_minor_dot_grid: bool = True
    minor_dot_grid_max_points: int = 20000
    axis_color: tuple[int, int, int, int] = (124, 138, 156, 255)
    text_color: tuple[int, int, int, int] = (208, 218, 232, 255)
    limit_hysteresis_enabled: bool = False
    limit_hysteresis_deadband_ratio: float = 0.1
    limit_hysteresis_shrink_rate: float = 0.08
    show_zero_reference_lines: bool = True
    reference_line_color: tuple[int, int, int, int] = (186, 201, 220, 235)
    reference_lines: list[ReferenceLine] = field(default_factory=list)
    x_major_tick_step: float | None = None
    y_major_tick_step: float | None = None
    show_edge_x_tick_labels: bool = True
    show_edge_y_tick_labels: bool = True
    include_zero_x_tick: bool = False
    x_tick_label_scale: float = 1.0
    x_tick_label_offset: float = 0.0
    x_tick_labels: tuple[str, ...] | None = None
    _viewport_x: tuple[float, float] | None = None
    legend_position_px: tuple[int, int] | None = None
    _legend_bounds_px: tuple[int, int, int, int] | None = None
    _legend_drag_active: bool = False
    _legend_drag_offset_px: tuple[int, int] = (0, 0)
    _legend_dirty_rect_px: tuple[int, int, int, int] | None = None
    _legend_layout: LegendLayout | None = None
    _last_static_rgba: np.ndarray | None = None
    _last_data_rgba: np.ndarray | None = None
    _last_plot_rect_px: tuple[int, int, int, int] | None = None
    _last_limits: DataLimits | None = None
    _last_x_rule_rect_px: tuple[int, int, int, int] | None = None
    _last_x_rule_bg: np.ndarray | None = None
    _last_tick_font_px: float = 12.0
    _last_label_font_px: float = 12.0
    _last_x_tick_pad: int = 4
    _last_x_tick_mark_len: int = 6
    _last_max_x_tick_h: int = 12
    _last_x_label_gap: int = 8
    _last_x_tick_font_px: float = 12.0
    _last_x_tick_italic: bool = False
    _last_x_tick_label_rotate_deg: int = 0
    _last_x_tick_label_stride: int = 1
    _last_resolved_x_viewport: tuple[float, float] | None = None
    _last_tick_x: tuple[float, ...] = ()
    _last_tick_y: tuple[float, ...] = ()
    preferred_panel_aspect_ratio: float | None = None

    def scatter(
        self,
        y: Any = None,
        *,
        x: Any = None,
        data: Any = None,
        label: str | None = None,
        color: tuple[int, int, int] | tuple[int, int, int, int] = (62, 149, 255),
        size: int = 2,
        alpha: float = 1.0,
    ) -> "Axes":
        style = SeriesStyle(mode="markers", color=_coerce_color(color, alpha), marker_size=max(1, size), line_width=1)
        series_data = normalize_xy(y=y, x=x, data=data)
        self._series.append(SeriesSpec(data=series_data, style=style, label=label))
        return self

    def plot(
        self,
        y: Any = None,
        *,
        x: Any = None,
        data: Any = None,
        label: str | None = None,
        mode: str = "line",
        color: tuple[int, int, int] | tuple[int, int, int, int] = (255, 165, 0),
        width: int = 1,
        alpha: float = 1.0,
    ) -> "Axes":
        if mode not in {"line", "lines", "lines+markers"}:
            raise PlotDataError(f"unsupported plot mode: {mode}")
        style_mode = "lines+markers" if mode == "lines+markers" else "lines"
        style = SeriesStyle(mode=style_mode, color=_coerce_color(color, alpha), marker_size=1, line_width=max(1, width))
        series_data = normalize_xy(y=y, x=x, data=data)
        self._series.append(SeriesSpec(data=series_data, style=style, label=label))
        return self

    def bar(
        self,
        y: Any = None,
        *,
        x: Any = None,
        data: Any = None,
        label: str | None = None,
        color: tuple[int, int, int] | tuple[int, int, int, int] = (110, 169, 255),
        width: float = 0.8,
        alpha: float = 1.0,
    ) -> "Axes":
        if width <= 0:
            raise ValueError("bar width must be > 0")
        style = SeriesStyle(
            mode="bars",
            color=_coerce_color(color, alpha),
            marker_size=1,
            line_width=1,
            bar_width=float(width),
        )
        series_data = normalize_xy(y=y, x=x, data=data)
        self._series.append(SeriesSpec(data=series_data, style=style, label=label))
        return self

    def series(
        self,
        y: Any = None,
        *,
        x: Any = None,
        data: Any = None,
        label: str | None = None,
        mode: str = "markers",
        color: tuple[int, int, int] | tuple[int, int, int, int] = (62, 149, 255),
        size: int = 1,
        width: int = 1,
        alpha: float = 1.0,
    ) -> "Axes":
        if mode not in {"markers", "lines", "lines+markers"}:
            raise PlotDataError(f"unsupported mode: {mode}")
        style = SeriesStyle(
            mode=mode,  # type: ignore[arg-type]
            color=_coerce_color(color, alpha),
            marker_size=max(1, size),
            line_width=max(1, width),
        )
        series_data = normalize_xy(y=y, x=x, data=data)
        self._series.append(SeriesSpec(data=series_data, style=style, label=label))
        return self

    def set_limit_hysteresis(
        self,
        *,
        enabled: bool = True,
        deadband_ratio: float = 0.1,
        shrink_rate: float = 0.08,
    ) -> "Axes":
        if deadband_ratio < 0:
            raise ValueError("deadband_ratio must be >= 0")
        if shrink_rate < 0 or shrink_rate > 1:
            raise ValueError("shrink_rate must be in [0, 1]")
        self.limit_hysteresis_enabled = enabled
        self.limit_hysteresis_deadband_ratio = deadband_ratio
        self.limit_hysteresis_shrink_rate = shrink_rate
        return self

    def set_major_tick_steps(self, *, x: float | None = None, y: float | None = None) -> "Axes":
        if x is not None and x <= 0:
            raise ValueError("x major tick step must be > 0")
        if y is not None and y <= 0:
            raise ValueError("y major tick step must be > 0")
        self.x_major_tick_step = x
        self.y_major_tick_step = y
        return self

    def set_show_edge_x_tick_labels(self, show: bool) -> "Axes":
        self.show_edge_x_tick_labels = bool(show)
        return self

    def set_show_edge_y_tick_labels(self, show: bool) -> "Axes":
        self.show_edge_y_tick_labels = bool(show)
        return self

    def set_dynamic_defaults(self) -> "Axes":
        # Dynamic/live plots typically avoid edge labels to reduce visual jitter at bounds.
        self.show_edge_x_tick_labels = False
        self.show_edge_y_tick_labels = False
        self.include_zero_x_tick = True
        return self

    def set_include_zero_x_tick(self, include: bool) -> "Axes":
        self.include_zero_x_tick = bool(include)
        return self

    def set_x_tick_label_affine(self, *, scale: float = 1.0, offset: float = 0.0) -> "Axes":
        self.x_tick_label_scale = float(scale)
        self.x_tick_label_offset = float(offset)
        return self

    def set_preferred_panel_aspect_ratio(self, aspect_ratio: float | None) -> "Axes":
        if aspect_ratio is None:
            self.preferred_panel_aspect_ratio = None
            return self
        if aspect_ratio <= 0:
            raise ValueError("aspect_ratio must be > 0")
        self.preferred_panel_aspect_ratio = float(aspect_ratio)
        return self

    def set_x_tick_labels(self, labels: Sequence[str] | None) -> "Axes":
        if labels is None:
            self.x_tick_labels = None
            return self
        self.x_tick_labels = tuple(str(label) for label in labels)
        return self

    def set_viewport(self, *, xmin: float, xmax: float) -> "Axes":
        left = float(min(xmin, xmax))
        right = float(max(xmin, xmax))
        if right - left <= 1e-12:
            raise ValueError("viewport span must be > 0")
        self._viewport_x = (left, right)
        return self

    def clear_viewport(self) -> "Axes":
        self._viewport_x = None
        return self

    def pan_viewport(self, delta_x: float) -> "Axes":
        if self._viewport_x is None:
            raise PlotDataError("x viewport is not set")
        left, right = self._viewport_x
        delta = float(delta_x)
        self._viewport_x = (left + delta, right + delta)
        return self

    def zoom_viewport(self, factor: float, *, anchor_x: float | None = None) -> "Axes":
        if factor <= 0:
            raise ValueError("zoom factor must be > 0")
        source = self._viewport_x
        if source is None:
            source = self._last_resolved_x_viewport
        if source is None:
            raise PlotDataError("x viewport is not set")
        left, right = source
        center = float(anchor_x) if anchor_x is not None else (left + right) * 0.5
        span = max(1e-12, (right - left) / float(factor))
        self._viewport_x = (center - span * 0.5, center + span * 0.5)
        return self

    def last_resolved_viewport(self) -> tuple[float, float] | None:
        return self._last_resolved_x_viewport

    def _resolve_x_viewport(self, xmin: float, xmax: float) -> tuple[float, float]:
        if self._viewport_x is None:
            return (xmin, xmax)
        data_left = float(min(xmin, xmax))
        data_right = float(max(xmin, xmax))
        data_span = max(1e-12, data_right - data_left)
        requested_left, requested_right = self._viewport_x
        requested_span = max(1e-12, requested_right - requested_left)
        span = min(requested_span, data_span)
        start = max(data_left, min(data_right - span, requested_left))
        end = start + span
        return (start, end)

    @staticmethod
    def _ticks_within_range(ticks: np.ndarray, *, vmin: float, vmax: float) -> np.ndarray:
        if ticks.size == 0:
            return ticks
        step = float(abs(ticks[1] - ticks[0])) if ticks.size > 1 else max(1e-12, abs(vmax - vmin))
        eps = max(1e-12, step * 1e-6)
        mask = (ticks >= (vmin - eps)) & (ticks <= (vmax + eps))
        out = ticks[mask]
        if out.size == 0:
            return np.asarray([vmin, vmax], dtype=np.float64) if abs(vmax - vmin) > 1e-12 else np.asarray([vmin], dtype=np.float64)
        return out

    def _format_x_tick_labels(self, tick_x: np.ndarray) -> list[str]:
        if tick_x.size == 0:
            return []
        if self.x_tick_labels is not None:
            out: list[str] = []
            for xv in tick_x.tolist():
                idx = int(round(float(xv)))
                if abs(float(xv) - float(idx)) <= 1e-9 and 0 <= idx < len(self.x_tick_labels):
                    out.append(self.x_tick_labels[idx])
                else:
                    display = float(xv) * self.x_tick_label_scale + self.x_tick_label_offset
                    out.append(format_ticks_for_axis(np.asarray([display], dtype=np.float64))[0])
            return out
        display_ticks = tick_x.astype(np.float64, copy=False) * self.x_tick_label_scale + self.x_tick_label_offset
        return format_ticks_for_axis(display_ticks)

    def _x_tick_label_layout(self, labels: Sequence[str], plot_w: int, tick_font_px: float) -> XTickLabelLayout:
        if not labels:
            h = max(1, int(round(tick_font_px)))
            return XTickLabelLayout(rotate_deg=0, stride=1, font_px=tick_font_px, italic=False, max_w=0, max_h=h)
        natural_sizes = [text_size(lbl, font_size_px=tick_font_px) for lbl in labels]
        natural_max_w = max((w for w, _ in natural_sizes), default=0)
        slots = max(1, len(labels) - 1)
        spacing = max(1.0, float(plot_w) / float(slots))
        has_long_labels = max((len(lbl) for lbl in labels), default=0) >= 12
        rotate = natural_max_w > spacing * 0.78 or (has_long_labels and len(labels) >= 3)
        rotate_deg = 65 if rotate else 0
        font_px = tick_font_px * 0.88 if rotate else tick_font_px
        italic = rotate
        rotated_sizes = [text_size(lbl, font_size_px=font_px, rotate_deg=rotate_deg, italic=italic) for lbl in labels]
        draw_max_w = max((w for w, _ in rotated_sizes), default=0)
        draw_max_h = max((h for _, h in rotated_sizes), default=max(1, int(round(font_px))))
        min_gap = max(2, int(round(font_px * 0.2)))
        stride = max(1, int(np.ceil((draw_max_w + min_gap) / spacing)))
        return XTickLabelLayout(
            rotate_deg=rotate_deg,
            stride=stride,
            font_px=font_px,
            italic=italic,
            max_w=draw_max_w,
            max_h=draw_max_h,
        )

    @staticmethod
    def _contains_zero_tick(ticks: np.ndarray) -> bool:
        if ticks.size == 0:
            return False
        step = float(abs(ticks[1] - ticks[0])) if ticks.size > 1 else 1.0
        eps = max(1e-12, step * 1e-6)
        return bool(np.any(np.isclose(ticks, 0.0, rtol=0.0, atol=eps)))

    def add_reference_line(
        self,
        axis: Literal["x", "y"],
        value: float,
        *,
        color: tuple[int, int, int, int] | None = None,
        width: int = 1,
    ) -> "Axes":
        if axis not in {"x", "y"}:
            raise ValueError("axis must be 'x' or 'y'")
        if width <= 0:
            raise ValueError("width must be > 0")
        self.reference_lines.append(
            ReferenceLine(
                axis=axis,
                value=float(value),
                color=self.reference_line_color if color is None else color,
                width=width,
            )
        )
        return self

    def clear_reference_lines(self) -> "Axes":
        self.reference_lines.clear()
        return self

    def set_legend_position(self, x_px: int, y_px: int) -> "Axes":
        self.legend_position_px = (int(x_px), int(y_px))
        return self

    def legend_bounds(self) -> tuple[int, int, int, int] | None:
        return self._legend_bounds_px

    def update_legend_drag(self, pointer_x: float, pointer_y: float, is_down: bool) -> bool:
        px = int(round(pointer_x))
        py = int(round(pointer_y))
        moved = False
        bounds = self._legend_bounds_px
        if is_down:
            if not self._legend_drag_active and bounds is not None:
                x, y, w, h = bounds
                inside = (px >= x) and (px < x + w) and (py >= y) and (py < y + h)
                if inside:
                    self._legend_drag_active = True
                    self._legend_drag_offset_px = (px - x, py - y)
            if self._legend_drag_active:
                ox, oy = self._legend_drag_offset_px
                next_pos = (px - ox, py - oy)
                if self._legend_layout is not None:
                    next_pos = self._clamp_legend_position(self._legend_layout, next_pos)
                if self.legend_position_px != next_pos:
                    old_bounds = self._legend_bounds_px
                    self.legend_position_px = next_pos
                    self._resolve_legend_bounds()
                    if old_bounds is not None:
                        ox0, oy0, ow, oh = old_bounds
                        new_bounds = self._legend_bounds_px or old_bounds
                        nx0, ny0, nw, nh = new_bounds
                        rx0 = min(ox0, nx0)
                        ry0 = min(oy0, ny0)
                        rx1 = max(ox0 + ow, nx0 + nw)
                        ry1 = max(oy0 + oh, ny0 + nh)
                        move_dirty = (rx0, ry0, rx1 - rx0, ry1 - ry0)
                        self._legend_dirty_rect_px = _union_rect(self._legend_dirty_rect_px, move_dirty)
                    moved = True
        else:
            self._legend_drag_active = False
        return moved

    def take_legend_dirty_rect(self) -> tuple[int, int, int, int] | None:
        rect = self._legend_dirty_rect_px
        self._legend_dirty_rect_px = None
        return rect

    def _build_legend_layout(
        self,
        *,
        tick_font_px: float,
        plot_x0: int,
        plot_y0: int,
        plot_w: int,
        plot_h: int,
    ) -> LegendLayout | None:
        line_series = [spec for spec in self._series if spec.style.mode in {"lines", "lines+markers"}]
        if len(line_series) < 2:
            return None
        entries = tuple(
            LegendEntry(
                label=(spec.label if spec.label is not None and spec.label.strip() else f"series {i+1}"),
                mode=spec.style.mode,
                color=spec.style.color,
                marker_size=max(2, spec.style.marker_size),
            )
            for i, spec in enumerate(line_series)
        )
        legend_font_px = max(10.0, tick_font_px * 0.9)
        swatch_w = int(max(10, legend_font_px * 1.6))
        swatch_h = int(max(6, legend_font_px * 0.9))
        item_gap = int(max(3, legend_font_px * 0.5))
        pad = int(max(5, legend_font_px * 0.55))
        text_w = max((text_size(entry.label, font_size_px=legend_font_px)[0] for entry in entries), default=0)
        item_h = max(swatch_h, int(round(legend_font_px)))
        box_w = pad * 2 + swatch_w + 6 + text_w
        box_h = pad * 2 + len(entries) * item_h + (len(entries) - 1) * item_gap
        return LegendLayout(
            entries=entries,
            plot_x0=plot_x0,
            plot_y0=plot_y0,
            plot_w=plot_w,
            plot_h=plot_h,
            legend_font_px=legend_font_px,
            swatch_w=swatch_w,
            swatch_h=swatch_h,
            item_gap=item_gap,
            pad=pad,
            item_h=item_h,
            box_w=box_w,
            box_h=box_h,
        )

    def _clamp_legend_position(self, layout: LegendLayout, requested: tuple[int, int] | None) -> tuple[int, int]:
        if requested is None:
            x = max(layout.plot_x0 + 4, layout.plot_x0 + layout.plot_w - layout.box_w - 6)
            y = max(layout.plot_y0 + 4, layout.plot_y0 + 6)
        else:
            x = int(requested[0])
            y = int(requested[1])
        x = max(layout.plot_x0 + 2, min(layout.plot_x0 + layout.plot_w - layout.box_w - 2, x))
        y = max(layout.plot_y0 + 2, min(layout.plot_y0 + layout.plot_h - layout.box_h - 2, y))
        return (x, y)

    def _resolve_legend_bounds(self) -> tuple[int, int, int, int] | None:
        layout = self._legend_layout
        if layout is None:
            self._legend_bounds_px = None
            return None
        x, y = self._clamp_legend_position(layout, self.legend_position_px)
        self.legend_position_px = (x, y)
        self._legend_bounds_px = (x, y, layout.box_w, layout.box_h)
        return self._legend_bounds_px

    def _draw_legend(self, canvas: np.ndarray, *, x_offset: int = 0, y_offset: int = 0) -> None:
        layout = self._legend_layout
        bounds = self._resolve_legend_bounds()
        if layout is None or bounds is None:
            return
        legend_x, legend_y, box_w, box_h = bounds
        draw_x = legend_x - x_offset
        draw_y = legend_y - y_offset
        for yy in range(draw_y, draw_y + box_h):
            draw_hline(
                canvas,
                draw_x,
                draw_x + box_w - 1,
                yy,
                (10, 14, 20, 170),
            )
        draw_hline(canvas, draw_x, draw_x + box_w - 1, draw_y, self.frame_color)
        draw_hline(canvas, draw_x, draw_x + box_w - 1, draw_y + box_h - 1, self.frame_color)
        draw_vline(canvas, draw_x, draw_y, draw_y + box_h - 1, self.frame_color)
        draw_vline(canvas, draw_x + box_w - 1, draw_y, draw_y + box_h - 1, self.frame_color)

        for i, entry in enumerate(layout.entries):
            row_y = draw_y + layout.pad + i * (layout.item_h + layout.item_gap) + layout.item_h // 2
            sw_x0 = draw_x + layout.pad
            sw_x1 = sw_x0 + layout.swatch_w - 1
            if entry.mode in {"lines", "lines+markers"}:
                draw_hline(canvas, sw_x0, sw_x1, row_y, entry.color)
            if entry.mode in {"markers", "lines+markers"}:
                marker_x = np.asarray([sw_x0 + layout.swatch_w // 2], dtype=np.int32)
                marker_y = np.asarray([row_y], dtype=np.int32)
                draw_markers(canvas, marker_x, marker_y, color=entry.color, size=entry.marker_size)
            draw_text(
                canvas,
                sw_x1 + 6,
                int(round(row_y - layout.legend_font_px * 0.5)),
                entry.label,
                self.text_color,
                font_size_px=layout.legend_font_px,
            )

    def render_legend_patch(self, dirty_rect: tuple[int, int, int, int]) -> tuple[int, int, np.ndarray] | None:
        if self._last_static_rgba is None:
            return None
        x, y, width, height = dirty_rect
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(self.figure.width, x0 + int(width))
        y1 = min(self.figure.height, y0 + int(height))
        if x1 <= x0 or y1 <= y0:
            return None
        patch = self._last_static_rgba[y0:y1, x0:x1].copy()
        if self._last_data_rgba is not None:
            blit(patch, self._last_data_rgba[y0:y1, x0:x1])
        self._draw_legend(patch, x_offset=x0, y_offset=y0)
        return (x0, y0, patch)

    def last_plot_rect(self) -> tuple[int, int, int, int] | None:
        return self._last_plot_rect_px

    def last_limits(self) -> DataLimits | None:
        return self._last_limits

    def last_static_rgba(self) -> np.ndarray | None:
        if self._last_static_rgba is None:
            return None
        return self._last_static_rgba.copy()

    def last_data_rgba(self) -> np.ndarray | None:
        if self._last_data_rgba is None:
            return None
        return self._last_data_rgba.copy()

    def last_x_rule_rect(self) -> tuple[int, int, int, int] | None:
        return self._last_x_rule_rect_px

    def last_x_tick_label_layout(self) -> tuple[int, int]:
        return (self._last_x_tick_label_rotate_deg, self._last_x_tick_label_stride)

    def last_tick_values(self) -> tuple[tuple[float, ...], tuple[float, ...]]:
        return (self._last_tick_x, self._last_tick_y)

    def render_x_rule_patch(
        self,
        xmin: float,
        xmax: float,
        *,
        visible_min: float | None = None,
        visible_max: float | None = None,
    ) -> tuple[int, int, np.ndarray] | None:
        if self._last_x_rule_bg is None or self._last_x_rule_rect_px is None:
            return None
        x0, y0, w, h = self._last_x_rule_rect_px
        if w <= 0 or h <= 0:
            return None
        patch = self._last_x_rule_bg.copy()
        tick_x = generate_nice_ticks(
            float(xmin),
            float(xmax),
            max(5, w // 120),
            preferred_step=self.x_major_tick_step,
        )
        if self.include_zero_x_tick:
            tick_x = _inject_zero_tick(tick_x, vmin=float(xmin), vmax=float(xmax))
        tick_x = self._ticks_within_range(tick_x, vmin=float(xmin), vmax=float(xmax))
        labels = self._format_x_tick_labels(tick_x)
        x_tick_layout = self._x_tick_label_layout(labels, w, self._last_x_tick_font_px)
        transform = build_transform(
            limits=DataLimits(xmin=float(xmin), xmax=float(xmax), ymin=0.0, ymax=1.0),
            width=w,
            height=max(2, h),
        )
        for idx, (xv, label) in enumerate(zip(tick_x.tolist(), labels, strict=False)):
            if visible_min is not None and xv < visible_min:
                continue
            if visible_max is not None and xv > visible_max:
                continue
            if (not self.show_edge_x_tick_labels) and (idx == 0 or idx == len(labels) - 1):
                continue
            px, _ = map_to_pixels(
                np.asarray([xv], dtype=np.float64),
                np.asarray([0.0], dtype=np.float64),
                transform,
                w,
                max(2, h),
            )
            pxi = int(px[0])
            draw_vline(
                patch,
                pxi,
                0,
                min(h - 1, self._last_x_tick_mark_len),
                self.axis_color,
            )
            if x_tick_layout.stride > 1 and (idx % x_tick_layout.stride) != 0:
                continue
            tx, _ = text_size(
                label,
                font_size_px=self._last_x_tick_font_px,
                rotate_deg=x_tick_layout.rotate_deg,
                italic=self._last_x_tick_italic,
            )
            label_x = pxi - tx if x_tick_layout.rotate_deg != 0 else pxi - tx // 2
            draw_text(
                patch,
                label_x,
                int(round(self._last_x_tick_mark_len + self._last_x_tick_pad)),
                label,
                self.text_color,
                font_size_px=self._last_x_tick_font_px,
                embolden_px=1,
                rotate_deg=x_tick_layout.rotate_deg,
                italic=self._last_x_tick_italic,
            )
        x_label_w, _ = text_size(self.x_label_bottom, font_size_px=self._last_label_font_px)
        draw_text(
            patch,
            max(0, (w // 2) - (x_label_w // 2)),
            max(2, int(round(self._last_x_tick_mark_len + self._last_x_tick_pad + self._last_max_x_tick_h + self._last_x_label_gap))),
            self.x_label_bottom,
            self.text_color,
            font_size_px=self._last_label_font_px,
            embolden_px=2,
        )
        return (x0, y0, patch)

    def _plot_viewport(self) -> tuple[int, int, int, int]:
        left = min(self._gutter_left, max(8, self.figure.width // 4))
        right = min(self._gutter_right, max(8, self.figure.width // 8))
        top = min(self._gutter_top, max(8, self.figure.height // 5))
        bottom = min(self._gutter_bottom, max(8, self.figure.height // 4))
        x0 = left
        y0 = top
        width = self.figure.width - left - right
        height = self.figure.height - top - bottom
        if width <= 1 or height <= 1:
            raise PlotDataError("figure too small for plotting viewport")
        return x0, y0, width, height

    def _combined_limits(self) -> tuple[float, float, float, float]:
        if not self._series:
            raise PlotDataError("no series in axes")

        mins_x: list[float] = []
        maxs_x: list[float] = []
        mins_y: list[float] = []
        maxs_y: list[float] = []

        for spec in self._series:
            # Recompute finiteness mask at render-time so dynamic in-place updates
            # (rolling windows with NaNs) stay aligned with limits and drawing.
            live_mask = np.isfinite(spec.data.x) & np.isfinite(spec.data.y)
            if not np.any(live_mask):
                continue
            limits = compute_limits(spec.data.x, spec.data.y, live_mask)
            if spec.style.mode == "bars":
                xvals = spec.data.x[live_mask]
                yvals = spec.data.y[live_mask]
                half_width = max(1e-9, float(spec.style.bar_width) * 0.5)
                edge_pad = max(1e-9, half_width * 0.35)
                limits = DataLimits(
                    xmin=min(limits.xmin, float(np.min(xvals - half_width - edge_pad))),
                    xmax=max(limits.xmax, float(np.max(xvals + half_width + edge_pad))),
                    ymin=min(limits.ymin, 0.0, float(np.min(yvals))),
                    ymax=max(limits.ymax, 0.0, float(np.max(yvals))),
                )
            mins_x.append(limits.xmin)
            maxs_x.append(limits.xmax)
            mins_y.append(limits.ymin)
            maxs_y.append(limits.ymax)
        if not mins_x:
            raise PlotDataError("series contains no finite points")
        return min(mins_x), max(maxs_x), min(mins_y), max(maxs_y)

    def _apply_limit_hysteresis(self, raw: DataLimits) -> DataLimits:
        if not self.limit_hysteresis_enabled:
            self._previous_limits = raw
            return raw
        prev = self._previous_limits
        if prev is None:
            self._previous_limits = raw
            return raw

        deadband_x = max(1e-9, (raw.xmax - raw.xmin) * self.limit_hysteresis_deadband_ratio)
        deadband_y = max(1e-9, (raw.ymax - raw.ymin) * self.limit_hysteresis_deadband_ratio)

        xmin = prev.xmin
        xmax = prev.xmax
        ymin = prev.ymin
        ymax = prev.ymax

        # Expand immediately when new data breaches current limits.
        if raw.xmin < xmin:
            xmin = raw.xmin
        if raw.xmax > xmax:
            xmax = raw.xmax
        if raw.ymin < ymin:
            ymin = raw.ymin
        if raw.ymax > ymax:
            ymax = raw.ymax

        # Contract slowly only when raw limits move inward past deadband.
        if raw.xmin > xmin + deadband_x:
            xmin = xmin + (raw.xmin - xmin) * self.limit_hysteresis_shrink_rate
        if raw.xmax < xmax - deadband_x:
            xmax = xmax - (xmax - raw.xmax) * self.limit_hysteresis_shrink_rate
        if raw.ymin > ymin + deadband_y:
            ymin = ymin + (raw.ymin - ymin) * self.limit_hysteresis_shrink_rate
        if raw.ymax < ymax - deadband_y:
            ymax = ymax - (ymax - raw.ymax) * self.limit_hysteresis_shrink_rate

        out = DataLimits(xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax)
        self._previous_limits = out
        return out

    def render(self) -> np.ndarray:
        if not self._series:
            raise PlotDataError("cannot render empty axes")

        base = new_canvas(self.figure.width, self.figure.height, color=self.figure.style.background)
        scale_base = min(self.figure.width, self.figure.height)
        tick_font_px = max(12.0, min(28.0, scale_base * 0.03))
        label_font_px = max(11.0, min(24.0, scale_base * 0.032))
        title_font_px = max(12.0, min(30.0, scale_base * 0.038))
        tick_half_h = int(round(tick_font_px * 0.5))
        data_xmin, data_xmax, ymin, ymax = self._combined_limits()
        limits = self._apply_limit_hysteresis(DataLimits(xmin=data_xmin, xmax=data_xmax, ymin=ymin, ymax=ymax))
        xmin, xmax = self._resolve_x_viewport(limits.xmin, limits.xmax)
        limits = DataLimits(xmin=xmin, xmax=xmax, ymin=limits.ymin, ymax=limits.ymax)
        xmin, xmax, ymin, ymax = limits.xmin, limits.xmax, limits.ymin, limits.ymax
        self._last_resolved_x_viewport = (xmin, xmax)
        self._last_limits = limits
        y_chunks: list[np.ndarray] = []
        for spec in self._series:
            live_mask = np.isfinite(spec.data.x) & np.isfinite(spec.data.y)
            if np.any(live_mask):
                y_chunks.append(spec.data.y[live_mask])
        if not y_chunks:
            raise PlotDataError("series contains no finite points")
        y_all = np.concatenate(y_chunks).astype(np.float64, copy=False)
        y_resolution = infer_resolution(y_all)
        preferred_y_step = self.y_major_tick_step if self.y_major_tick_step is not None else preferred_major_step_from_resolution(y_resolution)
        preferred_x_step = self.x_major_tick_step
        if preferred_x_step is None:
            bar_x_values: list[np.ndarray] = []
            for spec in self._series:
                if spec.style.mode != "bars":
                    continue
                mask = np.isfinite(spec.data.x) & np.isfinite(spec.data.y)
                if np.any(mask):
                    bar_x_values.append(spec.data.x[mask].astype(np.float64, copy=False))
            if bar_x_values:
                bx = np.unique(np.concatenate(bar_x_values))
                if bx.size >= 2:
                    diffs = np.diff(bx)
                    positive = diffs[diffs > 1e-12]
                    if positive.size > 0:
                        preferred_x_step = float(np.min(positive))

        # First pass tick estimates for layout sizing.
        provisional_w = max(120, self.figure.width - 80)
        provisional_h = max(80, self.figure.height - 80)
        tick_x_probe = generate_nice_ticks(xmin, xmax, max(5, provisional_w // 120), preferred_step=preferred_x_step)
        if self.include_zero_x_tick:
            tick_x_probe = _inject_zero_tick(tick_x_probe, vmin=xmin, vmax=xmax)
        tick_x_probe = self._ticks_within_range(tick_x_probe, vmin=xmin, vmax=xmax)
        tick_y_probe = generate_nice_ticks(ymin, ymax, max(4, provisional_h // 140), preferred_step=preferred_y_step)
        tick_y_probe = self._ticks_within_range(tick_y_probe, vmin=ymin, vmax=ymax)
        x_tick_labels_probe = self._format_x_tick_labels(tick_x_probe)
        x_tick_layout_probe = self._x_tick_label_layout(x_tick_labels_probe, provisional_w, tick_font_px)
        y_tick_labels_probe = format_ticks_for_axis(tick_y_probe)
        max_x_tick_h = x_tick_layout_probe.max_h
        max_x_tick_w = x_tick_layout_probe.max_w
        max_y_tick_w = max((text_size(lbl, font_size_px=tick_font_px)[0] for lbl in y_tick_labels_probe), default=0)
        x_label_w, x_label_h = text_size(self.x_label_bottom, font_size_px=label_font_px)
        y_label_w, y_label_h = text_size(self.y_label_left, font_size_px=label_font_px, rotate_deg=270)
        title_h = text_size(self.title, font_size_px=title_font_px)[1] if self.title else 0

        x_tick_pad = int(max(4.0, tick_font_px * 0.5))
        x_tick_mark_len = int(max(5.0, tick_font_px * 0.55))
        x_label_gap = int(max(10.0, label_font_px * 0.65))
        y_tick_pad = int(max(4.0, tick_font_px * 0.4))
        y_label_gap = int(max(8.0, label_font_px * 0.45))
        y_axis_label_pad = int(max(12.0, label_font_px * 0.75))
        left = int(max(18, max_y_tick_w + y_tick_pad + y_label_w + y_label_gap + y_axis_label_pad + 10))
        if x_tick_layout_probe.rotate_deg != 0:
            left = int(max(left, x_tick_layout_probe.max_w + 10))
        right_tick_pad = int(max(8, max_x_tick_w // 2 + 6))
        right = int(
            max(
                right_tick_pad,
                text_size(self.y_label_right, font_size_px=label_font_px)[0] + 10
                if self.show_right_axis and self.y_label_right
                else right_tick_pad,
            )
        )
        top = int(max(10, title_h + 10))
        extra_rot_bottom = int(max(0.0, max_x_tick_h * 0.22)) if x_tick_layout_probe.rotate_deg != 0 else 0
        bottom = int(max(12, x_tick_mark_len + max_x_tick_h + x_tick_pad + x_label_h + x_label_gap + 10 + extra_rot_bottom))

        # Bound gutters for small figures so we always preserve a drawable plot area.
        left = min(left, max(6, self.figure.width // 3))
        right = min(right, max(4, self.figure.width // 4))
        top = min(top, max(4, self.figure.height // 3))
        bottom = min(bottom, max(6, self.figure.height // 3))

        plot_x0 = left
        plot_y0 = top
        plot_w = self.figure.width - left - right
        plot_h = self.figure.height - top - bottom
        if plot_w <= 1:
            excess = 2 - plot_w
            trim_left = min(left - 2, max(0, excess))
            left -= trim_left
            excess -= trim_left
            right = max(2, right - excess)
            plot_x0 = left
            plot_w = self.figure.width - left - right
        if plot_h <= 1:
            excess = 2 - plot_h
            trim_top = min(top - 2, max(0, excess))
            top -= trim_top
            excess -= trim_top
            bottom = max(2, bottom - excess)
            plot_y0 = top
            plot_h = self.figure.height - top - bottom
        if plot_w <= 1 or plot_h <= 1:
            raise PlotDataError("figure too small for plotting viewport")
        self._last_plot_rect_px = (plot_x0, plot_y0, plot_w, plot_h)
        self._last_tick_font_px = tick_font_px
        self._last_label_font_px = label_font_px
        self._last_x_tick_pad = x_tick_pad
        self._last_x_tick_mark_len = x_tick_mark_len
        self._last_max_x_tick_h = max_x_tick_h
        self._last_x_label_gap = x_label_gap

        frame_key = (self.figure.width, self.figure.height, self.frame_color, self.plot_bg_color, plot_x0, plot_y0, plot_w, plot_h)
        if self._cache.frame_key != frame_key or self._cache.frame_template is None:
            frame = new_canvas(self.figure.width, self.figure.height, color=(0, 0, 0, 0))
            draw_hline(frame, 0, self.figure.width - 1, 0, self.frame_color)
            draw_hline(frame, 0, self.figure.width - 1, self.figure.height - 1, self.frame_color)
            draw_vline(frame, 0, 0, self.figure.height - 1, self.frame_color)
            draw_vline(frame, self.figure.width - 1, 0, self.figure.height - 1, self.frame_color)
            for yy in range(plot_y0, plot_y0 + plot_h):
                draw_hline(frame, plot_x0, plot_x0 + plot_w - 1, yy, self.plot_bg_color)
            self._cache.frame_key = frame_key
            self._cache.frame_template = frame

        # Final ticks based on resolved viewport.
        tick_x = generate_nice_ticks(xmin, xmax, max(5, plot_w // 120), preferred_step=preferred_x_step)
        if self.include_zero_x_tick:
            tick_x = _inject_zero_tick(tick_x, vmin=xmin, vmax=xmax)
        tick_x = self._ticks_within_range(tick_x, vmin=xmin, vmax=xmax)
        tick_y = generate_nice_ticks(ymin, ymax, max(4, plot_h // 140), preferred_step=preferred_y_step)
        tick_y = self._ticks_within_range(tick_y, vmin=ymin, vmax=ymax)
        x_tick_labels = self._format_x_tick_labels(tick_x)
        x_tick_layout = self._x_tick_label_layout(x_tick_labels, plot_w, tick_font_px)
        x_tick_font_px = x_tick_layout.font_px
        self._last_x_tick_font_px = x_tick_font_px
        self._last_x_tick_italic = x_tick_layout.italic
        self._last_x_tick_label_rotate_deg = x_tick_layout.rotate_deg
        self._last_x_tick_label_stride = x_tick_layout.stride
        self._last_tick_x = tuple(float(v) for v in tick_x.tolist())
        self._last_tick_y = tuple(float(v) for v in tick_y.tolist())
        y_tick_labels = format_ticks_for_axis(tick_y)
        grid_key = (
            plot_w,
            plot_h,
            round(xmin, 12),
            round(xmax, 12),
            round(ymin, 12),
            round(ymax, 12),
            self.grid_color,
            self.show_zero_reference_lines,
            self.show_minor_dot_grid,
            self.minor_dot_grid_max_points,
            tuple((line.axis, round(line.value, 12), line.color, line.width) for line in self.reference_lines),
        )
        if self._cache.grid_key != grid_key or self._cache.grid_template is None:
            grid = new_canvas(self.figure.width, self.figure.height, color=(0, 0, 0, 0))
            transform = build_transform(
                limits=DataLimits(xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax),
                width=plot_w,
                height=plot_h,
            )
            for xv in tick_x:
                px, _ = map_to_pixels(np.asarray([xv], dtype=np.float64), np.asarray([ymin], dtype=np.float64), transform, plot_w, plot_h)
                draw_vline(grid, plot_x0 + int(px[0]), plot_y0, plot_y0 + plot_h - 1, self.grid_color)
            for yv in tick_y:
                _, py = map_to_pixels(np.asarray([xmin], dtype=np.float64), np.asarray([yv], dtype=np.float64), transform, plot_w, plot_h)
                draw_hline(grid, plot_x0, plot_x0 + plot_w - 1, plot_y0 + int(py[0]), self.grid_color)
            ref_lines: list[ReferenceLine] = list(self.reference_lines)
            if self.show_zero_reference_lines:
                if self._contains_zero_tick(tick_x):
                    ref_lines.append(ReferenceLine(axis="x", value=0.0, color=self.reference_line_color, width=1))
                if self._contains_zero_tick(tick_y):
                    ref_lines.append(ReferenceLine(axis="y", value=0.0, color=self.reference_line_color, width=1))
            for ref in ref_lines:
                if ref.axis == "x":
                    if ref.value < xmin or ref.value > xmax:
                        continue
                    px, _ = map_to_pixels(
                        np.asarray([ref.value], dtype=np.float64),
                        np.asarray([ymin], dtype=np.float64),
                        transform,
                        plot_w,
                        plot_h,
                    )
                    gx = plot_x0 + int(px[0])
                    for offset in range(max(1, ref.width)):
                        draw_vline(grid, gx + offset, plot_y0, plot_y0 + plot_h - 1, ref.color)
                else:
                    if ref.value < ymin or ref.value > ymax:
                        continue
                    _, py = map_to_pixels(
                        np.asarray([xmin], dtype=np.float64),
                        np.asarray([ref.value], dtype=np.float64),
                        transform,
                        plot_w,
                        plot_h,
                    )
                    gy = plot_y0 + int(py[0])
                    for offset in range(max(1, ref.width)):
                        draw_hline(grid, plot_x0, plot_x0 + plot_w - 1, gy + offset, ref.color)
            # Minor dot grid at tenth subdivisions of major steps.
            major_x_step = float(abs(tick_x[1] - tick_x[0])) if tick_x.size > 1 else 1.0
            major_y_step = float(abs(tick_y[1] - tick_y[0])) if tick_y.size > 1 else 1.0
            minor_x_step = major_x_step / 10.0
            minor_y_step = major_y_step / 10.0
            if self.show_minor_dot_grid and minor_x_step > 0 and minor_y_step > 0:
                x_minor = np.arange(
                    np.floor(xmin / minor_x_step) * minor_x_step,
                    np.ceil(xmax / minor_x_step) * minor_x_step + 0.5 * minor_x_step,
                    minor_x_step,
                    dtype=np.float64,
                )
                y_minor = np.arange(
                    np.floor(ymin / minor_y_step) * minor_y_step,
                    np.ceil(ymax / minor_y_step) * minor_y_step + 0.5 * minor_y_step,
                    minor_y_step,
                    dtype=np.float64,
                )
                dot_color = self.minor_dot_grid_color
                x_minor_px, _ = map_to_pixels(
                    x_minor,
                    np.full(x_minor.shape, ymin, dtype=np.float64),
                    transform,
                    plot_w,
                    plot_h,
                )
                _, y_minor_px = map_to_pixels(
                    np.full(y_minor.shape, xmin, dtype=np.float64),
                    y_minor,
                    transform,
                    plot_w,
                    plot_h,
                )
                x_unique = np.unique(x_minor_px)
                y_unique = np.unique(y_minor_px)
                total = int(x_unique.size * y_unique.size)
                stride = 1
                max_points = max(1000, int(self.minor_dot_grid_max_points))
                if total > max_points:
                    stride = int(np.ceil(np.sqrt(total / max_points)))
                for px in x_unique[::stride].tolist():
                    gx = plot_x0 + int(px)
                    for py in y_unique[::stride].tolist():
                        gy = plot_y0 + int(py)
                        draw_pixel(grid, gx, gy, dot_color)
            self._cache.grid_key = grid_key
            self._cache.grid_template = grid

        blit(base, self._cache.frame_template)
        blit(base, self._cache.grid_template)

        transform = build_transform(
            limits=DataLimits(xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax),
            width=plot_w,
            height=plot_h,
        )

        drawing = new_canvas(self.figure.width, self.figure.height, color=(0, 0, 0, 0))
        # Pass 0: bars at the back so lines/markers remain visible when combined.
        for spec in self._series:
            if spec.style.mode != "bars":
                continue
            live_mask = np.isfinite(spec.data.x) & np.isfinite(spec.data.y)
            if not np.any(live_mask):
                continue
            xvals = spec.data.x[live_mask]
            yvals = spec.data.y[live_mask]
            half_width = max(1e-9, float(spec.style.bar_width) * 0.5)
            view_mask = (xvals + half_width >= xmin) & (xvals - half_width <= xmax)
            if not np.any(view_mask):
                continue
            xvals = xvals[view_mask]
            yvals = yvals[view_mask]
            zeros = np.zeros_like(yvals, dtype=np.float64)
            px_left, _ = map_to_pixels(xvals - half_width, zeros, transform, plot_w, plot_h)
            px_right, _ = map_to_pixels(xvals + half_width, zeros, transform, plot_w, plot_h)
            _, py_zero = map_to_pixels(xvals, zeros, transform, plot_w, plot_h)
            _, py_vals = map_to_pixels(xvals, yvals, transform, plot_w, plot_h)
            for i in range(xvals.size):
                x0_bar = int(min(px_left[i], px_right[i]))
                x1_bar = int(max(px_left[i], px_right[i]))
                if x1_bar == x0_bar:
                    x1_bar = min(plot_w - 1, x0_bar + 1)
                y0_bar = int(min(py_zero[i], py_vals[i]))
                y1_bar = int(max(py_zero[i], py_vals[i]))
                _draw_filled_rect(
                    drawing,
                    x0=plot_x0 + x0_bar,
                    y0=plot_y0 + y0_bar,
                    x1=plot_x0 + x1_bar,
                    y1=plot_y0 + y1_bar,
                    color=spec.style.color,
                )
        # Pass 1: lines under markers for clear point visibility.
        for spec in self._series:
            if spec.style.mode in {"lines", "lines+markers"}:
                live_mask = np.isfinite(spec.data.x) & np.isfinite(spec.data.y)
                live_mask = live_mask & (spec.data.x >= xmin) & (spec.data.x <= xmax)
                for seg_start, seg_end in _contiguous_true_runs(live_mask):
                    xvals = spec.data.x[seg_start:seg_end]
                    yvals = spec.data.y[seg_start:seg_end]
                    if xvals.size < 2:
                        continue
                    px, py = map_to_pixels(xvals, yvals, transform, plot_w, plot_h)
                    if px.size > plot_w:
                        px, py = downsample_by_pixel_column(px, py, width=plot_w, mode="lines")
                    px = px + plot_x0
                    py = py + plot_y0
                    draw_polyline(drawing, px, py, color=spec.style.color, width=spec.style.line_width)
        # Pass 2: markers on top.
        for spec in self._series:
            if spec.style.mode not in {"markers", "lines+markers"}:
                continue
            visible_mask = np.isfinite(spec.data.x) & np.isfinite(spec.data.y)
            visible_mask = visible_mask & (spec.data.x >= xmin) & (spec.data.x <= xmax)
            xvals = spec.data.x[visible_mask]
            yvals = spec.data.y[visible_mask]
            if xvals.size == 0:
                continue
            px, py = map_to_pixels(xvals, yvals, transform, plot_w, plot_h)
            if px.size > plot_w:
                px, py = downsample_by_pixel_column(px, py, width=plot_w, mode="markers")
            px = px + plot_x0
            py = py + plot_y0
            marker_size = max(2, spec.style.marker_size)
            draw_markers(drawing, px, py, color=spec.style.color, size=marker_size)

        base_no_data = base.copy()
        self._last_data_rgba = drawing.copy()
        blit(base, drawing)

        draw_hline(base, plot_x0, plot_x0 + plot_w - 1, plot_y0 + plot_h - 1, self.axis_color)
        draw_vline(base, plot_x0, plot_y0, plot_y0 + plot_h - 1, self.axis_color)
        draw_hline(base_no_data, plot_x0, plot_x0 + plot_w - 1, plot_y0 + plot_h - 1, self.axis_color)
        draw_vline(base_no_data, plot_x0, plot_y0, plot_y0 + plot_h - 1, self.axis_color)
        if self.show_top_axis:
            draw_hline(base, plot_x0, plot_x0 + plot_w - 1, plot_y0, self.axis_color)
            draw_hline(base_no_data, plot_x0, plot_x0 + plot_w - 1, plot_y0, self.axis_color)
        if self.show_right_axis:
            draw_vline(base, plot_x0 + plot_w - 1, plot_y0, plot_y0 + plot_h - 1, self.axis_color)
            draw_vline(base_no_data, plot_x0 + plot_w - 1, plot_y0, plot_y0 + plot_h - 1, self.axis_color)
        x_rule_y0 = min(self.figure.height, plot_y0 + plot_h)
        x_rule_h = max(0, self.figure.height - x_rule_y0)
        self._last_x_rule_rect_px = (plot_x0, x_rule_y0, plot_w, x_rule_h)
        self._last_x_rule_bg = base_no_data[x_rule_y0 : x_rule_y0 + x_rule_h, plot_x0 : plot_x0 + plot_w].copy()

        self._legend_layout = self._build_legend_layout(
            tick_font_px=tick_font_px,
            plot_x0=plot_x0,
            plot_y0=plot_y0,
            plot_w=plot_w,
            plot_h=plot_h,
        )

        text_key = (
            tuple(x_tick_labels),
            tuple(y_tick_labels),
            self.title,
            self.x_label_bottom,
            self.y_label_left,
            self.x_label_top,
            self.y_label_right,
            plot_x0,
            plot_y0,
            plot_w,
            plot_h,
            self.text_color,
            round(tick_font_px, 2),
            round(label_font_px, 2),
            round(title_font_px, 2),
            self.show_edge_x_tick_labels,
            self.show_edge_y_tick_labels,
            x_tick_mark_len,
            round(x_tick_font_px, 2),
            x_tick_layout.italic,
            x_tick_layout.rotate_deg,
            x_tick_layout.stride,
            self.include_zero_x_tick,
            round(self.x_tick_label_scale, 12),
            round(self.x_tick_label_offset, 12),
        )
        if self._cache.text_key != text_key or self._cache.text_template is None:
            text_layer = new_canvas(self.figure.width, self.figure.height, color=(0, 0, 0, 0))
            if self.title:
                tw, th = text_size(self.title, font_size_px=title_font_px)
                draw_text(
                    text_layer,
                    max(2, (self.figure.width - tw) // 2),
                    max(2, int(round((top - th) * 0.5))),
                    self.title,
                    self.text_color,
                    font_size_px=title_font_px,
                    embolden_px=2,
                )

            for idx, (xv, label) in enumerate(zip(tick_x.tolist(), x_tick_labels, strict=False)):
                if (not self.show_edge_x_tick_labels) and (idx == 0 or idx == len(x_tick_labels) - 1):
                    continue
                px, _ = map_to_pixels(np.asarray([xv], dtype=np.float64), np.asarray([ymin], dtype=np.float64), transform, plot_w, plot_h)
                pxi = plot_x0 + int(px[0])
                draw_vline(
                    text_layer,
                    pxi,
                    plot_y0 + plot_h - 1,
                    plot_y0 + plot_h + x_tick_mark_len,
                    self.axis_color,
                )
                if x_tick_layout.stride > 1 and (idx % x_tick_layout.stride) != 0:
                    continue
                tx, _ = text_size(
                    label,
                    font_size_px=x_tick_font_px,
                    rotate_deg=x_tick_layout.rotate_deg,
                    italic=x_tick_layout.italic,
                )
                label_x = pxi - tx if x_tick_layout.rotate_deg != 0 else pxi - tx // 2
                draw_text(
                    text_layer,
                    label_x,
                    int(round(plot_y0 + plot_h + x_tick_mark_len + x_tick_pad)),
                    label,
                    self.text_color,
                    font_size_px=x_tick_font_px,
                    embolden_px=1,
                    rotate_deg=x_tick_layout.rotate_deg,
                    italic=x_tick_layout.italic,
                )

            for idx, (yv, label) in enumerate(zip(tick_y.tolist(), y_tick_labels, strict=False)):
                if (not self.show_edge_y_tick_labels) and (idx == 0 or idx == len(y_tick_labels) - 1):
                    continue
                _, py = map_to_pixels(np.asarray([xmin], dtype=np.float64), np.asarray([yv], dtype=np.float64), transform, plot_w, plot_h)
                tx, _ = text_size(label, font_size_px=tick_font_px)
                draw_text(
                    text_layer,
                    max(0, int(round(plot_x0 - tx - y_tick_pad))),
                    int(round(plot_y0 + int(py[0]) - tick_half_h)),
                    label,
                    self.text_color,
                    font_size_px=tick_font_px,
                    embolden_px=2,
                )

            draw_text(
                text_layer,
                max(0, plot_x0 + (plot_w // 2) - (x_label_w // 2)),
                max(2, int(round(plot_y0 + plot_h + x_tick_mark_len + x_tick_pad + max_x_tick_h + x_label_gap))),
                self.x_label_bottom,
                self.text_color,
                font_size_px=label_font_px,
                embolden_px=2,
            )
            draw_text(
                text_layer,
                max(2, int(round(plot_x0 - max_y_tick_w - y_tick_pad - y_label_w - y_label_gap - y_axis_label_pad))),
                max(2, int(round(plot_y0 + (plot_h // 2) - (y_label_h * 0.5)))),
                self.y_label_left,
                self.text_color,
                font_size_px=label_font_px,
                embolden_px=2,
                rotate_deg=90,
            )
            if self.show_top_axis and self.x_label_top:
                top_w, _ = text_size(self.x_label_top, font_size_px=label_font_px)
                draw_text(
                    text_layer,
                    max(0, plot_x0 + (plot_w // 2) - (top_w // 2)),
                    2,
                    self.x_label_top,
                    self.text_color,
                    font_size_px=label_font_px,
                    embolden_px=2,
                )
            if self.show_right_axis and self.y_label_right:
                tw, _ = text_size(self.y_label_right, font_size_px=label_font_px)
                draw_text(
                    text_layer,
                    max(0, self.figure.width - tw - 2),
                    max(2, plot_y0 + (plot_h // 2)),
                    self.y_label_right,
                    self.text_color,
                    font_size_px=label_font_px,
                    embolden_px=2,
                )

            self._cache.text_key = text_key
            self._cache.text_template = text_layer

        blit(base, self._cache.text_template)
        blit(base_no_data, self._cache.text_template)
        self._last_static_rgba = base_no_data
        self._draw_legend(base)
        return base


@dataclass
class Figure:
    width: int = 1280
    height: int = 720
    style: FigureStyle = field(default_factory=FigureStyle)
    _axes: Axes | None = None
    _subplot_grid: tuple[int, int] | None = None
    _subplot_children: list["Figure"] = field(default_factory=list)
    _subplot_gap_px: tuple[int, int] = (8, 8)
    _subplot_margin_px: tuple[int, int, int, int] = (2, 2, 2, 2)
    _subplot_auto_sized: bool = False
    _last_frame_rgba: np.ndarray | None = None

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width and height must be > 0")

    def axes(
        self,
        *,
        title: str = "",
        x_label_bottom: str = "index",
        y_label_left: str = "value",
        x_label_top: str | None = None,
        y_label_right: str | None = None,
        show_top_axis: bool = False,
        show_right_axis: bool = False,
    ) -> Axes:
        if self._subplot_grid is not None:
            raise PlotDataError("figure already configured for subplot layout")
        if self._axes is not None:
            raise PlotDataError("v0 supports a single subplot per figure")
        self._axes = Axes(
            figure=self,
            title=title,
            x_label_bottom=x_label_bottom,
            y_label_left=y_label_left,
            x_label_top=x_label_top,
            y_label_right=y_label_right,
            show_top_axis=show_top_axis,
            show_right_axis=show_right_axis,
        )
        return self._axes

    def subplots(
        self,
        rows: int,
        cols: int,
        *,
        title: str = "",
        titles: Sequence[str] | None = None,
        x_label_bottom: str = "index",
        y_label_left: str = "value",
    ) -> list[Axes]:
        if rows <= 0 or cols <= 0:
            raise ValueError("rows and cols must be > 0")
        if rows * cols < 2:
            raise ValueError("subplot layout must include at least 2 panels")
        if self._axes is not None or self._subplot_grid is not None:
            raise PlotDataError("figure axes already initialized")
        title_items: tuple[str, ...] = tuple(titles) if titles is not None else ()
        self._subplot_grid = (int(rows), int(cols))
        self._subplot_children = []
        self._subplot_auto_sized = False
        axes_out: list[Axes] = []
        for idx in range(rows * cols):
            child = Figure(width=max(2, self.width), height=max(2, self.height), style=self.style)
            child_title = title_items[idx] if idx < len(title_items) else title
            ax = child.axes(
                title=child_title,
                x_label_bottom=x_label_bottom,
                y_label_left=y_label_left,
            )
            self._subplot_children.append(child)
            axes_out.append(ax)
        return axes_out

    def _subplot_layout(self) -> list[tuple[int, int, int, int, "Figure"]]:
        if self._subplot_grid is None:
            return []
        rows, cols = self._subplot_grid
        gap_x, gap_y = self._subplot_gap_px
        margin_left, margin_right, margin_top, margin_bottom = self._subplot_margin_px
        inner_w = self.width - margin_left - margin_right - gap_x * (cols - 1)
        inner_h = self.height - margin_top - margin_bottom - gap_y * (rows - 1)
        if inner_w < cols * 2 or inner_h < rows * 2:
            raise PlotDataError("figure too small for subplot layout")
        base_w = inner_w // cols
        extra_w = inner_w % cols
        base_h = inner_h // rows
        extra_h = inner_h % rows
        col_widths = [base_w + (1 if c < extra_w else 0) for c in range(cols)]
        row_heights = [base_h + (1 if r < extra_h else 0) for r in range(rows)]
        if len(self._subplot_children) != rows * cols:
            raise PlotDataError("subplot configuration is inconsistent")
        layout: list[tuple[int, int, int, int, Figure]] = []
        idx = 0
        y = margin_top
        for r in range(rows):
            h = row_heights[r]
            x = margin_left
            for c in range(cols):
                w = col_widths[c]
                layout.append((x, y, w, h, self._subplot_children[idx]))
                idx += 1
                x += w + gap_x
            y += h + gap_y
        return layout

    def _apply_subplot_preferred_aspects(self) -> None:
        if self._subplot_grid is None or not self._subplot_children:
            return
        if self._subplot_auto_sized:
            return
        rows, cols = self._subplot_grid
        gap_x, gap_y = self._subplot_gap_px
        margin_left, margin_right, margin_top, margin_bottom = self._subplot_margin_px
        for _ in range(2):
            inner_w = self.width - margin_left - margin_right - gap_x * (cols - 1)
            inner_h = self.height - margin_top - margin_bottom - gap_y * (rows - 1)
            if inner_w <= 0 or inner_h <= 0:
                return
            panel_w = float(inner_w) / float(cols)
            panel_h = float(inner_h) / float(rows)
            required_panel_w = panel_w
            required_panel_h = panel_h
            for child in self._subplot_children:
                ax = child._axes
                aspect: float | None = None
                if ax is not None and ax.preferred_panel_aspect_ratio is not None:
                    aspect = max(1e-9, float(ax.preferred_panel_aspect_ratio))
                elif ax is not None:
                    has_line_or_scatter = any(spec.style.mode in {"lines", "lines+markers", "markers"} for spec in ax._series)
                    if has_line_or_scatter:
                        aspect = 4.0 / 3.0
                if aspect is None:
                    continue
                required_panel_w = max(required_panel_w, panel_h * aspect)
                required_panel_h = max(required_panel_h, panel_w / aspect)
            target_inner_w = int(np.ceil(max(float(inner_w), required_panel_w * cols)))
            target_inner_h = int(np.ceil(max(float(inner_h), required_panel_h * rows)))
            target_w = target_inner_w + margin_left + margin_right + gap_x * (cols - 1)
            target_h = target_inner_h + margin_top + margin_bottom + gap_y * (rows - 1)
            grew = False
            if target_w > self.width:
                self.width = target_w
                grew = True
            if target_h > self.height:
                self.height = target_h
                grew = True
            if not grew:
                break
        self._subplot_auto_sized = True

    def to_rgba(self) -> np.ndarray:
        if self._subplot_grid is not None:
            self._apply_subplot_preferred_aspects()
            frame = new_canvas(self.width, self.height, color=self.style.background)
            for x, y, w, h, child in self._subplot_layout():
                child.width = max(2, int(w))
                child.height = max(2, int(h))
                panel = child.to_rgba()
                patch = frame[y : y + h, x : x + w]
                alpha = panel[:, :, 3:4].astype(np.float32) / 255.0
                inv = 1.0 - alpha
                patch[:, :, :3] = (panel[:, :, :3] * alpha + patch[:, :, :3] * inv).astype(np.uint8)
                patch[:, :, 3] = 255
            self._last_frame_rgba = frame.copy()
            return frame
        if self._axes is None:
            raise PlotDataError("figure has no axes")
        frame = self._axes.render()
        self._last_frame_rgba = frame.copy()
        return frame

    def compile_write_batch(self):
        return compile_full_rewrite_batch(self.to_rgba())

    def compile_incremental_write_batch(self, dirty_rect: tuple[int, int, int, int] | None = None):
        if self._subplot_grid is not None:
            return compile_full_rewrite_batch(self.to_rgba())
        if dirty_rect is None:
            return compile_full_rewrite_batch(self.to_rgba())
        if self._axes is not None:
            patch_info = self._axes.render_legend_patch(dirty_rect)
            if patch_info is not None:
                x0, y0, patch = patch_info
                self._last_frame_rgba = None
                return compile_replace_patch_batch(patch, x=x0, y=y0)
        frame = self.to_rgba()
        x, y, width, height = dirty_rect
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(frame.shape[1], x0 + int(width))
        y1 = min(frame.shape[0], y0 + int(height))
        if x1 <= x0 or y1 <= y0:
            return compile_full_rewrite_batch(frame)
        return compile_replace_rect_batch(frame, x=x0, y=y0, width=(x1 - x0), height=(y1 - y0))
