from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from luvatrix_plot.adapters import normalize_xy
from luvatrix_plot.compile import compile_full_rewrite_batch
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


@dataclass(frozen=True)
class FigureStyle:
    background: tuple[int, int, int, int] = (12, 16, 23, 255)


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
    axis_color: tuple[int, int, int, int] = (124, 138, 156, 255)
    text_color: tuple[int, int, int, int] = (208, 218, 232, 255)

    def scatter(
        self,
        y: Any = None,
        *,
        x: Any = None,
        data: Any = None,
        color: tuple[int, int, int] | tuple[int, int, int, int] = (62, 149, 255),
        size: int = 2,
        alpha: float = 1.0,
    ) -> "Axes":
        style = SeriesStyle(mode="markers", color=_coerce_color(color, alpha), marker_size=max(1, size), line_width=1)
        series_data = normalize_xy(y=y, x=x, data=data)
        self._series.append(SeriesSpec(data=series_data, style=style))
        return self

    def plot(
        self,
        y: Any = None,
        *,
        x: Any = None,
        data: Any = None,
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
        self._series.append(SeriesSpec(data=series_data, style=style))
        return self

    def series(
        self,
        y: Any = None,
        *,
        x: Any = None,
        data: Any = None,
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
        self._series.append(SeriesSpec(data=series_data, style=style))
        return self

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
            limits = compute_limits(spec.data.x, spec.data.y, spec.data.mask)
            mins_x.append(limits.xmin)
            maxs_x.append(limits.xmax)
            mins_y.append(limits.ymin)
            maxs_y.append(limits.ymax)

        return min(mins_x), max(maxs_x), min(mins_y), max(maxs_y)

    def render(self) -> np.ndarray:
        if not self._series:
            raise PlotDataError("cannot render empty axes")

        base = new_canvas(self.figure.width, self.figure.height, color=self.figure.style.background)
        scale_base = min(self.figure.width, self.figure.height)
        tick_font_px = max(12.0, min(28.0, scale_base * 0.03))
        label_font_px = max(11.0, min(24.0, scale_base * 0.032))
        title_font_px = max(12.0, min(30.0, scale_base * 0.038))
        tick_half_h = int(round(tick_font_px * 0.5))
        xmin, xmax, ymin, ymax = self._combined_limits()
        y_all = np.concatenate([spec.data.y[spec.data.mask] for spec in self._series]).astype(np.float64, copy=False)
        y_resolution = infer_resolution(y_all)
        preferred_y_step = preferred_major_step_from_resolution(y_resolution)

        # First pass tick estimates for layout sizing.
        provisional_w = max(120, self.figure.width - 80)
        provisional_h = max(80, self.figure.height - 80)
        tick_x_probe = generate_nice_ticks(xmin, xmax, max(5, provisional_w // 120))
        tick_y_probe = generate_nice_ticks(ymin, ymax, max(4, provisional_h // 140), preferred_step=preferred_y_step)
        x_tick_labels_probe = format_ticks_for_axis(tick_x_probe)
        y_tick_labels_probe = format_ticks_for_axis(tick_y_probe)
        max_x_tick_h = max((text_size(lbl, font_size_px=tick_font_px)[1] for lbl in x_tick_labels_probe), default=int(tick_font_px))
        max_x_tick_w = max((text_size(lbl, font_size_px=tick_font_px)[0] for lbl in x_tick_labels_probe), default=0)
        max_y_tick_w = max((text_size(lbl, font_size_px=tick_font_px)[0] for lbl in y_tick_labels_probe), default=0)
        x_label_w, x_label_h = text_size(self.x_label_bottom, font_size_px=label_font_px)
        y_label_w, y_label_h = text_size(self.y_label_left, font_size_px=label_font_px, rotate_deg=270)
        title_h = text_size(self.title, font_size_px=title_font_px)[1] if self.title else 0

        y_tick_pad = int(max(4.0, tick_font_px * 0.4))
        y_label_gap = int(max(8.0, label_font_px * 0.45))
        left = int(max(18, max_y_tick_w + y_tick_pad + y_label_w + y_label_gap + 10))
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
        bottom = int(max(12, max_x_tick_h + x_label_h + 14))

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
        tick_x = generate_nice_ticks(xmin, xmax, max(5, plot_w // 120))
        tick_y = generate_nice_ticks(ymin, ymax, max(4, plot_h // 140), preferred_step=preferred_y_step)
        x_tick_labels = format_ticks_for_axis(tick_x)
        y_tick_labels = format_ticks_for_axis(tick_y)
        grid_key = (
            plot_w,
            plot_h,
            round(xmin, 12),
            round(xmax, 12),
            round(ymin, 12),
            round(ymax, 12),
            self.grid_color,
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
            # Minor dot grid at tenth subdivisions of major steps.
            major_x_step = float(abs(tick_x[1] - tick_x[0])) if tick_x.size > 1 else 1.0
            major_y_step = float(abs(tick_y[1] - tick_y[0])) if tick_y.size > 1 else 1.0
            minor_x_step = major_x_step / 10.0
            minor_y_step = major_y_step / 10.0
            if minor_x_step > 0 and minor_y_step > 0:
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
                # Guardrail for very large grids.
                if x_minor.size * y_minor.size <= 20000:
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
                    for px in x_minor_px.tolist():
                        gx = plot_x0 + int(px)
                        for py in y_minor_px.tolist():
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
        # Pass 1: lines under markers for clear point visibility.
        for spec in self._series:
            visible_mask = spec.data.mask
            xvals = spec.data.x[visible_mask]
            yvals = spec.data.y[visible_mask]
            px, py = map_to_pixels(xvals, yvals, transform, plot_w, plot_h)
            if px.size > plot_w:
                mode = "markers" if spec.style.mode == "markers" else "lines"
                px, py = downsample_by_pixel_column(px, py, width=plot_w, mode=mode)

            px = px + plot_x0
            py = py + plot_y0
            if spec.style.mode in {"lines", "lines+markers"}:
                draw_polyline(drawing, px, py, color=spec.style.color, width=spec.style.line_width)
        # Pass 2: markers on top.
        for spec in self._series:
            if spec.style.mode not in {"markers", "lines+markers"}:
                continue
            visible_mask = spec.data.mask
            xvals = spec.data.x[visible_mask]
            yvals = spec.data.y[visible_mask]
            px, py = map_to_pixels(xvals, yvals, transform, plot_w, plot_h)
            if px.size > plot_w:
                px, py = downsample_by_pixel_column(px, py, width=plot_w, mode="markers")
            px = px + plot_x0
            py = py + plot_y0
            marker_size = max(2, spec.style.marker_size)
            draw_markers(drawing, px, py, color=spec.style.color, size=marker_size)

        blit(base, drawing)

        draw_hline(base, plot_x0, plot_x0 + plot_w - 1, plot_y0 + plot_h - 1, self.axis_color)
        draw_vline(base, plot_x0, plot_y0, plot_y0 + plot_h - 1, self.axis_color)
        if self.show_top_axis:
            draw_hline(base, plot_x0, plot_x0 + plot_w - 1, plot_y0, self.axis_color)
        if self.show_right_axis:
            draw_vline(base, plot_x0 + plot_w - 1, plot_y0, plot_y0 + plot_h - 1, self.axis_color)

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

            for xv, label in zip(tick_x.tolist(), x_tick_labels, strict=False):
                px, _ = map_to_pixels(np.asarray([xv], dtype=np.float64), np.asarray([ymin], dtype=np.float64), transform, plot_w, plot_h)
                tx, _ = text_size(label, font_size_px=tick_font_px)
                draw_text(
                    text_layer,
                    plot_x0 + int(px[0]) - tx // 2,
                    int(round(plot_y0 + plot_h + max(4.0, tick_font_px * 0.5))),
                    label,
                    self.text_color,
                    font_size_px=tick_font_px,
                    embolden_px=2,
                )

            for yv, label in zip(tick_y.tolist(), y_tick_labels, strict=False):
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
                max(2, int(round(self.figure.height - x_label_h - 2))),
                self.x_label_bottom,
                self.text_color,
                font_size_px=label_font_px,
                embolden_px=2,
            )
            draw_text(
                text_layer,
                max(2, int(round(plot_x0 - max_y_tick_w - y_tick_pad - y_label_w - y_label_gap))),
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
        return base


@dataclass
class Figure:
    width: int = 1280
    height: int = 720
    style: FigureStyle = field(default_factory=FigureStyle)
    _axes: Axes | None = None

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

    def to_rgba(self) -> np.ndarray:
        if self._axes is None:
            raise PlotDataError("figure has no axes")
        return self._axes.render()

    def compile_write_batch(self):
        return compile_full_rewrite_batch(self.to_rgba())
