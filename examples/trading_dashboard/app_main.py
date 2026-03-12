from __future__ import annotations

import os
import numpy as np

from luvatrix_plot.compile import compile_full_rewrite_batch
from luvatrix_plot.raster import draw_hline, draw_text, draw_vline, new_canvas, text_size


class TradingDashboardApp:
    """Order-book over time heatmap using incremental rolling bin buffers."""

    def __init__(self) -> None:
        self._width = 0
        self._height = 0

        self._time_window_sec = max(30, int(os.getenv("LUVATRIX_ORDERBOOK_TIME_WINDOW_SEC", "120")))
        self._display_window_sec = max(
            1,
            min(
                self._time_window_sec,
                int(os.getenv("LUVATRIX_ORDERBOOK_DISPLAY_WINDOW_SEC", str(self._time_window_sec))),
            ),
        )
        self._tick_size = float(os.getenv("LUVATRIX_ORDERBOOK_TICK_SIZE", "0.25"))
        self._levels_per_side = 15

        self._mid_price = float(os.getenv("LUVATRIX_ORDERBOOK_INITIAL_MID", "100.0"))
        self._mid_drift = float(os.getenv("LUVATRIX_ORDERBOOK_DRIFT", "0.12"))
        self._fit_pad_ticks = max(0.0, float(os.getenv("LUVATRIX_ORDERBOOK_FIT_PAD_TICKS", "1.0")))
        self._gradient_blur_px = max(1, int(os.getenv("LUVATRIX_ORDERBOOK_GRADIENT_BLUR_PX", "3")))
        self._bin_pad_ticks = max(0, int(np.ceil(self._fit_pad_ticks)))
        self._bin_count = (2 * self._levels_per_side) + (2 * self._bin_pad_ticks)
        self._global_bin_count = max(self._bin_count * 8, 256)
        self._rng = np.random.default_rng(seed=42)

        self._plot_x0 = 0
        self._plot_y0 = 0
        self._plot_w = 1
        self._plot_h = 1
        self._bars_x0 = 0
        self._bars_y0 = 0
        self._bars_w = 1
        self._bars_h = 1
        self._bid_heatmap = np.zeros((self._bin_count, 1), dtype=np.float32)
        self._ask_heatmap = np.zeros((self._bin_count, 1), dtype=np.float32)
        self._global_bid_heatmap = np.zeros((self._global_bin_count, 1), dtype=np.float32)
        self._global_ask_heatmap = np.zeros((self._global_bin_count, 1), dtype=np.float32)

        self._latest_lowest_bid = self._mid_price - float(self._levels_per_side) * self._tick_size
        self._latest_highest_ask = self._mid_price + float(self._levels_per_side) * self._tick_size
        self._latest_bid_prices = np.full(self._levels_per_side, np.nan, dtype=np.float64)
        self._latest_bid_sizes_exact = np.zeros(self._levels_per_side, dtype=np.float32)
        self._latest_ask_prices = np.full(self._levels_per_side, np.nan, dtype=np.float64)
        self._latest_ask_sizes_exact = np.zeros(self._levels_per_side, dtype=np.float32)
        self._price_min = 0.0
        self._price_max = 0.0
        self._global_price_min = self._mid_price - 0.5 * float(self._global_bin_count) * self._tick_size
        self._global_price_max = self._global_price_min + float(self._global_bin_count) * self._tick_size
        self._elapsed = 0.0

    def _price_label_decimals(self) -> int:
        if self._tick_size <= 0:
            return 2
        return max(2, min(8, int(np.ceil(-np.log10(self._tick_size))) + 1))

    def _layout(self) -> tuple[int, int, int, int, int, int, int, int, int]:
        left, right, top, bottom = 84, 18, 28, 34
        x0, y0 = left, top
        pw = max(8, self._width - left - right)
        total_h = max(24, self._height - top - bottom)
        gap = max(22, min(44, int(round(total_h * 0.16))))
        bars_h = max(8, min(total_h // 2, int(round(total_h * 0.23))))
        heat_h = max(8, total_h - bars_h - gap)
        if heat_h + bars_h + gap > total_h:
            bars_h = max(8, total_h - heat_h - gap)
        if heat_h + bars_h + gap > total_h:
            gap = max(0, total_h - heat_h - bars_h)
        bars_y0 = y0 + heat_h + gap
        return x0, y0, pw, heat_h, x0, bars_y0, pw, bars_h, gap

    def _ensure_heatmap_buffers(self) -> None:
        x0, y0, pw, ph, bx0, by0, bw, bh, _gap = self._layout()
        if (
            pw == self._plot_w
            and ph == self._plot_h
            and x0 == self._plot_x0
            and y0 == self._plot_y0
            and bw == self._bars_w
            and bh == self._bars_h
            and bx0 == self._bars_x0
            and by0 == self._bars_y0
        ):
            return
        self._plot_x0, self._plot_y0, self._plot_w, self._plot_h = x0, y0, pw, ph
        self._bars_x0, self._bars_y0, self._bars_w, self._bars_h = bx0, by0, bw, bh
        self._bid_heatmap = np.zeros((self._bin_count, pw), dtype=np.float32)
        self._ask_heatmap = np.zeros((self._bin_count, pw), dtype=np.float32)
        self._global_bid_heatmap = np.zeros((self._global_bin_count, pw), dtype=np.float32)
        self._global_ask_heatmap = np.zeros((self._global_bin_count, pw), dtype=np.float32)

    def _fit_price_window_to_book(self, lowest_bid: float, highest_ask: float) -> None:
        lo = lowest_bid - float(self._bin_pad_ticks) * self._tick_size
        lo = round(lo / self._tick_size) * self._tick_size
        self._price_min = lo
        self._price_max = lo + float(self._bin_count) * self._tick_size

    def _ensure_global_range_for_local(self) -> None:
        if self._price_min >= self._global_price_min and self._price_max <= self._global_price_max:
            return
        offset_bins = max(0, (self._global_bin_count - self._bin_count) // 2)
        target_min = self._price_min - float(offset_bins) * self._tick_size
        target_min = round(target_min / self._tick_size) * self._tick_size
        shift = int(round((target_min - self._global_price_min) / self._tick_size))
        if shift != 0:
            self._global_bid_heatmap = np.roll(self._global_bid_heatmap, shift, axis=0)
            self._global_ask_heatmap = np.roll(self._global_ask_heatmap, shift, axis=0)
            if shift > 0:
                self._global_bid_heatmap[:shift, :] = 0.0
                self._global_ask_heatmap[:shift, :] = 0.0
            else:
                self._global_bid_heatmap[shift:, :] = 0.0
                self._global_ask_heatmap[shift:, :] = 0.0
        self._global_price_min = target_min
        self._global_price_max = target_min + float(self._global_bin_count) * self._tick_size

    def _sample_orderbook_frame(
        self,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, float, float]:
        bid_prices = np.full(self._levels_per_side, np.nan, dtype=np.float64)
        ask_prices = np.full(self._levels_per_side, np.nan, dtype=np.float64)
        bid_sizes = np.zeros(self._levels_per_side, dtype=np.float32)
        ask_sizes = np.zeros(self._levels_per_side, dtype=np.float32)

        bid_levels = self._levels_per_side
        ask_levels = self._levels_per_side

        bid_offsets = np.arange(0, bid_levels, dtype=np.float64)
        ask_offsets = np.arange(1, ask_levels + 1, dtype=np.float64)

        bid_prices[:bid_levels] = self._mid_price - bid_offsets * self._tick_size
        ask_prices[:ask_levels] = self._mid_price + ask_offsets * self._tick_size

        bid_decay = np.exp(-bid_offsets / 7.0)
        ask_decay = np.exp(-ask_offsets / 7.0)
        bid_noise = 0.65 + 0.7 * self._rng.random(bid_levels)
        ask_noise = 0.65 + 0.7 * self._rng.random(ask_levels)
        bid_sizes[:bid_levels] = (bid_decay * bid_noise).astype(np.float32)
        ask_sizes[:ask_levels] = (ask_decay * ask_noise).astype(np.float32)
        bid_sizes_exact = bid_sizes.copy()
        ask_sizes_exact = ask_sizes.copy()

        bid_max = float(np.max(bid_sizes[:bid_levels])) if bid_levels > 0 else 0.0
        ask_max = float(np.max(ask_sizes[:ask_levels])) if ask_levels > 0 else 0.0
        if bid_max > 0.0:
            bid_sizes[:bid_levels] /= bid_max
        if ask_max > 0.0:
            ask_sizes[:ask_levels] /= ask_max

        lowest_bid = float(np.nanmin(bid_prices))
        highest_ask = float(np.nanmax(ask_prices))
        return bid_prices, bid_sizes, ask_prices, ask_sizes, bid_sizes_exact, ask_sizes_exact, lowest_bid, highest_ask

    def _build_side_column(self, prices: np.ndarray, sizes: np.ndarray) -> np.ndarray:
        bin_values = np.zeros(self._bin_count, dtype=np.float32)
        points: list[tuple[int, float]] = []
        for price, weight in zip(prices, sizes):
            if not np.isfinite(price) or weight <= 0.0:
                continue
            idx = int(np.rint((float(price) - self._price_min) / self._tick_size))
            if 0 <= idx < self._bin_count:
                points.append((idx, float(weight)))
        if not points:
            return bin_values

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

        return bin_values

    def _shift_heatmap_vertical(self, old_min: float, old_max: float, new_min: float, new_max: float) -> None:
        _ = (old_max, new_max)
        if self._bin_count <= 1:
            return
        shift = int(round((new_min - old_min) / self._tick_size))
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

    def _rehydrate_local_from_global(self) -> None:
        local_bid = np.zeros_like(self._bid_heatmap)
        local_ask = np.zeros_like(self._ask_heatmap)
        offset = int(round((self._price_min - self._global_price_min) / self._tick_size))
        g0 = max(0, offset)
        g1 = min(self._global_bin_count, offset + self._bin_count)
        if g1 <= g0:
            self._bid_heatmap = local_bid
            self._ask_heatmap = local_ask
            return
        l0 = max(0, -offset)
        l1 = l0 + (g1 - g0)
        local_bid[l0:l1, :] = self._global_bid_heatmap[g0:g1, :]
        local_ask[l0:l1, :] = self._global_ask_heatmap[g0:g1, :]
        self._bid_heatmap = local_bid
        self._ask_heatmap = local_ask

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
        local_shifted = abs(self._price_min - old_min) > 0.5 * self._tick_size
        if local_shifted:
            self._shift_heatmap_vertical(old_min, old_max, self._price_min, self._price_max)
        self._ensure_global_range_for_local()

        bid_col = self._build_side_column(bid_prices, bid_sizes)
        ask_col = self._build_side_column(ask_prices, ask_sizes)

        self._bid_heatmap = np.roll(self._bid_heatmap, -1, axis=1)
        self._ask_heatmap = np.roll(self._ask_heatmap, -1, axis=1)
        self._bid_heatmap[:, -1] = bid_col
        self._ask_heatmap[:, -1] = ask_col

        self._global_bid_heatmap = np.roll(self._global_bid_heatmap, -1, axis=1)
        self._global_ask_heatmap = np.roll(self._global_ask_heatmap, -1, axis=1)
        self._global_bid_heatmap[:, -1] = 0.0
        self._global_ask_heatmap[:, -1] = 0.0

        offset = int(round((self._price_min - self._global_price_min) / self._tick_size))
        g0 = max(0, offset)
        g1 = min(self._global_bin_count, offset + self._bin_count)
        if g1 > g0:
            l0 = max(0, -offset)
            l1 = l0 + (g1 - g0)
            self._global_bid_heatmap[g0:g1, -1] = np.maximum(
                self._global_bid_heatmap[g0:g1, -1], bid_col[l0:l1]
            )
            self._global_ask_heatmap[g0:g1, -1] = np.maximum(
                self._global_ask_heatmap[g0:g1, -1], ask_col[l0:l1]
            )

        if local_shifted:
            self._rehydrate_local_from_global()

    def _step_market(self, dt: float) -> bool:
        self._elapsed += max(0.0, dt)
        if self._elapsed < 1.0:
            return False
        self._elapsed -= 1.0
        self._mid_price += self._mid_drift * float(self._rng.normal())
        (
            bid_prices,
            bid_sizes,
            ask_prices,
            ask_sizes,
            bid_sizes_exact,
            ask_sizes_exact,
            lowest_bid,
            highest_ask,
        ) = self._sample_orderbook_frame()
        self._latest_lowest_bid = float(lowest_bid)
        self._latest_highest_ask = float(highest_ask)
        self._latest_bid_prices = bid_prices.copy()
        self._latest_bid_sizes_exact = bid_sizes_exact.copy()
        self._latest_ask_prices = ask_prices.copy()
        self._latest_ask_sizes_exact = ask_sizes_exact.copy()
        self._push_distribution_column(bid_prices, bid_sizes, ask_prices, ask_sizes, lowest_bid, highest_ask)
        return True

    def _render(self) -> np.ndarray:
        canvas = new_canvas(self._width, self._height, color=(10, 14, 20, 255))
        self._ensure_heatmap_buffers()
        x0, y0, pw, ph = self._plot_x0, self._plot_y0, self._plot_w, self._plot_h
        x1, y1 = x0 + pw - 1, y0 + ph - 1
        bx0, by0, bw, bh = self._bars_x0, self._bars_y0, self._bars_w, self._bars_h
        bx1, by1 = bx0 + bw - 1, by0 + bh - 1
        divider_top = y1 + 1
        divider_bottom = by0 - 1

        # Display a cropped x-domain from the full rolling grid without resizing storage.
        visible_cols = max(
            1,
            min(
                self._plot_w,
                int(round(self._plot_w * (float(self._display_window_sec) / float(self._time_window_sec)))),
            ),
        )
        source_start = self._plot_w - visible_cols
        bid_bins = self._bid_heatmap[:, source_start:]
        ask_bins = self._ask_heatmap[:, source_start:]

        bid_img = np.zeros((ph, pw), dtype=np.float32)
        ask_img = np.zeros((ph, pw), dtype=np.float32)
        src_idx = (np.arange(self._plot_w, dtype=np.float32) * float(visible_cols) / float(self._plot_w)).astype(np.int32)
        src_idx = np.clip(src_idx, 0, visible_cols - 1)
        for b in range(self._bin_count):
            row_start = ph - int(round((b + 1) * ph / self._bin_count))
            row_end = ph - int(round(b * ph / self._bin_count)) - 1
            row_start = max(0, min(ph - 1, row_start))
            row_end = max(0, min(ph - 1, row_end))
            if row_end < row_start:
                continue
            # Stretch cropped domain to full plot width for zoomed-in display.
            bid_img[row_start : row_end + 1, :] = bid_bins[b, src_idx]
            ask_img[row_start : row_end + 1, :] = ask_bins[b, src_idx]

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

        # Price-bin background guides: true boundaries from the same bin partition.
        minor_grid = (82, 96, 114, 46)
        major_grid = (106, 122, 142, 84)
        for b in range(self._bin_count + 1):
            y = y0 + ph - int(round(b * ph / self._bin_count))
            y = max(y0, min(y1, y))
            color = major_grid if (b % 5 == 0) else minor_grid
            draw_hline(canvas, x0, x1, y, color)

        frame = (102, 116, 136, 255)
        draw_hline(canvas, x0, x1, y0, frame)
        draw_hline(canvas, x0, x1, y1, frame)
        draw_vline(canvas, x0, y0, y1, frame)
        draw_vline(canvas, x1, y0, y1, frame)

        label = (212, 222, 236, 255)
        title = "Order Book Heatmap (Bid=Green, Ask=Red)"
        title_w, title_h = text_size(title, font_size_px=12.0)
        title_x = x0 + max(0, (pw - title_w) // 2)
        title_y = 4
        draw_text(canvas, title_x, title_y, title, label, font_size_px=12.0)
        draw_hline(canvas, title_x, min(x1, title_x + title_w), min(y0 - 2, title_y + title_h + 1), label)

        a_y_title = "Y: price (quote)"
        a_yw, a_yh = text_size(a_y_title, font_size_px=8.0)
        a_yx = 8
        a_yy = y0 + 2
        draw_text(canvas, a_yx, a_yy, a_y_title, label, font_size_px=8.0)
        draw_hline(canvas, a_yx, a_yx + a_yw, min(y1, a_yy + a_yh + 1), label)

        best_bid = float(np.nanmax(self._latest_bid_prices)) if np.isfinite(self._latest_bid_prices).any() else np.nan
        best_ask = float(np.nanmin(self._latest_ask_prices)) if np.isfinite(self._latest_ask_prices).any() else np.nan
        spread = best_ask - best_bid if np.isfinite(best_bid) and np.isfinite(best_ask) else np.nan
        spread_text = (
            f"Spread: {spread:.{self._price_label_decimals()}f}"
            if np.isfinite(spread)
            else "Spread: --"
        )
        draw_text(canvas, max(8, x1 - 150), 4, spread_text, label, font_size_px=10.0)

        # Label every bin center. Major cadence labels are larger and emboldened.
        decimals = self._price_label_decimals()
        for b in range(self._bin_count):
            row_start = ph - int(round((b + 1) * ph / self._bin_count))
            row_end = ph - int(round(b * ph / self._bin_count)) - 1
            row_start = max(0, min(ph - 1, row_start))
            row_end = max(0, min(ph - 1, row_end))
            if row_end < row_start:
                continue
            y_center = y0 + (row_start + row_end) // 2
            price = self._price_min + (float(b) + 0.5) * self._tick_size
            text = f"{price:.{decimals}f}"
            is_major = (b % 5) == 0
            draw_hline(canvas, x0 - (6 if is_major else 3), x0, y_center, frame)
            draw_text(
                canvas,
                8,
                max(0, y_center - (7 if is_major else 5)),
                text,
                label,
                font_size_px=(11.0 if is_major else 8.5),
                embolden_px=(2 if is_major else 1),
            )

        if divider_bottom >= divider_top:
            divider_bg = np.array([8, 11, 17], dtype=np.uint8)
            canvas[divider_top : divider_bottom + 1, x0 : x0 + pw, :3] = divider_bg
            canvas[divider_top : divider_bottom + 1, x0 : x0 + pw, 3] = 255
            draw_hline(canvas, x0, x1, divider_top, frame)
            draw_hline(canvas, x0, x1, divider_bottom, frame)
            mid_y = divider_top + max(0, (divider_bottom - divider_top) // 2 - 3)
            draw_text(
                canvas,
                x0 + max(0, pw // 2 - 58),
                mid_y,
                "time (s, recent -> right)",
                label,
                font_size_px=8.0,
            )
            tx_w, tx_h = text_size("time (s, recent -> right)", font_size_px=8.0)
            draw_hline(canvas, x0 + max(0, pw // 2 - 58), x0 + max(0, pw // 2 - 58) + tx_w, mid_y + tx_h + 1, label)
        else:
            draw_text(
                canvas,
                x0 + max(0, pw // 2 - 58),
                min(self._height - 14, y1 + 14),
                "time (s, recent -> right)",
                label,
                font_size_px=8.0,
            )

        # Draw x-axis ticks/labels after divider so they are not overpainted.
        x_ticks = 6
        tick_y0 = y1
        tick_y1 = min(self._height - 1, y1 + 4)
        label_y = min(self._height - 12, y1 + 8)
        for i in range(x_ticks + 1):
            frac = i / x_ticks
            x = int(round(x0 + frac * (pw - 1)))
            draw_vline(canvas, x, tick_y0, tick_y1, frame)
            seconds_ago = int(round((1.0 - frac) * (self._display_window_sec - 1)))
            draw_text(canvas, max(0, x - 12), label_y, f"-{seconds_ago}s", label, font_size_px=9.0)

        # Y label is shown in header subtitle near the centered title.

        # Bottom row split: B (bid bars) and C (ask bars).
        bottom_gap = max(8, min(20, int(round(bw * 0.02))))
        b_w = max(16, (bw - bottom_gap) // 2)
        c_w = max(16, bw - bottom_gap - b_w)
        b_x0, c_x0 = bx0, bx0 + b_w + bottom_gap
        b_x1, c_x1 = b_x0 + b_w - 1, c_x0 + c_w - 1

        panel_bg = (15, 21, 30, 255)
        canvas[by0 : by0 + bh, b_x0 : b_x0 + b_w, :3] = np.array(panel_bg[:3], dtype=np.uint8)
        canvas[by0 : by0 + bh, b_x0 : b_x0 + b_w, 3] = 255
        canvas[by0 : by0 + bh, c_x0 : c_x0 + c_w, :3] = np.array(panel_bg[:3], dtype=np.uint8)
        canvas[by0 : by0 + bh, c_x0 : c_x0 + c_w, 3] = 255

        for px0, px1 in ((b_x0, b_x1), (c_x0, c_x1)):
            draw_hline(canvas, px0, px1, by0, frame)
            draw_hline(canvas, px0, px1, by1, frame)
            draw_vline(canvas, px0, by0, by1, frame)
            draw_vline(canvas, px1, by0, by1, frame)

        b_title = "B: Bid Distribution (Exact Qty)"
        c_title = "C: Ask Distribution (Exact Qty)"
        b_tw, b_th = text_size(b_title, font_size_px=10.0)
        c_tw, c_th = text_size(c_title, font_size_px=10.0)
        b_tx = b_x0 + max(0, (b_w - b_tw) // 2)
        c_tx = c_x0 + max(0, (c_w - c_tw) // 2)
        b_ty, c_ty = by0 + 7, by0 + 7
        draw_text(canvas, b_tx, b_ty, b_title, label, font_size_px=10.0)
        draw_text(canvas, c_tx, c_ty, c_title, label, font_size_px=10.0)
        draw_hline(canvas, b_tx, min(b_x1, b_tx + b_tw), min(by1, b_ty + b_th + 1), label)
        draw_hline(canvas, c_tx, min(c_x1, c_tx + c_tw), min(by1, c_ty + c_th + 1), label)

        b_y_title = "Y: bid price"
        c_y_title = "Y: ask price"
        b_yw, b_yh = text_size(b_y_title, font_size_px=8.0)
        c_yw, c_yh = text_size(c_y_title, font_size_px=8.0)
        b_yx, b_yy = b_x0 + 6, by0 + 21
        c_yx, c_yy = c_x0 + 6, by0 + 21
        draw_text(canvas, b_yx, b_yy, b_y_title, label, font_size_px=8.0)
        draw_text(canvas, c_yx, c_yy, c_y_title, label, font_size_px=8.0)
        draw_hline(canvas, b_yx, min(b_x1, b_yx + b_yw), min(by1, b_yy + b_yh + 1), label)
        draw_hline(canvas, c_yx, min(c_x1, c_yx + c_yw), min(by1, c_yy + c_yh + 1), label)

        b_x_title = "quantity (exact)"
        c_x_title = "quantity (exact)"
        b_xw, b_xh = text_size(b_x_title, font_size_px=8.5)
        c_xw, c_xh = text_size(c_x_title, font_size_px=8.5)
        b_qx, b_qy = b_x0 + max(0, b_w // 2 - b_xw // 2), by1 - 10
        c_qx, c_qy = c_x0 + max(0, c_w // 2 - c_xw // 2), by1 - 10
        draw_text(canvas, b_qx, b_qy, b_x_title, label, font_size_px=8.5)
        draw_text(canvas, c_qx, c_qy, c_x_title, label, font_size_px=8.5)
        draw_hline(canvas, b_qx, min(b_x1, b_qx + b_xw), min(by1, b_qy + b_xh + 1), label)
        draw_hline(canvas, c_qx, min(c_x1, c_qx + c_xw), min(by1, c_qy + c_xh + 1), label)

        def _draw_sideways_distribution(
            panel_x0: int,
            panel_x1: int,
            prices: np.ndarray,
            sizes: np.ndarray,
            bar_color: tuple[int, int, int, int],
        ) -> None:
            bar_left = panel_x0 + 88
            bar_right = panel_x1 - 72
            bar_w = max(10, bar_right - bar_left)
            header_h = min(40, max(28, bh // 3))
            usable_h = max(1, bh - header_h)
            row_h = max(1, usable_h // self._levels_per_side)
            max_qty = float(np.max(sizes)) if sizes.size > 0 else 0.0
            if max_qty <= 0.0:
                max_qty = 1.0
            for i in range(self._levels_per_side):
                y_top = by0 + header_h + i * row_h
                y_bot = min(by1, y_top + row_h - 1)
                if y_bot < y_top:
                    continue
                price = prices[i]
                qty = float(sizes[i])
                frac = max(0.0, min(1.0, qty / max_qty))
                fill = int(round(frac * bar_w))
                if fill > 0:
                    x_fill_end = min(panel_x1, bar_left + fill)
                    for yy in range(y_top, y_bot + 1):
                        draw_hline(canvas, bar_left, x_fill_end, yy, bar_color)
                draw_text(
                    canvas,
                    panel_x0 + 6,
                    max(0, y_top + 1),
                    f"{price:.4f}" if np.isfinite(price) else "--",
                    label,
                    font_size_px=8.5,
                )
                draw_text(
                    canvas,
                    min(self._width - 80, bar_right + 5),
                    max(0, y_top + 1),
                    f"{qty:.6f}",
                    label,
                    font_size_px=8.5,
                )

        _draw_sideways_distribution(b_x0, b_x1, self._latest_bid_prices, self._latest_bid_sizes_exact, (56, 214, 114, 220))
        _draw_sideways_distribution(c_x0, c_x1, self._latest_ask_prices, self._latest_ask_sizes_exact, (224, 88, 88, 220))
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
