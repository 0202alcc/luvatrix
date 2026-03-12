from __future__ import annotations

import os
import numpy as np

from luvatrix_plot.compile import compile_full_rewrite_batch
from luvatrix_plot.raster import draw_hline, draw_text, draw_vline, new_canvas


class TradingDashboardApp:
    """Order-book over time heatmap using incremental rolling pixel buffers."""

    def __init__(self) -> None:
        self._width = 0
        self._height = 0

        self._time_window_sec = max(30, int(os.getenv("LUVATRIX_ORDERBOOK_TIME_WINDOW_SEC", "120")))
        self._tick_size = float(os.getenv("LUVATRIX_ORDERBOOK_TICK_SIZE", "0.25"))
        self._levels_per_side = 15

        self._mid_price = float(os.getenv("LUVATRIX_ORDERBOOK_INITIAL_MID", "100.0"))
        self._mid_drift = float(os.getenv("LUVATRIX_ORDERBOOK_DRIFT", "0.12"))
        self._fit_pad_ticks = max(0.0, float(os.getenv("LUVATRIX_ORDERBOOK_FIT_PAD_TICKS", "1.0")))
        self._gradient_blur_px = max(1, int(os.getenv("LUVATRIX_ORDERBOOK_GRADIENT_BLUR_PX", "3")))
        self._rng = np.random.default_rng(seed=42)

        self._plot_x0 = 0
        self._plot_y0 = 0
        self._plot_w = 1
        self._plot_h = 1
        self._bid_heatmap = np.zeros((1, 1), dtype=np.float32)
        self._ask_heatmap = np.zeros((1, 1), dtype=np.float32)

        self._latest_lowest_bid = self._mid_price - float(self._levels_per_side) * self._tick_size
        self._latest_highest_ask = self._mid_price + float(self._levels_per_side) * self._tick_size
        self._price_min = 0.0
        self._price_max = 0.0
        self._elapsed = 0.0

    def _layout(self) -> tuple[int, int, int, int]:
        left, right, top, bottom = 84, 18, 24, 34
        x0, y0 = left, top
        pw = max(8, self._width - left - right)
        ph = max(8, self._height - top - bottom)
        return x0, y0, pw, ph

    def _ensure_heatmap_buffers(self) -> None:
        x0, y0, pw, ph = self._layout()
        if pw == self._plot_w and ph == self._plot_h and x0 == self._plot_x0 and y0 == self._plot_y0:
            return
        self._plot_x0, self._plot_y0, self._plot_w, self._plot_h = x0, y0, pw, ph
        self._bid_heatmap = np.zeros((ph, pw), dtype=np.float32)
        self._ask_heatmap = np.zeros((ph, pw), dtype=np.float32)

    def _fit_price_window_to_book(self, lowest_bid: float, highest_ask: float) -> None:
        pad = self._fit_pad_ticks * self._tick_size
        lo = lowest_bid - pad
        hi = highest_ask + pad
        if hi <= lo:
            hi = lo + self._tick_size
        self._price_min = lo
        self._price_max = hi

    def _sample_orderbook_frame(
        self,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float, float]:
        bid_prices = np.full(self._levels_per_side, np.nan, dtype=np.float64)
        ask_prices = np.full(self._levels_per_side, np.nan, dtype=np.float64)
        bid_sizes = np.zeros(self._levels_per_side, dtype=np.float32)
        ask_sizes = np.zeros(self._levels_per_side, dtype=np.float32)

        bid_levels = int(np.clip(round(self._levels_per_side * (0.6 + 0.5 * self._rng.random())), 4, self._levels_per_side))
        ask_levels = int(np.clip(round(self._levels_per_side * (0.6 + 0.5 * self._rng.random())), 4, self._levels_per_side))

        bid_offsets = np.arange(1, bid_levels + 1, dtype=np.float64)
        ask_offsets = np.arange(1, ask_levels + 1, dtype=np.float64)

        bid_prices[:bid_levels] = self._mid_price - bid_offsets * self._tick_size
        ask_prices[:ask_levels] = self._mid_price + ask_offsets * self._tick_size

        bid_decay = np.exp(-bid_offsets / 7.0)
        ask_decay = np.exp(-ask_offsets / 7.0)
        bid_noise = 0.65 + 0.7 * self._rng.random(bid_levels)
        ask_noise = 0.65 + 0.7 * self._rng.random(ask_levels)
        bid_sizes[:bid_levels] = (bid_decay * bid_noise).astype(np.float32)
        ask_sizes[:ask_levels] = (ask_decay * ask_noise).astype(np.float32)

        bid_max = float(np.max(bid_sizes[:bid_levels])) if bid_levels > 0 else 0.0
        ask_max = float(np.max(ask_sizes[:ask_levels])) if ask_levels > 0 else 0.0
        if bid_max > 0.0:
            bid_sizes[:bid_levels] /= bid_max
        if ask_max > 0.0:
            ask_sizes[:ask_levels] /= ask_max

        lowest_bid = float(np.nanmin(bid_prices))
        highest_ask = float(np.nanmax(ask_prices))
        return bid_prices, bid_sizes, ask_prices, ask_sizes, lowest_bid, highest_ask

    def _build_side_column(self, prices: np.ndarray, sizes: np.ndarray, *, ph: int, price_span: float) -> np.ndarray:
        visible_bins = max(1, int(np.ceil(price_span / self._tick_size)))
        bin_values = np.zeros(visible_bins, dtype=np.float32)
        points: list[tuple[int, float]] = []
        for price, weight in zip(prices, sizes):
            if not np.isfinite(price) or weight <= 0.0:
                continue
            idx = int(np.floor((float(price) - self._price_min) / self._tick_size))
            if 0 <= idx < visible_bins:
                points.append((idx, float(weight)))
        if not points:
            return np.zeros(ph, dtype=np.float32)

        points.sort(key=lambda item: item[0])
        for idx, w in points:
            bin_values[idx] = max(bin_values[idx], w)

        # Fill gaps between adjacent bins by interpolation.
        for i in range(len(points) - 1):
            b0, w0 = points[i]
            b1, w1 = points[i + 1]
            if b1 <= b0 + 1:
                continue
            span = b1 - b0
            for b in range(b0 + 1, b1):
                t = (b - b0) / span
                w = (1.0 - t) * w0 + t * w1
                bin_values[b] = max(bin_values[b], float(w))

        # Blur in bin space for smooth gradient.
        r = self._gradient_blur_px
        if r > 0:
            x = np.arange(-r, r + 1, dtype=np.float32)
            sigma = max(1.0, r * 0.6)
            kernel = np.exp(-(x * x) / (2.0 * sigma * sigma))
            kernel /= np.sum(kernel)
            bin_values = np.convolve(bin_values, kernel, mode="same").astype(np.float32)

        # Expand bins to full pixel rows (no partial-bin coverage).
        col = np.zeros(ph, dtype=np.float32)
        for b in range(visible_bins):
            row_start = ph - int(round((b + 1) * ph / visible_bins))
            row_end = ph - int(round(b * ph / visible_bins)) - 1
            row_start = max(0, min(ph - 1, row_start))
            row_end = max(0, min(ph - 1, row_end))
            if row_end < row_start:
                continue
            col[row_start : row_end + 1] = max(float(bin_values[b]), float(col[row_start]))

        return col

    def _shift_heatmap_vertical(self, old_min: float, old_max: float, new_min: float, new_max: float) -> None:
        ph = self._plot_h
        if ph <= 1 or old_max <= old_min:
            return
        old_span = max(self._tick_size, old_max - old_min)
        old_center = 0.5 * (old_min + old_max)
        new_center = 0.5 * (new_min + new_max)
        shift = int(round((new_center - old_center) / old_span * (ph - 1)))
        if shift == 0:
            return
        self._bid_heatmap = np.roll(self._bid_heatmap, shift, axis=0)
        self._ask_heatmap = np.roll(self._ask_heatmap, shift, axis=0)
        if shift > 0:
            self._bid_heatmap[:shift, :] = 0.0
            self._ask_heatmap[:shift, :] = 0.0
        else:
            self._bid_heatmap[shift:, :] = 0.0
            self._ask_heatmap[shift:, :] = 0.0

    def _push_distribution_column(
        self,
        bid_prices: np.ndarray,
        bid_sizes: np.ndarray,
        ask_prices: np.ndarray,
        ask_sizes: np.ndarray,
        lowest_bid: float,
        highest_ask: float,
    ) -> None:
        self._ensure_heatmap_buffers()
        old_min = self._price_min
        old_max = self._price_max
        self._fit_price_window_to_book(lowest_bid, highest_ask)
        self._shift_heatmap_vertical(old_min, old_max, self._price_min, self._price_max)

        price_span = max(self._tick_size, self._price_max - self._price_min)
        bid_col = self._build_side_column(bid_prices, bid_sizes, ph=self._plot_h, price_span=price_span)
        ask_col = self._build_side_column(ask_prices, ask_sizes, ph=self._plot_h, price_span=price_span)

        self._bid_heatmap = np.roll(self._bid_heatmap, -1, axis=1)
        self._ask_heatmap = np.roll(self._ask_heatmap, -1, axis=1)
        self._bid_heatmap[:, -1] = bid_col
        self._ask_heatmap[:, -1] = ask_col

    def _step_market(self, dt: float) -> bool:
        self._elapsed += max(0.0, dt)
        if self._elapsed < 1.0:
            return False
        self._elapsed -= 1.0
        self._mid_price += self._mid_drift * float(self._rng.normal())
        bid_prices, bid_sizes, ask_prices, ask_sizes, lowest_bid, highest_ask = self._sample_orderbook_frame()
        self._latest_lowest_bid = float(lowest_bid)
        self._latest_highest_ask = float(highest_ask)
        self._push_distribution_column(bid_prices, bid_sizes, ask_prices, ask_sizes, lowest_bid, highest_ask)
        return True

    def _render(self) -> np.ndarray:
        canvas = new_canvas(self._width, self._height, color=(10, 14, 20, 255))
        self._ensure_heatmap_buffers()
        x0, y0, pw, ph = self._plot_x0, self._plot_y0, self._plot_w, self._plot_h
        x1, y1 = x0 + pw - 1, y0 + ph - 1

        bid_img = self._bid_heatmap
        ask_img = self._ask_heatmap

        bid_max = float(np.max(bid_img))
        ask_max = float(np.max(ask_img))
        if bid_max > 0.0:
            bid_img = bid_img / bid_max
        if ask_max > 0.0:
            ask_img = ask_img / ask_max

        base = np.array([14, 20, 28], dtype=np.float32).reshape(1, 1, 3)
        green = np.array([45, 220, 95], dtype=np.float32).reshape(1, 1, 3)
        red = np.array([230, 70, 70], dtype=np.float32).reshape(1, 1, 3)
        rgb = base + (bid_img[:, :, None] * green) + (ask_img[:, :, None] * red)
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)

        canvas[y0 : y0 + ph, x0 : x0 + pw, :3] = rgb
        canvas[y0 : y0 + ph, x0 : x0 + pw, 3] = 255

        # Price-bin background guides: true bin boundaries with stronger major cadence.
        price_span = max(self._tick_size, self._price_max - self._price_min)
        visible_bins = max(1, int(np.ceil(price_span / self._tick_size)))
        minor_grid = (82, 96, 114, 46)
        major_grid = (106, 122, 142, 84)
        for b in range(visible_bins + 1):
            y = y0 + ph - int(round(b * ph / visible_bins))
            y = max(y0, min(y1, y))
            color = major_grid if (b % 5 == 0) else minor_grid
            draw_hline(canvas, x0, x1, y, color)

        frame = (102, 116, 136, 255)
        draw_hline(canvas, x0, x1, y0, frame)
        draw_hline(canvas, x0, x1, y1, frame)
        draw_vline(canvas, x0, y0, y1, frame)
        draw_vline(canvas, x1, y0, y1, frame)

        label = (212, 222, 236, 255)
        draw_text(canvas, 8, 6, "Order Book Heatmap (Bid=Green, Ask=Red)", label, font_size_px=12.0)

        y_ticks = 6
        for i in range(y_ticks + 1):
            frac = i / y_ticks
            y = int(round(y0 + frac * (ph - 1)))
            draw_hline(canvas, x0 - 3, x0, y, frame)
            price = self._price_max - frac * (self._price_max - self._price_min)
            draw_text(canvas, 8, max(0, y - 6), f"{price:8.2f}", label, font_size_px=10.0)

        x_ticks = 6
        for i in range(x_ticks + 1):
            frac = i / x_ticks
            x = int(round(x0 + frac * (pw - 1)))
            draw_vline(canvas, x, y1, y1 + 3, frame)
            seconds_ago = int(round((1.0 - frac) * (self._time_window_sec - 1)))
            draw_text(canvas, max(0, x - 12), y1 + 8, f"-{seconds_ago}s", label, font_size_px=10.0)

        draw_text(canvas, x0 + max(0, pw // 2 - 18), self._height - 18, "time", label, font_size_px=10.0)
        draw_text(canvas, 8, y0 + max(0, ph // 2 - 6), "quote", label, font_size_px=10.0, rotate_deg=270)
        return canvas

    def init(self, ctx) -> None:
        snapshot = ctx.read_matrix_snapshot()
        height, width, _ = snapshot.shape
        self._width = width
        self._height = height
        self._ensure_heatmap_buffers()
        self._elapsed = 1.0
        for _ in range(self._plot_w):
            self._step_market(1.0)

    def loop(self, ctx, dt: float) -> None:
        snapshot = ctx.read_matrix_snapshot()
        height, width, _ = snapshot.shape
        if height != self._height or width != self._width:
            self._height = height
            self._width = width
            self._ensure_heatmap_buffers()
        self._step_market(dt)
        frame = self._render()
        ctx.submit_write_batch(compile_full_rewrite_batch(frame))
        return None

    def stop(self, ctx) -> None:
        _ = ctx
        return None


def create() -> TradingDashboardApp:
    return TradingDashboardApp()
