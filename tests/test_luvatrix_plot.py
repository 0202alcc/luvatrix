from __future__ import annotations

from decimal import Decimal
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

import numpy as np
import torch

from luvatrix_core.core.window_matrix import FullRewrite, ReplaceRect, WriteBatch
from luvatrix_plot import PlotDataError, figure
from luvatrix_plot.adapters.normalize import normalize_xy
from luvatrix_plot.display import resolve_default_figure_size
from luvatrix_plot.figure import Axes, Figure
from luvatrix_plot.dynamic_axis import Dynamic2DMonotonicAxis, DynamicSampleAxis
from luvatrix_plot.live import Dynamic2DStreamBuffer, IncrementalPlotState, SampleToXMapper
from luvatrix_plot.raster.canvas import new_canvas
from luvatrix_plot.raster.draw_text import DEFAULT_FONT_FAMILY
from luvatrix_plot.raster.draw_text import draw_text as raster_draw_text
from luvatrix_plot.raster.draw_text import text_size as raster_text_size
from luvatrix_plot.scales import (
    DataLimits,
    build_transform,
    downsample_by_pixel_column,
    format_ticks_for_axis,
    generate_nice_ticks,
    infer_resolution,
    map_to_pixels,
    preferred_major_step_from_resolution,
)


class LuvatrixPlotTests(unittest.TestCase):
    def test_default_plot_font_family_is_comic_mono(self) -> None:
        self.assertEqual(DEFAULT_FONT_FAMILY, "Comic Mono")

    def test_default_figure_size_scales_with_display(self) -> None:
        with mock.patch("luvatrix_plot.display._detect_screen_size", return_value=(2560, 1600)):
            w, h = resolve_default_figure_size()
        self.assertGreaterEqual(w, 960)
        self.assertGreaterEqual(h, 540)
        self.assertAlmostEqual(w / h, 16.0 / 9.0, places=1)

    def test_figure_derives_missing_dimension_from_aspect_ratio(self) -> None:
        fig = figure(width=1000, height=None)
        self.assertEqual(fig.height, 562)

    def test_text_renderer_uses_antialias_coverage(self) -> None:
        canvas = new_canvas(220, 80, color=(0, 0, 0, 0))
        raster_draw_text(canvas, 10, 20, "Static 1-D Plot", (255, 255, 255, 255), font_size_px=24.0)
        chan = canvas[:, :, 0]
        self.assertTrue(np.any((chan > 0) & (chan < 255)))
        # Transparent background should remain transparent outside rendered glyph coverage.
        self.assertEqual(int(canvas[0, 0, 3]), 0)

    def test_rotated_text_size_swaps_dimensions(self) -> None:
        w0, h0 = raster_text_size("value", font_size_px=18.0, rotate_deg=0)
        w1, h1 = raster_text_size("value", font_size_px=18.0, rotate_deg=270)
        self.assertEqual((w1, h1), (h0, w0))

    def test_tick_formatting_uses_consistent_decimals_from_step(self) -> None:
        ticks = np.asarray([1.5, 2.0, 2.5, 3.0], dtype=np.float64)
        labels = format_ticks_for_axis(ticks)
        self.assertEqual(labels, ["1.5", "2", "2.5", "3"])

    def test_tick_formatting_preserves_integer_trailing_zeros(self) -> None:
        ticks = np.asarray([20.0, 30.0, 40.0], dtype=np.float64)
        labels = format_ticks_for_axis(ticks)
        self.assertEqual(labels, ["20", "30", "40"])

    def test_tick_formatting_snaps_near_zero(self) -> None:
        ticks = np.asarray([-1.0, -4.4409e-16, 1.0], dtype=np.float64)
        labels = format_ticks_for_axis(ticks)
        self.assertEqual(labels[1], "0")

    def test_resolution_inference_prefers_half_step_for_tenth_data(self) -> None:
        values = np.asarray([2.0, 2.4, 2.1, 3.0, 2.8, 3.2, 3.6, 3.1, 3.9, 4.3], dtype=np.float64)
        resolution = infer_resolution(values)
        self.assertAlmostEqual(resolution or 0.0, 0.1, places=9)
        preferred = preferred_major_step_from_resolution(resolution)
        self.assertAlmostEqual(preferred or 0.0, 0.5, places=9)
        ticks = generate_nice_ticks(1.795, 6.305, 5, preferred_step=preferred)
        self.assertTrue(np.isclose(abs(ticks[1] - ticks[0]), 0.5))

    def test_limit_hysteresis_expands_immediately_and_shrinks_gradually(self) -> None:
        ax = Axes(figure=Figure(width=320, height=200))
        ax.set_limit_hysteresis(enabled=True, deadband_ratio=0.1, shrink_rate=0.2)

        first = ax._apply_limit_hysteresis(DataLimits(xmin=0.0, xmax=10.0, ymin=0.0, ymax=10.0))
        self.assertEqual(first.ymax, 10.0)

        expanded = ax._apply_limit_hysteresis(DataLimits(xmin=0.0, xmax=10.0, ymin=-2.0, ymax=12.0))
        self.assertEqual(expanded.ymin, -2.0)
        self.assertEqual(expanded.ymax, 12.0)

        shrunk = ax._apply_limit_hysteresis(DataLimits(xmin=0.0, xmax=10.0, ymin=1.0, ymax=9.0))
        self.assertGreater(shrunk.ymax, 9.0)
        self.assertLess(shrunk.ymax, 12.0)

    def test_axes_accepts_major_tick_step_override(self) -> None:
        ax = Axes(figure=Figure(width=320, height=200))
        ax.set_major_tick_steps(y=0.2)
        self.assertAlmostEqual(ax.y_major_tick_step or 0.0, 0.2, places=9)

    def test_axes_dynamic_defaults(self) -> None:
        ax = Axes(figure=Figure(width=320, height=200))
        ax.set_dynamic_defaults()
        self.assertFalse(ax.show_edge_x_tick_labels)
        self.assertFalse(ax.show_edge_y_tick_labels)
        self.assertTrue(ax.include_zero_x_tick)

    def test_x_tick_label_affine_affects_labels_only(self) -> None:
        ax = Axes(figure=Figure(width=320, height=200))
        ax.set_x_tick_label_affine(scale=0.5, offset=0.0)
        labels = ax._format_x_tick_labels(np.asarray([0.0, 20.0, 40.0], dtype=np.float64))
        self.assertEqual(labels, ["0", "10", "20"])

    def test_dense_long_x_labels_compact_fallback_is_deterministic(self) -> None:
        x = np.arange(24, dtype=np.float64)
        y = np.sin(x / 3.0)
        labels = [f"rule-{i:02d}-very-long-label" for i in range(24)]

        fig_small = figure(width=640, height=360)
        ax_small = fig_small.axes(x_label_bottom="rule", y_label_left="value")
        ax_small.set_major_tick_steps(x=1.0)
        ax_small.set_x_tick_labels(labels)
        ax_small.plot(x=x, y=y, color=(255, 170, 70), width=1)
        frame_small_1 = fig_small.to_rgba()
        frame_small_2 = fig_small.to_rgba()

        self.assertTrue(np.array_equal(frame_small_1, frame_small_2))
        rotate_small, stride_small = ax_small.last_x_tick_label_layout()
        self.assertGreater(rotate_small, 0)
        self.assertLess(rotate_small, 90)
        self.assertGreaterEqual(stride_small, 1)

        fig_large = figure(width=1280, height=720)
        ax_large = fig_large.axes(x_label_bottom="rule", y_label_left="value")
        ax_large.set_major_tick_steps(x=1.0)
        ax_large.set_x_tick_labels(labels)
        ax_large.plot(x=x, y=y, color=(255, 170, 70), width=1)
        fig_large.to_rgba()
        rotate_large, stride_large = ax_large.last_x_tick_label_layout()
        self.assertEqual(rotate_large, rotate_small)
        self.assertLessEqual(stride_large, stride_small)

    def test_zero_reference_lines_enabled_by_default(self) -> None:
        x = np.asarray([-1.0, 0.0, 1.0], dtype=np.float64)
        y = np.asarray([-1.0, 0.0, 1.0], dtype=np.float64)

        fig_on = figure(width=220, height=160)
        ax_on = fig_on.axes(x_label_bottom="x", y_label_left="y")
        ax_on.plot(x=x, y=y)
        frame_on = fig_on.to_rgba()

        fig_off = figure(width=220, height=160)
        ax_off = fig_off.axes(x_label_bottom="x", y_label_left="y")
        ax_off.show_zero_reference_lines = False
        ax_off.plot(x=x, y=y)
        frame_off = fig_off.to_rgba()

        self.assertFalse(np.array_equal(frame_on, frame_off))

    def test_normalize_decimal_and_mask(self) -> None:
        data = [Decimal("1.5"), Decimal("2.25"), None, Decimal("3.5")]
        series = normalize_xy(y=data)
        self.assertEqual(series.x.tolist(), [0.0, 1.0, 2.0, 3.0])
        self.assertTrue(np.array_equal(series.mask, np.asarray([True, True, False, True])))

    def test_normalize_torch_tensor(self) -> None:
        y = torch.tensor([1, 2, 3], dtype=torch.int64)
        series = normalize_xy(y=y)
        self.assertEqual(series.y.dtype, np.float64)
        self.assertEqual(series.y.tolist(), [1.0, 2.0, 3.0])

    def test_normalize_pandas_dataframe_single_numeric_column(self) -> None:
        try:
            import pandas as pd
        except Exception:
            self.skipTest("pandas is not installed")

        df = pd.DataFrame({"value": [1, 2, 3]})
        series = normalize_xy(y=df)
        self.assertEqual(series.y.tolist(), [1.0, 2.0, 3.0])

    def test_map_to_pixels_and_downsample(self) -> None:
        x = np.arange(200, dtype=np.float64)
        y = np.sin(x / 10.0)
        transform = build_transform(DataLimits(0.0, 199.0, -1.0, 1.0), width=50, height=20)
        px, py = map_to_pixels(x, y, transform, width=50, height=20)
        dsx, dsy = downsample_by_pixel_column(px, py, width=50, mode="markers")
        self.assertLessEqual(dsx.size, 50)
        self.assertEqual(dsx.size, dsy.size)

    def test_render_scatter_and_line_deterministic(self) -> None:
        y = np.asarray([1, 4, 2, 6, 3, 7, 5], dtype=np.float64)
        fig = figure(width=128, height=96)
        ax = fig.axes(title="demo", x_label_bottom="idx", y_label_left="val")
        ax.scatter(y=y, color=(10, 200, 120), size=1)
        ax.plot(y=y, color=(240, 120, 10), width=1)

        frame1 = fig.to_rgba()
        frame2 = fig.to_rgba()

        self.assertEqual(frame1.shape, (96, 128, 4))
        self.assertEqual(frame1.dtype, np.uint8)
        self.assertTrue(np.array_equal(frame1, frame2))

    def test_bar_plot_supports_positive_and_negative_values_deterministically(self) -> None:
        x = np.asarray([0.0, 1.0, 2.0, 3.0], dtype=np.float64)
        y = np.asarray([2.0, -1.5, 3.5, -2.2], dtype=np.float64)
        fig = figure(width=240, height=160)
        ax = fig.axes(title="bars", x_label_bottom="x", y_label_left="value")
        ax.bar(x=x, y=y, color=(90, 180, 255), width=0.7)
        frame_1 = fig.to_rgba()
        frame_2 = fig.to_rgba()
        self.assertTrue(np.array_equal(frame_1, frame_2))

        limits = ax.last_limits()
        plot_rect = ax.last_plot_rect()
        self.assertIsNotNone(limits)
        self.assertIsNotNone(plot_rect)
        assert limits is not None
        assert plot_rect is not None
        self.assertLess(limits.ymin, 0.0)
        self.assertGreater(limits.ymax, 0.0)
        tick_x, _ = ax.last_tick_values()
        for xv in x.tolist():
            self.assertTrue(any(abs(tv - float(xv)) <= 1e-9 for tv in tick_x))

        plot_x0, plot_y0, plot_w, plot_h = plot_rect
        transform = build_transform(limits, width=plot_w, height=plot_h)
        _, py_zero = map_to_pixels(
            np.asarray([0.0], dtype=np.float64),
            np.asarray([0.0], dtype=np.float64),
            transform,
            plot_w,
            plot_h,
        )
        baseline_y = int(plot_y0 + int(py_zero[0]))
        rgb = frame_1[:, :, :3]
        bar_mask = np.all(rgb == np.asarray([90, 180, 255], dtype=np.uint8).reshape(1, 1, 3), axis=2)
        self.assertTrue(np.any(bar_mask[:baseline_y, :]))
        self.assertTrue(np.any(bar_mask[baseline_y + 1 :, :]))
        self.assertFalse(np.any(bar_mask[plot_y0 : plot_y0 + plot_h, plot_x0]))
        self.assertFalse(np.any(bar_mask[plot_y0 : plot_y0 + plot_h, plot_x0 + plot_w - 1]))

    def test_bar_rejects_nonpositive_width(self) -> None:
        fig = figure(width=160, height=100)
        ax = fig.axes()
        with self.assertRaises(ValueError):
            ax.bar(y=[1.0, 2.0], width=0.0)

    def test_figure_supports_two_subplots_in_single_frame(self) -> None:
        fig = figure(width=320, height=200)
        left_ax, right_ax = fig.subplots(1, 2, titles=("left", "right"), x_label_bottom="x", y_label_left="y")
        x = np.asarray([0.0, 1.0, 2.0, 3.0], dtype=np.float64)
        left_ax.plot(x=x, y=np.asarray([0.0, 1.0, 0.5, 1.5], dtype=np.float64), color=(255, 170, 70), width=1)
        right_ax.bar(x=x, y=np.asarray([1.0, -0.5, 1.3, -1.0], dtype=np.float64), color=(90, 190, 255), width=0.7)

        frame_1 = fig.to_rgba()
        frame_2 = fig.to_rgba()
        self.assertGreaterEqual(frame_1.shape[0], 200)
        self.assertGreaterEqual(frame_1.shape[1], 320)
        self.assertEqual(frame_1.shape[2], 4)
        self.assertTrue(np.array_equal(frame_1, frame_2))
        mid = frame_1.shape[1] // 2
        self.assertGreater(float(frame_1[:, :mid, :3].std()), 0.0)
        self.assertGreater(float(frame_1[:, mid:, :3].std()), 0.0)

    def test_subplots_update_one_panel_without_requiring_other_panel_change(self) -> None:
        fig = figure(width=360, height=220)
        left_ax, right_ax = fig.subplots(1, 2, x_label_bottom="x", y_label_left="y")
        x = np.asarray([0.0, 1.0, 2.0, 3.0], dtype=np.float64)
        left_ax.plot(x=x, y=np.asarray([0.0, 1.0, 0.0, 1.0], dtype=np.float64), color=(255, 170, 70), width=1)
        right_ax.plot(x=x, y=np.asarray([1.0, 1.0, 1.0, 1.0], dtype=np.float64), color=(90, 190, 255), width=1)
        frame_before = fig.to_rgba()

        right_ax.plot(x=x, y=np.asarray([0.0, -1.0, 0.5, -0.5], dtype=np.float64), color=(180, 255, 90), width=1)
        frame_after = fig.to_rgba()
        diff = np.abs(frame_after.astype(np.int16) - frame_before.astype(np.int16)).sum(axis=2)
        left_diff = int(diff[:, :180].sum())
        right_diff = int(diff[:, 180:].sum())
        self.assertGreater(right_diff, left_diff)

    def test_subplots_and_single_axes_are_mutually_exclusive(self) -> None:
        fig = figure(width=240, height=160)
        fig.subplots(1, 2)
        with self.assertRaises(PlotDataError):
            fig.axes()

    def test_subplots_expand_for_preferred_panel_aspect_ratio(self) -> None:
        fig = figure(width=320, height=200)
        left_ax, right_ax = fig.subplots(1, 2, x_label_bottom="x", y_label_left="y")
        left_ax.set_preferred_panel_aspect_ratio(1.0)
        right_ax.set_preferred_panel_aspect_ratio(1.8)
        x = np.asarray([0.0, 1.0, 2.0, 3.0], dtype=np.float64)
        left_ax.plot(x=x, y=np.asarray([1.0, 2.0, 1.5, 2.0], dtype=np.float64), color=(255, 170, 70), width=1)
        right_ax.plot(x=x, y=np.asarray([0.0, 1.0, 0.0, 1.0], dtype=np.float64), color=(90, 190, 255), width=1)
        before_w = fig.width
        _ = fig.to_rgba()
        self.assertGreaterEqual(fig.width, before_w)

    def test_line_subplot_defaults_to_four_by_three_preferred_aspect(self) -> None:
        fig = figure(width=320, height=220)
        ax_left, ax_right = fig.subplots(1, 2, x_label_bottom="x", y_label_left="y")
        x = np.asarray([0.0, 1.0, 2.0, 3.0], dtype=np.float64)
        ax_left.plot(x=x, y=np.asarray([0.0, 1.0, 0.0, 1.0], dtype=np.float64), color=(255, 170, 70), width=1)
        ax_right.scatter(x=x, y=np.asarray([1.0, 0.0, 1.0, 0.0], dtype=np.float64), color=(90, 190, 255), size=2)
        before_w = fig.width
        _ = fig.to_rgba()
        self.assertGreater(fig.width, before_w)

    def test_viewport_pan_is_clamped_and_deterministic(self) -> None:
        x = np.arange(100, dtype=np.float64)
        y = np.sin(x * 0.1)
        fig = figure(width=320, height=180)
        ax = fig.axes(x_label_bottom="x", y_label_left="y")
        ax.plot(x=x, y=y, color=(255, 170, 70), width=1)
        ax.set_viewport(xmin=20.0, xmax=40.0)
        fig.to_rgba()
        self.assertEqual(ax.last_resolved_viewport(), (20.0, 40.0))

        ax.pan_viewport(200.0)
        frame_1 = fig.to_rgba()
        frame_2 = fig.to_rgba()
        self.assertTrue(np.array_equal(frame_1, frame_2))
        viewport = ax.last_resolved_viewport()
        self.assertIsNotNone(viewport)
        assert viewport is not None
        self.assertAlmostEqual(viewport[0], 79.0, places=9)
        self.assertAlmostEqual(viewport[1], 99.0, places=9)

    def test_viewport_pan_keeps_data_aligned_with_transform(self) -> None:
        x = np.arange(10, dtype=np.float64)
        y = np.full(10, 2.0, dtype=np.float64)
        fig = figure(width=280, height=180)
        ax = fig.axes(x_label_bottom="x", y_label_left="y")
        ax.scatter(x=x, y=y, color=(250, 70, 70), size=3)
        ax.set_viewport(xmin=2.0, xmax=6.0)
        frame_a = fig.to_rgba()

        plot_rect = ax.last_plot_rect()
        limits_a = ax.last_limits()
        self.assertIsNotNone(plot_rect)
        self.assertIsNotNone(limits_a)
        assert plot_rect is not None
        assert limits_a is not None
        x0, y0, w, h = plot_rect
        transform_a = build_transform(limits_a, width=w, height=h)
        px_a, py_a = map_to_pixels(
            np.asarray([5.0], dtype=np.float64),
            np.asarray([2.0], dtype=np.float64),
            transform_a,
            w,
            h,
        )
        self.assertTrue(np.array_equal(frame_a[y0 + int(py_a[0]), x0 + int(px_a[0]), :3], np.asarray([250, 70, 70], dtype=np.uint8)))

        ax.pan_viewport(2.0)
        frame_b = fig.to_rgba()
        limits_b = ax.last_limits()
        self.assertIsNotNone(limits_b)
        assert limits_b is not None
        transform_b = build_transform(limits_b, width=w, height=h)
        px_b, py_b = map_to_pixels(
            np.asarray([5.0], dtype=np.float64),
            np.asarray([2.0], dtype=np.float64),
            transform_b,
            w,
            h,
        )
        self.assertTrue(np.array_equal(frame_b[y0 + int(py_b[0]), x0 + int(px_b[0]), :3], np.asarray([250, 70, 70], dtype=np.uint8)))

    def test_viewport_excludes_out_of_range_points_without_edge_collapse(self) -> None:
        x = np.arange(0.0, 101.0, dtype=np.float64)
        y = np.sin(x * 0.08)
        fig = figure(width=360, height=220)
        ax = fig.axes(x_label_bottom="x", y_label_left="y")
        ax.scatter(x=x, y=y, color=(90, 190, 255), size=2)
        ax.set_viewport(xmin=20.0, xmax=70.0)
        frame = fig.to_rgba()
        plot_rect = ax.last_plot_rect()
        self.assertIsNotNone(plot_rect)
        assert plot_rect is not None
        x0, y0, w, h = plot_rect
        right_col = frame[y0 : y0 + h, x0 + w - 1, :3]
        hits = int(np.count_nonzero(np.all(right_col == np.asarray([90, 190, 255], dtype=np.uint8), axis=1)))
        self.assertLess(hits, 20)

    def test_viewport_tick_values_stay_within_bounds(self) -> None:
        x = np.arange(0.0, 121.0, dtype=np.float64)
        y = np.cos(x * 0.09)
        fig = figure(width=360, height=220)
        ax = fig.axes(x_label_bottom="x", y_label_left="y")
        ax.plot(x=x, y=y, color=(255, 170, 70), width=1)
        ax.set_major_tick_steps(x=10.0, y=0.2)
        ax.set_viewport(xmin=44.0, xmax=94.0)
        fig.to_rgba()
        tick_x, tick_y = ax.last_tick_values()
        self.assertTrue(all(44.0 <= value <= 94.0 for value in tick_x))
        limits = ax.last_limits()
        self.assertIsNotNone(limits)
        assert limits is not None
        self.assertTrue(all(limits.ymin <= value <= limits.ymax for value in tick_y))

    def test_line_plot_respects_nan_gaps(self) -> None:
        y = np.asarray([0.0, 0.5, np.nan, np.nan, 0.0, 0.5], dtype=np.float64)
        fig = figure(width=160, height=100)
        ax = fig.axes(title="", x_label_bottom="x", y_label_left="y")
        ax.plot(y=y, color=(255, 170, 70), width=1)
        frame = fig.to_rgba()
        # Pixel near the center gap should remain background-like (no connecting line bridge).
        mid = frame[50, 80, :3].astype(np.int32)
        self.assertGreater(int(np.abs(mid - np.asarray([255, 170, 70])).sum()), 120)

    def test_render_recomputes_finite_mask_for_dynamic_arrays(self) -> None:
        x = np.asarray([np.nan, np.nan, 0.0], dtype=np.float64)
        y = np.asarray([np.nan, np.nan, 1.0], dtype=np.float64)
        fig = figure(width=180, height=120)
        ax = fig.axes(title="", x_label_bottom="x", y_label_left="y")
        ax.scatter(x=x, y=y, color=(90, 190, 255), size=2)
        fig.to_rgba()

        # Mutate in place to emulate rolling dynamic buffers.
        x[:] = np.asarray([0.0, 1.0, 2.0], dtype=np.float64)
        y[:] = np.asarray([1.0, 2.0, 3.0], dtype=np.float64)
        fig.to_rgba()
        limits = ax.last_limits()
        self.assertIsNotNone(limits)
        assert limits is not None
        # If stale mask were used, x range would collapse around the old slot.
        self.assertAlmostEqual(limits.xmin, 0.0, places=9)
        self.assertAlmostEqual(limits.xmax, 2.0, places=9)

    def test_legend_renders_for_multiple_labeled_lines(self) -> None:
        x = np.asarray([0, 1, 2, 3, 4], dtype=np.float64)
        y1 = np.asarray([1, 2, 1.5, 2.5, 2.0], dtype=np.float64)
        y2 = np.asarray([1, 2, 1.5, 2.5, 2.0], dtype=np.float64)

        fig_no_legend = figure(width=260, height=180)
        ax_no = fig_no_legend.axes()
        ax_no.plot(x=x, y=y1, color=(255, 170, 70))
        ax_no.plot(x=x, y=y2, color=(70, 170, 255))
        frame_no = fig_no_legend.to_rgba()

        fig_legend = figure(width=260, height=180)
        ax_yes = fig_legend.axes()
        ax_yes.plot(x=x, y=y1, color=(255, 170, 70), label="A")
        ax_yes.plot(x=x, y=y2, color=(70, 170, 255), label="B")
        frame_yes = fig_legend.to_rgba()

        self.assertFalse(np.array_equal(frame_no, frame_yes))

    def test_compile_write_batch(self) -> None:
        y = np.asarray([1, 2, 3, 4], dtype=np.float64)
        fig = figure(width=64, height=48)
        fig.axes().scatter(y=y)
        batch = fig.compile_write_batch()

        self.assertIsInstance(batch, WriteBatch)
        self.assertEqual(len(batch.operations), 1)
        self.assertIsInstance(batch.operations[0], FullRewrite)
        op = batch.operations[0]
        self.assertEqual(tuple(op.tensor_h_w_4.shape), (48, 64, 4))
        self.assertEqual(op.tensor_h_w_4.dtype, torch.uint8)

    def test_compile_incremental_write_batch_uses_replace_rect(self) -> None:
        y = np.asarray([1, 2, 3, 4], dtype=np.float64)
        fig = figure(width=96, height=64)
        fig.axes().scatter(y=y)
        batch = fig.compile_incremental_write_batch((10, 8, 20, 12))
        self.assertIsInstance(batch, WriteBatch)
        self.assertEqual(len(batch.operations), 1)
        op = batch.operations[0]
        self.assertIsInstance(op, ReplaceRect)
        assert isinstance(op, ReplaceRect)
        self.assertEqual((op.x, op.y, op.width, op.height), (10, 8, 20, 12))

    def test_compile_incremental_legend_patch_avoids_full_rerender(self) -> None:
        x = np.asarray([0, 1, 2, 3, 4], dtype=np.float64)
        y1 = np.asarray([1, 2, 1.5, 2.5, 2.0], dtype=np.float64)
        y2 = np.asarray([1.3, 2.1, 1.7, 2.7, 2.1], dtype=np.float64)
        fig = figure(width=260, height=180)
        ax = fig.axes()
        ax.plot(x=x, y=y1, color=(255, 170, 70), label="A")
        ax.plot(x=x, y=y2, color=(70, 170, 255), label="B")
        fig.to_rgba()

        bounds = ax.legend_bounds()
        self.assertIsNotNone(bounds)
        assert bounds is not None
        cx = float(bounds[0] + 4)
        cy = float(bounds[1] + 4)
        ax.update_legend_drag(cx, cy, True)
        ax.update_legend_drag(cx - 24.0, cy + 12.0, True)
        dirty = ax.take_legend_dirty_rect()
        self.assertIsNotNone(dirty)

        with mock.patch.object(fig, "to_rgba", side_effect=AssertionError("full rerender should not be used")):
            batch = fig.compile_incremental_write_batch(dirty)
        self.assertIsInstance(batch.operations[0], ReplaceRect)

    def test_incremental_plot_state_fast_path_gating(self) -> None:
        data_plane = np.zeros((10, 20, 4), dtype=np.uint8)
        state = IncrementalPlotState(
            width=80,
            height=40,
            plot_rect=(10, 5, 20, 10),
            y_limits=DataLimits(xmin=0.0, xmax=4.0, ymin=-1.0, ymax=1.0),
            series_values=np.asarray([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64),
            data_plane=data_plane,
            line_color=(255, 170, 70, 255),
            line_width=1,
            marker_color=(90, 190, 255, 204),
            marker_size=2,
        )
        ok = state.can_fast_path(
            width=80,
            height=40,
            next_values=np.asarray([2.0, 3.0, 4.0, 5.0, 6.0], dtype=np.float64),
            y_limits=DataLimits(xmin=0.0, xmax=4.0, ymin=-1.0, ymax=1.0),
        )
        self.assertTrue(ok)
        not_ok = state.can_fast_path(
            width=80,
            height=40,
            next_values=np.asarray([2.0, 3.1, 4.0, 5.0, 6.0], dtype=np.float64),
            y_limits=DataLimits(xmin=0.0, xmax=4.0, ymin=-1.0, ymax=1.0),
        )
        self.assertFalse(not_ok)

    def test_incremental_plot_state_advance_updates_last_value(self) -> None:
        data_plane = np.zeros((10, 20, 4), dtype=np.uint8)
        state = IncrementalPlotState(
            width=80,
            height=40,
            plot_rect=(10, 5, 20, 10),
            y_limits=DataLimits(xmin=0.0, xmax=4.0, ymin=-1.0, ymax=1.0),
            series_values=np.asarray([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64),
            data_plane=data_plane,
            line_color=(255, 170, 70, 255),
            line_width=1,
            marker_color=(90, 190, 255, 204),
            marker_size=2,
        )
        out = state.advance_one(np.asarray([2.0, 3.0, 4.0, 5.0, 6.0], dtype=np.float64))
        self.assertEqual(out.shape, (10, 20, 4))
        self.assertEqual(float(state.series_values[-1]), 6.0)
        self.assertGreater(int(out[:, :, 3].sum()), 0)

    def test_incremental_plot_state_reverse_direction_fast_path(self) -> None:
        data_plane = np.zeros((10, 20, 4), dtype=np.uint8)
        state = IncrementalPlotState(
            width=80,
            height=40,
            plot_rect=(10, 5, 20, 10),
            y_limits=DataLimits(xmin=0.0, xmax=4.0, ymin=-1.0, ymax=1.0),
            series_values=np.asarray([5.0, 4.0, 3.0, 2.0, 1.0], dtype=np.float64),
            data_plane=data_plane,
            line_color=(255, 170, 70, 255),
            line_width=1,
            marker_color=(90, 190, 255, 204),
            marker_size=2,
            push_from_right=False,
        )
        ok = state.can_fast_path(
            width=80,
            height=40,
            next_values=np.asarray([6.0, 5.0, 4.0, 3.0, 2.0], dtype=np.float64),
            y_limits=DataLimits(xmin=0.0, xmax=4.0, ymin=-1.0, ymax=1.0),
        )
        self.assertTrue(ok)

    def test_sample_to_x_mapper_reset_and_push(self) -> None:
        mapper = SampleToXMapper(sample_count=5)
        mapper.reset(latest_x=1.0, step=0.1)
        self.assertAlmostEqual(mapper.window()[0], 0.6, places=9)
        self.assertAlmostEqual(mapper.window()[1], 1.0, places=9)
        mapper.push(1.2)
        self.assertAlmostEqual(mapper.window()[0], 0.7, places=9)
        self.assertAlmostEqual(mapper.window()[1], 1.2, places=9)

    def test_sample_to_x_mapper_rejects_invalid_count(self) -> None:
        with self.assertRaises(ValueError):
            SampleToXMapper(sample_count=1)

    def test_dynamic_sample_axis_window_and_visibility(self) -> None:
        axis = DynamicSampleAxis(sample_count=5, dx=2.0, x0=0.0)
        axis.on_sample()
        axis.on_sample()
        xmin, xmax = axis.x_window_sorted()
        self.assertLessEqual(xmin, xmax)
        self.assertEqual(axis.label_visibility_bounds(), (0.0, None))

    def test_dynamic_sample_axis_negative_dx_push_from_left(self) -> None:
        axis = DynamicSampleAxis(sample_count=5, dx=-1.0, x0=0.0)
        self.assertFalse(axis.push_from_right)
        self.assertEqual(axis.label_visibility_bounds(), (None, 0.0))

    def test_dynamic_2d_monotonic_axis_gap_and_update(self) -> None:
        axis = Dynamic2DMonotonicAxis(viewport_bins=8, dx=1.0, x0=0.0)
        first = axis.ingest(0.1, 1.0)
        self.assertEqual(first.status, "advance")
        self.assertEqual(first.bin_index, 0)
        self.assertEqual(first.gap_bins, 0)

        jumped = axis.ingest(3.2, 2.0)
        self.assertEqual(jumped.status, "advance")
        self.assertEqual(jumped.bin_index, 3)
        self.assertEqual(jumped.gap_bins, 2)

        same_bin = axis.ingest(3.49, 2.5)
        self.assertEqual(same_bin.status, "update_current")
        self.assertEqual(same_bin.bin_index, 3)
        self.assertAlmostEqual(same_bin.x_quantized, 3.0, places=9)

    def test_dynamic_2d_monotonic_axis_quantizes_non_multiple_x(self) -> None:
        axis = Dynamic2DMonotonicAxis(viewport_bins=8, dx=0.1, x0=0.0)
        out = axis.ingest(0.26, 1.0)
        self.assertEqual(out.bin_index, 3)
        self.assertAlmostEqual(out.x_quantized, 0.3, places=9)
        self.assertAlmostEqual(out.residual_bins, -0.4, places=9)

    def test_dynamic_2d_monotonic_axis_rejects_out_of_order(self) -> None:
        axis = Dynamic2DMonotonicAxis(viewport_bins=8, dx=1.0, x0=0.0)
        axis.ingest(2.1, 1.0)
        out = axis.ingest(1.4, 2.0)
        self.assertEqual(out.status, "out_of_order")

    def test_dynamic_2d_monotonic_axis_negative_dx_progression(self) -> None:
        axis = Dynamic2DMonotonicAxis(viewport_bins=8, dx=-0.5, x0=0.0)
        self.assertFalse(axis.push_from_right)
        first = axis.ingest(-0.1, 1.0)
        self.assertEqual(first.bin_index, 0)
        next_val = axis.ingest(-1.2, 2.0)
        self.assertEqual(next_val.status, "advance")
        self.assertEqual(next_val.bin_index, 2)
        self.assertEqual(next_val.gap_bins, 1)

    def test_dynamic_2d_stream_buffer_ingest_and_update(self) -> None:
        buf = Dynamic2DStreamBuffer(viewport_bins=6, dx=1.0, x0=0.0)
        a = buf.ingest(0.0, 1.0)
        self.assertEqual(a.status, "advance")
        self.assertAlmostEqual(float(buf.x_values[-1]), 0.0, places=9)
        self.assertAlmostEqual(float(buf.y_values[-1]), 1.0, places=9)
        b = buf.ingest(0.2, 2.0)  # same bin
        self.assertEqual(b.status, "update_current")
        self.assertAlmostEqual(float(buf.y_values[-1]), 2.0, places=9)

    def test_dynamic_2d_stream_buffer_gap_inserts_nan(self) -> None:
        buf = Dynamic2DStreamBuffer(viewport_bins=8, dx=1.0, x0=0.0)
        buf.ingest(0.0, 1.0)
        out = buf.ingest(3.0, 5.0)
        self.assertEqual(out.status, "advance")
        self.assertEqual(out.gap_bins, 2)
        self.assertTrue(np.isnan(buf.x_values[-2]))
        self.assertTrue(np.isnan(buf.x_values[-3]))
        self.assertAlmostEqual(float(buf.x_values[-1]), 3.0, places=9)
        self.assertAlmostEqual(float(buf.y_values[-1]), 5.0, places=9)

    def test_dynamic_2d_stream_buffer_rejects_out_of_order(self) -> None:
        buf = Dynamic2DStreamBuffer(viewport_bins=8, dx=1.0, x0=0.0)
        buf.ingest(2.0, 1.0)
        prev_x = buf.x_values.copy()
        prev_y = buf.y_values.copy()
        out = buf.ingest(1.0, 2.0)
        self.assertEqual(out.status, "out_of_order")
        self.assertTrue(np.array_equal(buf.x_values, prev_x, equal_nan=True))
        self.assertTrue(np.array_equal(buf.y_values, prev_y, equal_nan=True))

    def test_dynamic_2d_app_rolling_buffers_shift_in_place(self) -> None:
        app_path = Path(__file__).resolve().parents[1] / "examples" / "plots" / "dynamic_plot_2d" / "app_main.py"
        spec = importlib.util.spec_from_file_location("dynamic_plot_2d_app_main", app_path)
        self.assertIsNotNone(spec)
        assert spec is not None
        mod = importlib.util.module_from_spec(spec)
        self.assertIsNotNone(spec.loader)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        app = mod.DynamicPlot2DApp()

        x_id = id(app._x_values)
        y_id = id(app._y_values)
        app._update_value_window(gap_bins=0, x_value=0.0, y_value=1.0, update_only=False)
        app._update_value_window(gap_bins=0, x_value=0.1, y_value=2.0, update_only=False)

        self.assertEqual(id(app._x_values), x_id)
        self.assertEqual(id(app._y_values), y_id)
        self.assertAlmostEqual(float(app._x_values[-2]), 0.0, places=9)
        self.assertAlmostEqual(float(app._x_values[-1]), 0.1, places=9)
        self.assertAlmostEqual(float(app._y_values[-2]), 1.0, places=9)
        self.assertAlmostEqual(float(app._y_values[-1]), 2.0, places=9)

    def test_dynamic_2d_app_gap_inserts_nan_columns_before_new_sample(self) -> None:
        app_path = Path(__file__).resolve().parents[1] / "examples" / "plots" / "dynamic_plot_2d" / "app_main.py"
        spec = importlib.util.spec_from_file_location("dynamic_plot_2d_app_main_gap", app_path)
        self.assertIsNotNone(spec)
        assert spec is not None
        mod = importlib.util.module_from_spec(spec)
        self.assertIsNotNone(spec.loader)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        app = mod.DynamicPlot2DApp()

        app._update_value_window(gap_bins=2, x_value=0.3, y_value=3.0, update_only=False)
        self.assertTrue(np.isnan(app._x_values[-2]))
        self.assertTrue(np.isnan(app._x_values[-3]))
        self.assertTrue(np.isnan(app._y_values[-2]))
        self.assertTrue(np.isnan(app._y_values[-3]))
        self.assertAlmostEqual(float(app._x_values[-1]), 0.3, places=9)
        self.assertAlmostEqual(float(app._y_values[-1]), 3.0, places=9)

    def test_series_mode_rejects_invalid_mode(self) -> None:
        fig = figure(width=64, height=48)
        ax = fig.axes()
        with self.assertRaises(PlotDataError):
            ax.series(y=[1, 2, 3], mode="bad")


if __name__ == "__main__":
    unittest.main()
