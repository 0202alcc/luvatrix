from __future__ import annotations

from decimal import Decimal
import unittest
from unittest import mock

import numpy as np
import torch

from luvatrix_core.core.window_matrix import FullRewrite, WriteBatch
from luvatrix_plot import PlotDataError, figure
from luvatrix_plot.adapters.normalize import normalize_xy
from luvatrix_plot.display import resolve_default_figure_size
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

    def test_resolution_inference_prefers_half_step_for_tenth_data(self) -> None:
        values = np.asarray([2.0, 2.4, 2.1, 3.0, 2.8, 3.2, 3.6, 3.1, 3.9, 4.3], dtype=np.float64)
        resolution = infer_resolution(values)
        self.assertAlmostEqual(resolution or 0.0, 0.1, places=9)
        preferred = preferred_major_step_from_resolution(resolution)
        self.assertAlmostEqual(preferred or 0.0, 0.5, places=9)
        ticks = generate_nice_ticks(1.795, 6.305, 5, preferred_step=preferred)
        self.assertTrue(np.isclose(abs(ticks[1] - ticks[0]), 0.5))

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

    def test_series_mode_rejects_invalid_mode(self) -> None:
        fig = figure(width=64, height=48)
        ax = fig.axes()
        with self.assertRaises(PlotDataError):
            ax.series(y=[1, 2, 3], mode="bad")


if __name__ == "__main__":
    unittest.main()
