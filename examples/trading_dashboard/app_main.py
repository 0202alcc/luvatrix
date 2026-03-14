from __future__ import annotations

import json
import logging
import os
import queue
import ssl
import threading
import time
import urllib.request
import numpy as np

from examples.trading_dashboard.orderbook_snapshot_client import OrderBookSnapshot, OrderBookSnapshotClient
from luvatrix_plot.compile import compile_full_rewrite_batch
from luvatrix_plot.raster import draw_hline, draw_text, draw_vline, new_canvas, text_size


class _SSEPriceClient:
    """Tiny resilient SSE client that pushes JSON events into a queue."""

    def __init__(self, url: str, *, insecure_tls: bool = False) -> None:
        self._url = url
        self._insecure_tls = bool(insecure_tls)
        self._queue: queue.Queue[tuple[str, dict]] = queue.Queue(maxsize=512)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None
        self.connected = False

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="trading-dashboard-sse", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
        self._thread = None

    def drain(self, limit: int = 256) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        for _ in range(max(1, limit)):
            try:
                out.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return out

    def _push(self, event_type: str, payload: dict) -> None:
        try:
            self._queue.put_nowait((event_type, payload))
        except queue.Full:
            try:
                _ = self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait((event_type, payload))
            except queue.Full:
                pass

    def _run(self) -> None:
        reconnect_s = 0.5
        while not self._stop.is_set():
            try:
                headers = {"Accept": "text/event-stream", "Cache-Control": "no-cache"}
                req = urllib.request.Request(self._url, headers=headers)
                ctx = None
                if self._insecure_tls:
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                with urllib.request.urlopen(req, timeout=30.0, context=ctx) as resp:
                    self.connected = True
                    self.last_error = None
                    reconnect_s = 0.5
                    event_type = "message"
                    data_lines: list[str] = []
                    while not self._stop.is_set():
                        raw = resp.readline()
                        if not raw:
                            break
                        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                        if not line:
                            if data_lines:
                                blob = "\n".join(data_lines)
                                data_lines.clear()
                                try:
                                    payload_obj = json.loads(blob)
                                except json.JSONDecodeError:
                                    payload_obj = {"raw": blob}
                                if isinstance(payload_obj, dict):
                                    self._push(event_type or "message", payload_obj)
                            event_type = "message"
                            continue
                        if line.startswith(":"):
                            continue
                        if line.startswith("event:"):
                            event_type = line.split(":", 1)[1].strip() or "message"
                            continue
                        if line.startswith("data:"):
                            data_lines.append(line.split(":", 1)[1].lstrip())
            except Exception as exc:  # noqa: BLE001 - keep stream alive
                self.last_error = str(exc)
            self.connected = False
            if self._stop.wait(reconnect_s):
                break
            reconnect_s = min(5.0, reconnect_s * 1.6)


class _OrderBookSnapshotFeed:
    """Background HTTP poller for orderbook snapshots."""

    def __init__(self, client: OrderBookSnapshotClient) -> None:
        self._client = client
        self._queue: queue.Queue[OrderBookSnapshot] = queue.Queue(maxsize=64)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None
        self.connected = False

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="trading-dashboard-snapshot", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
        self._thread = None

    def drain(self, limit: int = 64) -> list[OrderBookSnapshot]:
        out: list[OrderBookSnapshot] = []
        for _ in range(max(1, limit)):
            try:
                out.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return out

    def _push(self, snapshot: OrderBookSnapshot) -> None:
        try:
            self._queue.put_nowait(snapshot)
        except queue.Full:
            try:
                _ = self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(snapshot)
            except queue.Full:
                pass

    def _run(self) -> None:
        backoff_sec = self._client.poll_interval_sec
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                snap = self._client.fetch_once()
                self._client._track_staleness(snap)  # noqa: SLF001 - intentional reuse
                self._push(snap)
                self.last_error = None
                self.connected = True
                backoff_sec = self._client.poll_interval_sec
                elapsed = time.monotonic() - started
                wait_s = max(0.0, self._client.poll_interval_sec - elapsed)
                if self._stop.wait(wait_s):
                    break
            except Exception as exc:  # noqa: BLE001 - resilient loop
                self.last_error = str(exc)
                self.connected = False
                transient = self._client._is_transient_error(exc)  # noqa: SLF001 - intentional reuse
                if not transient:
                    if self._stop.wait(min(self._client.max_backoff_sec, 1.0)):
                        break
                    continue
                if self._stop.wait(backoff_sec):
                    break
                backoff_sec = min(self._client.max_backoff_sec, max(0.1, backoff_sec * 2.0))


class TradingDashboardApp:
    """Order-book over time heatmap using incremental rolling bin buffers."""

    def __init__(self) -> None:
        self._logger = logging.getLogger("trading_dashboard")
        self._debug_log = os.getenv("LUVATRIX_ORDERBOOK_DEBUG_LOG", "0").strip().lower() in {"1", "true", "yes"}
        if self._debug_log and not logging.getLogger().handlers:
            logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        self._width = 0
        self._height = 0
        self._source = os.getenv("LUVATRIX_ORDERBOOK_SOURCE", "sim").strip().lower()
        self._snapshot_base_url = os.getenv(
            "LUVATRIX_ORDERBOOK_SNAPSHOT_BASE_URL",
            "https://mgabatangnyc.tail9574b0.ts.net:8443",
        ).strip()
        self._sse_url = os.getenv(
            "LUVATRIX_ORDERBOOK_SSE_URL",
            "https://mgabatangnyc.tail9574b0.ts.net:8443/sse/prices",
        ).strip()
        self._selected_pair = os.getenv("LUVATRIX_ORDERBOOK_PRODUCT", "").strip().upper()
        if self._source == "snapshot" and not self._selected_pair:
            self._selected_pair = "ADA-USD"
        self._active_pair = self._selected_pair or ""
        self._active_quote = self._extract_quote_from_pair(self._active_pair)
        self._seen_pairs: set[str] = set()
        self._last_stream_error = ""
        self._last_stream_event_ts = 0.0
        self._stream_status = "simulated"
        self._latest_stream_spread = np.nan
        self._latest_exchange_ts: int | None = None
        self._last_snapshot_ts: int | None = None
        self._last_snapshot_fingerprint: tuple | None = None
        self._sse = _SSEPriceClient(
            self._sse_url,
            insecure_tls=os.getenv("LUVATRIX_ORDERBOOK_SSE_INSECURE_TLS", "0").strip() in {"1", "true", "yes"},
        )

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
        self._snapshot_levels = max(
            1,
            int(os.getenv("LUVATRIX_ORDERBOOK_SNAPSHOT_LEVELS", str(self._levels_per_side))),
        )
        self._snapshot_poll_interval_sec = max(
            0.2,
            float(os.getenv("LUVATRIX_ORDERBOOK_SNAPSHOT_POLL_INTERVAL_SEC", "1.0")),
        )
        self._snapshot_stale_after_sec = max(
            1.0,
            float(os.getenv("LUVATRIX_ORDERBOOK_SNAPSHOT_STALE_AFTER_SEC", "10.0")),
        )
        self._lock_inferred_tick = os.getenv("LUVATRIX_ORDERBOOK_LOCK_INFERRED_TICK", "1").strip().lower() not in {
            "0",
            "false",
            "no",
        }
        self._inferred_tick_locked = False
        self._inferred_tick_initialized = False

        self._mid_price = float(os.getenv("LUVATRIX_ORDERBOOK_INITIAL_MID", "100.0"))
        self._mid_drift = float(os.getenv("LUVATRIX_ORDERBOOK_DRIFT", "0.12"))
        self._font_scale = 1.5
        # Default to strict ladder fit (no extra pad bins) so Plot A aligns 1:1 with
        # the visible top-N bid/ask orderbook levels unless explicitly overridden.
        self._fit_pad_ticks = max(0.0, float(os.getenv("LUVATRIX_ORDERBOOK_FIT_PAD_TICKS", "0.0")))
        self._gradient_blur_px = max(1, int(os.getenv("LUVATRIX_ORDERBOOK_GRADIENT_BLUR_PX", "3")))
        self._maker_mode = os.getenv("LUVATRIX_ORDERBOOK_MAKER_MODE", "0").strip().lower() in {"1", "true", "yes"}
        self._maker_fee_rate = max(
            0.0,
            float(os.getenv("LUVATRIX_ORDERBOOK_MAKER_FEE_RATE", "0.0")),
        )
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
        self._column_ts = np.full((1,), np.nan, dtype=np.float64)

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
        self._snapshot_client = OrderBookSnapshotClient(
            base_url=self._snapshot_base_url,
            product_id=self._selected_pair or "ADA-USD",
            levels=self._snapshot_levels,
            poll_interval_sec=self._snapshot_poll_interval_sec,
            stale_after_sec=self._snapshot_stale_after_sec,
        )
        self._snapshot_feed = _OrderBookSnapshotFeed(self._snapshot_client)
        self._x_tick_label_h_cache: int | None = None
        self._last_key_debug = ""
        self._keyboard_status = "init"
        self._last_tab_toggle_ns = 0
        self._last_console_stream_meta = ""
        self._mode_badge_rect: tuple[int, int, int, int] | None = None

    def _toggle_mode(self) -> None:
        was_maker = bool(self._maker_mode)
        self._maker_mode = not self._maker_mode
        mode = "maker" if self._maker_mode else "market"
        self._reproject_all_heatmaps_for_mode_change(was_maker=was_maker, is_maker=self._maker_mode)
        self._dbg(f"mode toggle -> {mode}")
        self._recompute_latest_column_for_mode()

    def _reproject_all_heatmaps_for_mode_change(self, *, was_maker: bool, is_maker: bool) -> None:
        if was_maker == is_maker:
            return
        fee = float(max(0.0, self._maker_fee_rate))
        if fee <= 0.0:
            return

        old_bid_factor = float(max(0.0, 1.0 - fee)) if was_maker else 1.0
        old_ask_factor = float(1.0 + fee) if was_maker else 1.0
        new_bid_factor = float(max(0.0, 1.0 - fee)) if is_maker else 1.0
        new_ask_factor = float(1.0 + fee) if is_maker else 1.0
        if old_bid_factor <= 0.0 or old_ask_factor <= 0.0:
            return

        bid_ratio = new_bid_factor / old_bid_factor
        ask_ratio = new_ask_factor / old_ask_factor

        self._bid_heatmap = self._remap_heatmap_rows(self._bid_heatmap, self._price_min, bid_ratio)
        self._ask_heatmap = self._remap_heatmap_rows(self._ask_heatmap, self._price_min, ask_ratio)
        self._global_bid_heatmap = self._remap_heatmap_rows(self._global_bid_heatmap, self._global_price_min, bid_ratio)
        self._global_ask_heatmap = self._remap_heatmap_rows(self._global_ask_heatmap, self._global_price_min, ask_ratio)

    def _remap_heatmap_rows(self, heatmap: np.ndarray, price_min: float, ratio: float) -> np.ndarray:
        if heatmap.ndim != 2:
            return heatmap
        rows, _cols = heatmap.shape
        if rows <= 0 or abs(ratio - 1.0) < 1e-12:
            return heatmap

        out = np.zeros_like(heatmap)
        for src_row in range(rows):
            p = float(price_min) + (float(src_row) + 0.5) * self._tick_size
            mapped_p = p * float(ratio)
            target = ((mapped_p - float(price_min)) / self._tick_size) - 0.5
            i0 = int(np.floor(target))
            w1 = float(target - i0)
            w0 = 1.0 - w1
            if 0 <= i0 < rows:
                out[i0, :] += heatmap[src_row, :] * w0
            i1 = i0 + 1
            if 0 <= i1 < rows:
                out[i1, :] += heatmap[src_row, :] * w1
        return out

    def _recompute_latest_column_for_mode(self) -> None:
        bid_prices = self._latest_bid_prices.copy()
        ask_prices = self._latest_ask_prices.copy()
        if not np.isfinite(bid_prices).any() or not np.isfinite(ask_prices).any():
            return
        bid_sizes = self._latest_bid_sizes_exact.copy()
        ask_sizes = self._latest_ask_sizes_exact.copy()
        bid_norm = bid_sizes.copy()
        ask_norm = ask_sizes.copy()
        bmx = float(np.max(bid_norm)) if bid_norm.size else 0.0
        amx = float(np.max(ask_norm)) if ask_norm.size else 0.0
        if bmx > 0.0:
            bid_norm /= bmx
        if amx > 0.0:
            ask_norm /= amx
        lowest_bid = float(np.nanmin(bid_prices))
        highest_ask = float(np.nanmax(ask_prices))
        # Replace current column in-place so mode change is visible immediately.
        self._push_distribution_column(
            bid_prices,
            bid_norm,
            ask_prices,
            ask_norm,
            lowest_bid,
            highest_ask,
            roll_column=False,
            roll_steps=0,
            write_steps=max(1, self._columns_per_second()),
        )

    def _poll_keyboard_toggles(self, events: list[object]) -> None:
        self._keyboard_status = f"events:{len(events)}"
        for event in events:
            device = str(getattr(event, "device", "")).strip().lower()
            if "keyboard" not in device:
                continue
            if getattr(event, "status", None) != "OK":
                self._keyboard_status = f"status:{getattr(event, 'status', '--')}"
                continue
            event_type = str(getattr(event, "event_type", "")).strip().lower()
            if event_type and event_type not in {"press", "key_down", "keydown"}:
                continue
            payload = getattr(event, "payload", None)
            if not isinstance(payload, dict):
                continue
            phase = str(payload.get("phase", "")).strip().lower()
            if phase and phase not in {"down", "single", "repeat", "up"}:
                continue
            raw_key = str(payload.get("key", ""))
            key = raw_key.lower()
            code_raw = payload.get("code")
            try:
                code_int = int(code_raw) if code_raw is not None else None
            except (TypeError, ValueError):
                code_int = None
            active_keys = payload.get("active_keys")
            self._last_key_debug = (
                f"type={event_type or '--'} key={key or '--'} phase={phase or '--'} "
                f"code={code_int if code_int is not None else code_raw if code_raw is not None else '--'}"
            )
            self._keyboard_status = "ok"
            self._dbg(f"keyboard event {self._last_key_debug}")
            is_tab = (
                raw_key in {"\t"}
                or key in {"tab", "\\t", "⇥"}
                or code_int in {48, 9}
            )
            if not is_tab:
                continue
            if phase in {"up", "cancel", "repeat"}:
                continue
            if phase and phase not in {"single"}:
                continue
            now_ns = time.time_ns()
            if now_ns - self._last_tab_toggle_ns < 120_000_000:
                continue
            self._last_tab_toggle_ns = now_ns
            self._toggle_mode()

    def _poll_pointer_toggle(self, events: list[object]) -> None:
        rect = self._mode_badge_rect
        if rect is None:
            return
        x0, y0, x1, y1 = rect
        for event in events:
            device = str(getattr(event, "device", "")).strip().lower()
            if device not in {"mouse", "trackpad"}:
                continue
            event_type = str(getattr(event, "event_type", "")).strip().lower()
            if event_type not in {"click", "tap"}:
                continue
            payload = getattr(event, "payload", None)
            if not isinstance(payload, dict):
                continue
            phase = str(payload.get("phase", "")).strip().lower()
            if phase and phase not in {"down", "single"}:
                continue
            x = payload.get("x")
            y = payload.get("y")
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                continue
            inside = (x0 <= int(x) <= x1) and (y0 <= int(y) <= y1)
            if not inside:
                continue
            now_ns = time.time_ns()
            if now_ns - self._last_tab_toggle_ns < 120_000_000:
                continue
            self._last_tab_toggle_ns = now_ns
            self._toggle_mode()
            self._dbg(f"mode toggle pointer={device}:{event_type}")
            break

    def _dbg(self, message: str) -> None:
        if self._debug_log:
            self._logger.info(message)

    def _emit_console_stream_meta(self) -> None:
        if self._source not in {"sse", "snapshot"}:
            return
        pair = self._active_pair or self._selected_pair or "--"
        seen_count = len(self._seen_pairs)
        msg = f"[trading-dashboard] pair={pair} source={self._source} seen={seen_count}"
        if msg == self._last_console_stream_meta:
            return
        self._last_console_stream_meta = msg
        print(msg)

    def _emit_console_snapshot_book(
        self,
        *,
        snapshot: OrderBookSnapshot,
        bid_prices: np.ndarray,
        bid_sizes: np.ndarray,
        ask_prices: np.ndarray,
        ask_sizes: np.ndarray,
    ) -> None:
        def _fmt_px(v: float) -> str:
            return self._format_price_axis(v) if np.isfinite(v) else "--"

        def _fmt_qty(v: float) -> str:
            if not np.isfinite(v):
                return "--"
            av = abs(v)
            if av >= 1e6:
                return self._format_scientific(v, 4)
            return self._format_fixed(v, 3)

        def _side_line(prices: np.ndarray, sizes: np.ndarray) -> str:
            parts: list[str] = []
            n = min(self._levels_per_side, prices.shape[0], sizes.shape[0])
            for i in range(n):
                p = float(prices[i])
                q = float(sizes[i])
                if not np.isfinite(p):
                    continue
                parts.append(f"{_fmt_px(p)}@{_fmt_qty(q)}")
            return " | ".join(parts) if parts else "--"

        ts_txt = str(snapshot.timestamp) if snapshot.timestamp is not None else "null"
        spread = snapshot.spread
        spread_txt = self._format_price_axis(float(spread)) if spread is not None else "--"
        best_bid = float(np.nanmax(bid_prices)) if np.isfinite(bid_prices).any() else np.nan
        best_ask = float(np.nanmin(ask_prices)) if np.isfinite(ask_prices).any() else np.nan
        best_txt = f"best_bid={_fmt_px(best_bid)} best_ask={_fmt_px(best_ask)}"
        print(f"[orderbook] pair={snapshot.product_id} ts={ts_txt} spread={spread_txt} {best_txt}")
        print(f"[orderbook] bids: {_side_line(bid_prices, bid_sizes)}")
        print(f"[orderbook] asks: {_side_line(ask_prices, ask_sizes)}")

    def _fs(self, px: float) -> float:
        return float(px) * float(self._font_scale)

    def _price_label_decimals(self) -> int:
        if self._tick_size <= 0:
            return 6
        return max(4, min(12, int(np.ceil(-np.log10(self._tick_size))) + 1))

    def _spread_label_decimals(self) -> int:
        return max(8, min(14, self._price_label_decimals() + 2))

    def _price_sig_digits(self) -> int:
        if self._tick_size <= 0:
            return 6
        return max(3, min(12, int(np.ceil(-np.log10(self._tick_size))) + 2))

    def _snap_to_tick(self, value: float) -> float:
        if self._tick_size <= 0.0 or not np.isfinite(value):
            return float(value)
        ticks = float(value) / float(self._tick_size)
        snapped_ticks = np.floor(ticks + 0.5 + 1e-12)
        return float(snapped_ticks * self._tick_size)

    def _bin_index_for_price(self, price: float) -> int:
        if self._tick_size <= 0.0 or not np.isfinite(price):
            return -1
        ticks = (float(price) - float(self._price_min)) / float(self._tick_size)
        return int(np.floor(ticks + 0.5 + 1e-12))

    def _format_price_axis(self, value: float) -> str:
        if not np.isfinite(value):
            return "--"
        if value != 0.0 and abs(value) < 1e-5:
            return self._format_scientific(value, self._price_sig_digits())
        return self._format_fixed(value, self._price_label_decimals())

    @staticmethod
    def _format_scientific(value: float, sig_digits: int = 2) -> str:
        if not np.isfinite(value):
            return "--"
        if value == 0.0:
            return "0.0E0"
        precision = max(1, int(sig_digits))
        s = f"{value:.{precision - 1}E}"
        mantissa, exp = s.split("E")
        if "." in mantissa:
            mantissa = mantissa.rstrip("0").rstrip(".")
        if mantissa in {"-0", ""}:
            mantissa = "0"
        if "." not in mantissa:
            mantissa = f"{mantissa}.0"
        exp_i = int(exp)
        return f"{mantissa}E{exp_i}"

    @staticmethod
    def _format_fixed(value: float, decimals: int) -> str:
        if not np.isfinite(value):
            return "--"
        txt = f"{value:.{max(0, int(decimals))}f}"
        if "." in txt:
            txt = txt.rstrip("0").rstrip(".")
        if txt in {"-0", "-0.0", ""}:
            return "0"
        return txt

    def _infer_tick_size_from_books(self, bid_prices: np.ndarray, ask_prices: np.ndarray) -> float | None:
        vals = np.concatenate((bid_prices[np.isfinite(bid_prices)], ask_prices[np.isfinite(ask_prices)]))
        if vals.size < 2:
            return None
        uniq = np.unique(np.round(vals.astype(np.float64), 12))
        if uniq.size < 2:
            return None
        diffs = np.diff(np.sort(uniq))
        diffs = diffs[diffs > 0]
        if diffs.size == 0:
            return None
        tick = float(np.min(diffs))
        if not np.isfinite(tick) or tick <= 0.0:
            return None
        return tick

    def _apply_tick_size(self, tick: float) -> None:
        if not np.isfinite(tick) or tick <= 0.0:
            return
        old_tick = float(self._tick_size)
        rel = abs(tick - old_tick) / max(old_tick, 1e-12)
        if rel < 0.01:
            return
        self._dbg(f"tick-size reset old={old_tick:.12g} new={tick:.12g} rel={rel:.4f} plot_w={self._plot_w}")
        self._tick_size = float(tick)
        self._global_price_min = self._mid_price - 0.5 * float(self._global_bin_count) * self._tick_size
        self._global_price_max = self._global_price_min + float(self._global_bin_count) * self._tick_size
        self._bid_heatmap = np.zeros((self._bin_count, self._plot_w), dtype=np.float32)
        self._ask_heatmap = np.zeros((self._bin_count, self._plot_w), dtype=np.float32)
        self._global_bid_heatmap = np.zeros((self._global_bin_count, self._plot_w), dtype=np.float32)
        self._global_ask_heatmap = np.zeros((self._global_bin_count, self._plot_w), dtype=np.float32)

    def _maybe_apply_inferred_tick(self, inferred_tick: float | None) -> None:
        if inferred_tick is None:
            return
        if self._source != "snapshot":
            self._apply_tick_size(inferred_tick)
            return
        # Snapshot mode: infer tick once, then keep it fixed to prevent history resets.
        if self._inferred_tick_initialized:
            return
        # Once we have any rendered history, keep the tick ruler stable to avoid visual resets.
        if np.any(self._bid_heatmap > 0.0) or np.any(self._ask_heatmap > 0.0):
            self._inferred_tick_locked = True
            self._inferred_tick_initialized = True
            return
        if self._lock_inferred_tick and self._inferred_tick_locked:
            return
        self._apply_tick_size(inferred_tick)
        self._inferred_tick_initialized = True
        if self._lock_inferred_tick:
            self._inferred_tick_locked = True
        self._dbg(f"inferred tick initialized={self._inferred_tick_initialized} locked={self._inferred_tick_locked} tick={self._tick_size:.12g}")

    @staticmethod
    def _coerce_float(value: object) -> float | None:
        try:
            out = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        if not np.isfinite(out):
            return None
        return out

    @staticmethod
    def _extract_pair(payload: dict) -> str:
        for key in ("product_id", "product", "symbol", "pair", "instrument"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().upper()
        return ""

    @staticmethod
    def _extract_quote_from_pair(pair: str) -> str:
        pair_norm = (pair or "").strip().upper()
        if not pair_norm:
            return "QUOTE"
        if "-" in pair_norm:
            parts = pair_norm.split("-", 1)
            if len(parts) == 2 and parts[1]:
                return parts[1]
        if "/" in pair_norm:
            parts = pair_norm.split("/", 1)
            if len(parts) == 2 and parts[1]:
                return parts[1]
        return "QUOTE"

    def _extract_side_levels(
        self,
        side_raw: object,
        *,
        side_name: str,
    ) -> tuple[np.ndarray, np.ndarray]:
        prices = np.full(self._levels_per_side, np.nan, dtype=np.float64)
        sizes = np.zeros(self._levels_per_side, dtype=np.float32)
        if not isinstance(side_raw, list):
            return prices, sizes
        idx = 0
        for item in side_raw:
            if idx >= self._levels_per_side:
                break
            price_val: float | None = None
            size_val: float | None = None
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                price_val = self._coerce_float(item[0])
                size_val = self._coerce_float(item[1])
            elif isinstance(item, dict):
                price_val = self._coerce_float(item.get("price"))
                if size_val is None:
                    size_val = self._coerce_float(item.get("size"))
                if size_val is None:
                    size_val = self._coerce_float(item.get("qty"))
                if size_val is None:
                    size_val = self._coerce_float(item.get("quantity"))
            if price_val is None:
                continue
            if size_val is None:
                size_val = 0.0
            prices[idx] = float(price_val)
            sizes[idx] = max(0.0, float(size_val))
            idx += 1
        if idx == 0:
            return prices, sizes
        valid = np.isfinite(prices)
        sort_idx = np.argsort(prices[valid])
        sorted_prices = prices[valid][sort_idx]
        sorted_sizes = sizes[valid][sort_idx]
        if side_name == "bid":
            sorted_prices = sorted_prices[::-1]
            sorted_sizes = sorted_sizes[::-1]
        prices[:] = np.nan
        sizes[:] = 0.0
        n = min(self._levels_per_side, sorted_prices.shape[0])
        prices[:n] = sorted_prices[:n]
        sizes[:n] = sorted_sizes[:n]
        return prices, sizes

    def _synthesize_levels_from_mid(
        self,
        mid_price: float,
        spread: float,
        bid_hint: float | None,
        ask_hint: float | None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        bid_prices = np.full(self._levels_per_side, np.nan, dtype=np.float64)
        ask_prices = np.full(self._levels_per_side, np.nan, dtype=np.float64)
        bid_sizes = np.zeros(self._levels_per_side, dtype=np.float32)
        ask_sizes = np.zeros(self._levels_per_side, dtype=np.float32)
        bid_base = bid_hint if bid_hint is not None else (mid_price - 0.5 * spread)
        ask_base = ask_hint if ask_hint is not None else (mid_price + 0.5 * spread)
        for i in range(self._levels_per_side):
            bid_prices[i] = float(bid_base - i * self._tick_size)
            ask_prices[i] = float(ask_base + i * self._tick_size)
        decay = np.exp(-np.arange(self._levels_per_side, dtype=np.float64) / 7.0).astype(np.float32)
        bid_sizes[:] = decay
        ask_sizes[:] = decay
        return bid_prices, bid_sizes, ask_prices, ask_sizes

    def _apply_live_payload(self, payload: dict) -> bool:
        pair = self._extract_pair(payload)
        if pair:
            self._seen_pairs.add(pair)
            if self._selected_pair:
                if pair == self._selected_pair:
                    self._active_pair = self._selected_pair
                elif self._selected_pair in self._seen_pairs:
                    return False
                elif not self._active_pair:
                    # Requested pair has not appeared yet; fall back to a live pair.
                    self._active_pair = pair
                elif pair != self._active_pair:
                    return False
            else:
                if not self._active_pair:
                    self._active_pair = pair
                if self._active_pair and pair != self._active_pair:
                    return False
            if self._active_pair:
                self._active_quote = self._extract_quote_from_pair(self._active_pair)

        bids_raw = payload.get("bids")
        asks_raw = payload.get("asks")
        bid_prices, bid_sizes_exact = self._extract_side_levels(bids_raw, side_name="bid")
        ask_prices, ask_sizes_exact = self._extract_side_levels(asks_raw, side_name="ask")
        has_book = bool(np.isfinite(bid_prices).any() and np.isfinite(ask_prices).any())

        best_bid = self._coerce_float(payload.get("best_bid"))
        if best_bid is None:
            best_bid = self._coerce_float(payload.get("bid"))
        best_ask = self._coerce_float(payload.get("best_ask"))
        if best_ask is None:
            best_ask = self._coerce_float(payload.get("ask"))
        last_price = self._coerce_float(payload.get("price"))
        if last_price is None:
            last_price = self._coerce_float(payload.get("last_price"))
        ts_raw = payload.get("timestamp")
        if isinstance(ts_raw, (int, float)):
            self._latest_exchange_ts = int(ts_raw)
        spread = self._coerce_float(payload.get("spread"))
        display_spread = spread
        if display_spread is None and best_bid is not None and best_ask is not None:
            display_spread = float(best_ask - best_bid)
        if display_spread is not None:
            self._latest_stream_spread = float(display_spread)

        synth_spread = spread if spread is not None else self._tick_size
        synth_spread = max(self._tick_size, float(synth_spread))

        if not has_book:
            if best_bid is None and best_ask is not None:
                best_bid = float(best_ask - spread)
            if best_ask is None and best_bid is not None:
                best_ask = float(best_bid + spread)
            if last_price is None:
                if best_bid is not None and best_ask is not None:
                    last_price = 0.5 * (best_bid + best_ask)
                elif best_bid is not None:
                    last_price = best_bid + 0.5 * spread
                elif best_ask is not None:
                    last_price = best_ask - 0.5 * spread
                else:
                    last_price = self._mid_price
            bid_prices, bid_sizes_exact, ask_prices, ask_sizes_exact = self._synthesize_levels_from_mid(
                float(last_price),
                synth_spread,
                best_bid,
                best_ask,
            )
            has_book = True

        if not has_book:
            return False

        self._mid_price = float(last_price) if last_price is not None else self._mid_price
        self._latest_bid_prices = bid_prices.copy()
        self._latest_ask_prices = ask_prices.copy()
        self._latest_bid_sizes_exact = bid_sizes_exact.copy()
        self._latest_ask_sizes_exact = ask_sizes_exact.copy()

        bid_norm = bid_sizes_exact.copy()
        ask_norm = ask_sizes_exact.copy()
        bmx = float(np.max(bid_norm)) if bid_norm.size > 0 else 0.0
        amx = float(np.max(ask_norm)) if ask_norm.size > 0 else 0.0
        if bmx > 0.0:
            bid_norm /= bmx
        if amx > 0.0:
            ask_norm /= amx

        lowest_bid = float(np.nanmin(bid_prices))
        highest_ask = float(np.nanmax(ask_prices))
        self._latest_lowest_bid = lowest_bid
        self._latest_highest_ask = highest_ask
        self._push_distribution_column(
            bid_prices,
            bid_norm,
            ask_prices,
            ask_norm,
            lowest_bid,
            highest_ask,
            roll_steps=0,
        )
        self._last_stream_event_ts = time.time()
        return True

    def _apply_snapshot(self, snapshot: OrderBookSnapshot) -> bool:
        self._seen_pairs.add(snapshot.product_id)
        pair_changed = bool(self._active_pair and snapshot.product_id != self._active_pair)
        self._active_pair = snapshot.product_id
        self._active_quote = self._extract_quote_from_pair(snapshot.product_id)
        if pair_changed and self._lock_inferred_tick:
            self._inferred_tick_locked = False
            self._inferred_tick_initialized = False

        if not snapshot.bids or not snapshot.asks:
            return False

        bid_prices = np.full(self._levels_per_side, np.nan, dtype=np.float64)
        ask_prices = np.full(self._levels_per_side, np.nan, dtype=np.float64)
        bid_sizes_exact = np.zeros(self._levels_per_side, dtype=np.float32)
        ask_sizes_exact = np.zeros(self._levels_per_side, dtype=np.float32)

        b_n = min(self._levels_per_side, len(snapshot.bids))
        a_n = min(self._levels_per_side, len(snapshot.asks))
        for i in range(b_n):
            bid_prices[i] = float(snapshot.bids[i].price)
            bid_sizes_exact[i] = max(0.0, float(snapshot.bids[i].size))
        for i in range(a_n):
            ask_prices[i] = float(snapshot.asks[i].price)
            ask_sizes_exact[i] = max(0.0, float(snapshot.asks[i].size))

        fingerprint = (
            tuple(float(v) if np.isfinite(v) else np.nan for v in bid_prices),
            tuple(float(v) for v in bid_sizes_exact),
            tuple(float(v) if np.isfinite(v) else np.nan for v in ask_prices),
            tuple(float(v) for v in ask_sizes_exact),
        )
        same_ts = snapshot.timestamp is not None and snapshot.timestamp == self._last_snapshot_ts
        replace_latest_column = bool(same_ts)
        ts = snapshot.timestamp
        if ts is None:
            roll_steps = 1
        elif self._last_snapshot_ts is None:
            roll_steps = 1
        elif ts == self._last_snapshot_ts:
            roll_steps = 0
        elif ts > self._last_snapshot_ts:
            roll_steps = int(ts - self._last_snapshot_ts)
        else:
            # Out-of-order timestamp: overwrite latest column instead of rolling backward.
            roll_steps = 0
        sec_cols = self._columns_per_second()
        roll_cols = int(max(0, roll_steps)) * sec_cols
        self._dbg(
            f"snapshot apply pair={snapshot.product_id} ts={snapshot.timestamp} last_ts={self._last_snapshot_ts} "
            f"same_ts={same_ts} replace={replace_latest_column} roll_steps={roll_steps}"
        )

        inferred_tick = self._infer_tick_size_from_books(bid_prices, ask_prices)
        if inferred_tick is not None:
            self._maybe_apply_inferred_tick(inferred_tick)

        bid_norm = bid_sizes_exact.copy()
        ask_norm = ask_sizes_exact.copy()
        bmx = float(np.max(bid_norm)) if b_n > 0 else 0.0
        amx = float(np.max(ask_norm)) if a_n > 0 else 0.0
        if bmx > 0.0:
            bid_norm /= bmx
        if amx > 0.0:
            ask_norm /= amx

        self._latest_bid_prices = bid_prices.copy()
        self._latest_bid_sizes_exact = bid_sizes_exact.copy()
        self._latest_ask_prices = ask_prices.copy()
        self._latest_ask_sizes_exact = ask_sizes_exact.copy()
        self._latest_stream_spread = float(snapshot.spread) if snapshot.spread is not None else np.nan
        if snapshot.timestamp is not None:
            self._latest_exchange_ts = int(snapshot.timestamp)
        self._emit_console_snapshot_book(
            snapshot=snapshot,
            bid_prices=bid_prices,
            bid_sizes=bid_sizes_exact,
            ask_prices=ask_prices,
            ask_sizes=ask_sizes_exact,
        )

        lowest_bid = float(np.nanmin(bid_prices))
        highest_ask = float(np.nanmax(ask_prices))
        self._latest_lowest_bid = lowest_bid
        self._latest_highest_ask = highest_ask
        self._push_distribution_column(
            bid_prices,
            bid_norm,
            ask_prices,
            ask_norm,
            lowest_bid,
            highest_ask,
            roll_column=False,
            roll_steps=roll_cols,
            write_steps=sec_cols,
        )
        if snapshot.timestamp is not None:
            self._last_snapshot_ts = int(snapshot.timestamp)
        self._last_snapshot_fingerprint = fingerprint
        self._last_stream_event_ts = time.time()
        return True

    def _layout(self) -> tuple[int, int, int, int, int, int, int, int, int]:
        left, right, top, bottom = 84, 112, 28, 34
        x0, y0 = left, top
        pw = max(8, self._width - left - right)
        total_h = max(24, self._height - top - bottom)
        gap = max(22, min(44, int(round(total_h * 0.16))))
        if self._source in {"sse", "snapshot"}:
            # Reserve enough vertical divider space for rotated timestamp tick labels.
            # Math: tick label offset + rotated labels + spacing + x-title + safety + extra B/C drop.
            required_gap = 8 + self._x_tick_label_height_px() + 4 + self._x_title_height_px() + 16
            gap = max(gap, required_gap)
        bars_h = max(8, min(total_h // 2, int(round(total_h * 0.29))))
        heat_h = max(8, total_h - bars_h - gap)
        if heat_h + bars_h + gap > total_h:
            bars_h = max(8, total_h - heat_h - gap)
        if heat_h + bars_h + gap > total_h:
            gap = max(0, total_h - heat_h - bars_h)
        bars_y0 = y0 + heat_h + gap
        return x0, y0, pw, heat_h, x0, bars_y0, pw, bars_h, gap

    @staticmethod
    def _x_tick_rotate_deg() -> int:
        return 65

    def _x_tick_label_height_px(self) -> int:
        if self._x_tick_label_h_cache is None:
            # Keep layout stable across frames by using a fixed worst-case sample label.
            # Using all '8's approximates max glyph height/footprint for bitmap text.
            sample = "8888888888"
            _w, h = text_size(sample, font_size_px=self._fs(9.0), rotate_deg=self._x_tick_rotate_deg())
            self._x_tick_label_h_cache = int(max(1, h))
        return int(self._x_tick_label_h_cache)

    def _x_title_height_px(self) -> int:
        _w, h = text_size("time (s, recent -> right)", font_size_px=self._fs(8.0))
        return int(max(1, h))

    def _columns_per_second(self) -> int:
        if self._time_window_sec <= 0:
            return 1
        return max(1, int(round(float(self._plot_w) / float(self._time_window_sec))))

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
        self._dbg(f"buffer resize/reinit plot=({pw}x{ph}) bars=({bw}x{bh})")
        self._bid_heatmap = np.zeros((self._bin_count, pw), dtype=np.float32)
        self._ask_heatmap = np.zeros((self._bin_count, pw), dtype=np.float32)
        self._global_bid_heatmap = np.zeros((self._global_bin_count, pw), dtype=np.float32)
        self._global_ask_heatmap = np.zeros((self._global_bin_count, pw), dtype=np.float32)
        self._column_ts = np.full((pw,), np.nan, dtype=np.float64)

    def _fit_price_window_to_book(self, lowest_bid: float, highest_ask: float) -> None:
        target_range = float(self._bin_count) * self._tick_size
        observed_range = max(0.0, float(highest_ask - lowest_bid))
        _ = observed_range
        # Strict order-book anchoring: map bins as an ordered ladder from the live book,
        # not a center-fitted window. This avoids half-spare phase shifts that can look
        # like a persistent one-bin y-axis offset.
        lo = float(lowest_bid)
        lo = self._snap_to_tick(lo)
        self._price_min = lo
        self._price_max = lo + target_range

    def _ensure_global_range_for_local(self) -> None:
        if self._price_min >= self._global_price_min and self._price_max <= self._global_price_max:
            return
        offset_bins = max(0, (self._global_bin_count - self._bin_count) // 2)
        target_min = self._price_min - float(offset_bins) * self._tick_size
        target_min = self._snap_to_tick(target_min)
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
            idx = self._bin_index_for_price(float(price))
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
        *,
        roll_column: bool = True,
        roll_steps: int = 1,
        write_steps: int = 1,
    ) -> None:
        self._ensure_heatmap_buffers()
        plot_bid_prices = bid_prices.copy()
        plot_ask_prices = ask_prices.copy()
        if self._maker_mode and self._maker_fee_rate > 0.0:
            bid_factor = float(max(0.0, 1.0 - self._maker_fee_rate))
            ask_factor = float(1.0 + self._maker_fee_rate)
            bid_mask = np.isfinite(plot_bid_prices)
            ask_mask = np.isfinite(plot_ask_prices)
            plot_bid_prices[bid_mask] = plot_bid_prices[bid_mask] * bid_factor
            plot_ask_prices[ask_mask] = plot_ask_prices[ask_mask] * ask_factor

        old_min = self._price_min
        old_max = self._price_max
        # Keep y-axis ruler anchored to market prices regardless of mode.
        self._fit_price_window_to_book(float(lowest_bid), float(highest_ask))
        local_shifted = abs(self._price_min - old_min) > 0.5 * self._tick_size
        if local_shifted:
            self._shift_heatmap_vertical(old_min, old_max, self._price_min, self._price_max)
        self._ensure_global_range_for_local()

        bid_col = self._build_side_column(plot_bid_prices, bid_sizes)
        ask_col = self._build_side_column(plot_ask_prices, ask_sizes)

        if roll_column:
            self._bid_heatmap = np.roll(self._bid_heatmap, -1, axis=1)
            self._ask_heatmap = np.roll(self._ask_heatmap, -1, axis=1)
            self._column_ts = np.roll(self._column_ts, -1, axis=0)
            self._column_ts[-1:] = np.nan
        steps = max(0, int(roll_steps))
        if steps > 1:
            self._dbg(f"multi-roll steps={steps} roll_column={roll_column} ts={self._latest_exchange_ts}")
        if steps > 0:
            steps = min(steps, self._plot_w)
            self._bid_heatmap = np.roll(self._bid_heatmap, -steps, axis=1)
            self._ask_heatmap = np.roll(self._ask_heatmap, -steps, axis=1)
            self._bid_heatmap[:, -steps:] = 0.0
            self._ask_heatmap[:, -steps:] = 0.0
            self._column_ts = np.roll(self._column_ts, -steps, axis=0)
            self._column_ts[-steps:] = np.nan
        write_cols = max(1, int(write_steps))
        write_cols = min(write_cols, self._plot_w)
        self._bid_heatmap[:, -write_cols:] = bid_col[:, None]
        self._ask_heatmap[:, -write_cols:] = ask_col[:, None]
        ts_val = float(self._latest_exchange_ts) if self._latest_exchange_ts is not None else np.nan
        self._column_ts[-write_cols:] = ts_val

        if roll_column:
            self._global_bid_heatmap = np.roll(self._global_bid_heatmap, -1, axis=1)
            self._global_ask_heatmap = np.roll(self._global_ask_heatmap, -1, axis=1)
        if steps > 0:
            self._global_bid_heatmap = np.roll(self._global_bid_heatmap, -steps, axis=1)
            self._global_ask_heatmap = np.roll(self._global_ask_heatmap, -steps, axis=1)
            self._global_bid_heatmap[:, -steps:] = 0.0
            self._global_ask_heatmap[:, -steps:] = 0.0
        self._global_bid_heatmap[:, -write_cols:] = 0.0
        self._global_ask_heatmap[:, -write_cols:] = 0.0

        offset = int(round((self._price_min - self._global_price_min) / self._tick_size))
        g0 = max(0, offset)
        g1 = min(self._global_bin_count, offset + self._bin_count)
        if g1 > g0:
            l0 = max(0, -offset)
            l1 = l0 + (g1 - g0)
            self._global_bid_heatmap[g0:g1, -write_cols:] = bid_col[l0:l1][:, None]
            self._global_ask_heatmap[g0:g1, -write_cols:] = ask_col[l0:l1][:, None]

        if local_shifted:
            self._rehydrate_local_from_global()

    def _step_market(self, dt: float) -> bool:
        if self._source == "sse":
            updated = False
            events = self._sse.drain(limit=512)
            if self._sse.last_error:
                self._last_stream_error = self._sse.last_error
            for event_type, payload in events:
                if event_type == "error":
                    msg = payload.get("message") if isinstance(payload, dict) else None
                    if isinstance(msg, str) and msg.strip():
                        self._last_stream_error = msg.strip()
                    continue
                price_batch = payload.get("prices") if isinstance(payload, dict) else None
                if isinstance(price_batch, list):
                    for item in price_batch:
                        if isinstance(item, dict) and self._apply_live_payload(item):
                            updated = True
                    continue
                if isinstance(payload, dict) and self._apply_live_payload(payload):
                    updated = True
            self._stream_status = "connected" if self._sse.connected else "connecting"
            return updated
        if self._source == "snapshot":
            updated = False
            snaps = self._snapshot_feed.drain(limit=64)
            if self._snapshot_feed.last_error:
                self._last_stream_error = self._snapshot_feed.last_error
                self._dbg(f"snapshot feed error: {self._last_stream_error}")
            if snaps and self._debug_log:
                self._dbg(f"snapshot drain count={len(snaps)}")
            for snap in snaps:
                if self._apply_snapshot(snap):
                    updated = True
            self._stream_status = "connected" if self._snapshot_feed.connected else "connecting"
            return updated

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
        self._push_distribution_column(
            bid_prices,
            bid_sizes,
            ask_prices,
            ask_sizes,
            lowest_bid,
            highest_ask,
            roll_steps=0,
        )
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
        if self._maker_mode:
            bid_color = np.array([88, 162, 242], dtype=np.float32).reshape(1, 1, 3)  # blue
            ask_color = np.array([242, 148, 72], dtype=np.float32).reshape(1, 1, 3)  # orange
        else:
            bid_color = np.array([45, 220, 95], dtype=np.float32).reshape(1, 1, 3)  # green
            ask_color = np.array([230, 70, 70], dtype=np.float32).reshape(1, 1, 3)  # red
        rgb = base + (bid_img[:, :, None] * bid_color) + (ask_img[:, :, None] * ask_color)
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)

        # Peak-bin borders per timestamp-column: compute strongest bin independently
        # for each displayed column from the corresponding heatmap source column.
        bid_peak = np.zeros((ph, pw), dtype=bool)
        ask_peak = np.zeros((ph, pw), dtype=bool)
        border_px = 3

        for xx in range(pw):
            src_col = int(src_idx[xx])
            if 0 <= src_col < visible_cols:
                bcol = bid_bins[:, src_col]
                bmx = float(np.max(bcol))
            else:
                bcol = None
                bmx = 0.0
            if bmx > 0.0 and bcol is not None:
                bbin = int(np.argmax(bcol))
                b_row_start = ph - int(round((bbin + 1) * ph / self._bin_count))
                b_row_end = ph - int(round(bbin * ph / self._bin_count)) - 1
                b_row_start = max(0, min(ph - 1, b_row_start))
                b_row_end = max(0, min(ph - 1, b_row_end))
                top_end = min(ph - 1, b_row_start + border_px - 1)
                bot_start = max(0, b_row_end - border_px + 1)
                bid_peak[b_row_start : top_end + 1, xx] = True
                bid_peak[bot_start : b_row_end + 1, xx] = True

            if 0 <= src_col < visible_cols:
                acol = ask_bins[:, src_col]
                amx = float(np.max(acol))
            else:
                acol = None
                amx = 0.0
            if amx > 0.0 and acol is not None:
                abin = int(np.argmax(acol))
                a_row_start = ph - int(round((abin + 1) * ph / self._bin_count))
                a_row_end = ph - int(round(abin * ph / self._bin_count)) - 1
                a_row_start = max(0, min(ph - 1, a_row_start))
                a_row_end = max(0, min(ph - 1, a_row_end))
                top_end = min(ph - 1, a_row_start + border_px - 1)
                bot_start = max(0, a_row_end - border_px + 1)
                ask_peak[a_row_start : top_end + 1, xx] = True
                ask_peak[bot_start : a_row_end + 1, xx] = True

        if np.any(bid_peak) or np.any(ask_peak):
            rgb_f = rgb.astype(np.float32)
            bid_dark = (bid_color.reshape(3) * 0.42).astype(np.float32)
            ask_dark = (ask_color.reshape(3) * 0.42).astype(np.float32)
            if np.any(bid_peak):
                rgb_f[bid_peak] = (0.35 * rgb_f[bid_peak]) + (0.65 * bid_dark)
            if np.any(ask_peak):
                rgb_f[ask_peak] = (0.35 * rgb_f[ask_peak]) + (0.65 * ask_dark)
            rgb = np.clip(rgb_f, 0, 255).astype(np.uint8)

        # Time-second cadence tint: 2 normal second-bins, then 1 slightly lighter blue second-bin.
        # Anchor to absolute second (when available) so stripes roll with the timeline/data.
        if self._display_window_sec > 1:
            x = np.arange(pw, dtype=np.float32)
            secs_ago = ((pw - 1 - x) * float(self._display_window_sec) / float(pw - 1)).astype(np.int32)
            secs_ago = np.clip(secs_ago, 0, self._display_window_sec - 1)
        else:
            secs_ago = np.zeros((pw,), dtype=np.int32)
        if self._latest_exchange_ts is not None and self._source in {"snapshot", "sse"}:
            col_ts = int(self._latest_exchange_ts) - secs_ago
            stripe_mask = (col_ts % 3) == 2
        else:
            stripe_mask = (secs_ago % 3) == 2
        if np.any(stripe_mask):
            tint = np.array([26, 40, 58], dtype=np.float32).reshape(1, 1, 3)
            alpha = 0.16
            rgb_f = rgb.astype(np.float32)
            rgb_f[:, stripe_mask, :] = (1.0 - alpha) * rgb_f[:, stripe_mask, :] + alpha * tint
            rgb = np.clip(rgb_f, 0, 255).astype(np.uint8)

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
        pair_for_title = self._active_pair or self._selected_pair
        if pair_for_title:
            title = f"{pair_for_title} Order Book Heatmap"
        else:
            title = (
                "Order Book Heatmap (Top=Orange, Bottom=Blue)"
                if self._maker_mode
                else "Order Book Heatmap (Bid=Green, Ask=Red)"
            )
        title_w, title_h = text_size(title, font_size_px=self._fs(12.0))
        title_x = x0 + max(0, (pw - title_w) // 2)
        title_y = 4
        draw_text(canvas, title_x, title_y, title, label, font_size_px=self._fs(12.0))
        draw_hline(canvas, title_x, min(x1, title_x + title_w), min(y0 - 2, title_y + title_h + 1), label)
        mode_badge = "[MAKER]" if self._maker_mode else "[MARKET]"
        badge_w, _ = text_size(mode_badge, font_size_px=self._fs(10.0))
        badge_x = max(8, title_x - badge_w - 10)
        badge_y = title_y + 2
        draw_text(canvas, badge_x, badge_y, mode_badge, label, font_size_px=self._fs(10.0))
        self._mode_badge_rect = (badge_x - 4, max(0, badge_y - 2), badge_x + badge_w + 4, badge_y + int(self._fs(12.0)))

        y_label_left = min(self._width - 8, x1 + 10)
        quote = self._active_quote if self._active_quote else "QUOTE"
        a_y_title = f"price ({quote})"
        a_yw, a_yh = text_size(a_y_title, font_size_px=self._fs(8.0))
        a_yx = min(self._width - a_yw - 8, y_label_left)
        a_yy = max(2, y0 - a_yh - 6)
        draw_text(canvas, a_yx, a_yy, a_y_title, label, font_size_px=self._fs(8.0))
        draw_hline(canvas, a_yx, a_yx + a_yw, a_yy + a_yh + 1, label)

        if self._source in {"sse", "snapshot"}:
            spread = float(self._latest_stream_spread) if np.isfinite(self._latest_stream_spread) else np.nan
        else:
            best_bid = float(np.nanmax(self._latest_bid_prices)) if np.isfinite(self._latest_bid_prices).any() else np.nan
            best_ask = float(np.nanmin(self._latest_ask_prices)) if np.isfinite(self._latest_ask_prices).any() else np.nan
            spread = best_ask - best_bid if np.isfinite(best_bid) and np.isfinite(best_ask) else np.nan
        if self._maker_mode and np.isfinite(self._latest_bid_prices).any() and np.isfinite(self._latest_ask_prices).any():
            best_bid = float(np.nanmax(self._latest_bid_prices))
            best_ask = float(np.nanmin(self._latest_ask_prices))
            bid_eff = best_bid * float(max(0.0, 1.0 - self._maker_fee_rate))
            ask_eff = best_ask * float(1.0 + self._maker_fee_rate)
            spread = ask_eff - bid_eff
        spread_text = (
            f"Spread: {self._format_fixed(spread, self._spread_label_decimals())} = {self._format_scientific(spread, 2)}"
            if np.isfinite(spread)
            else "Spread: --"
        )
        spread_w, _ = text_size(spread_text, font_size_px=self._fs(10.0))
        spread_x = max(8, x1 - spread_w - 8)
        draw_text(canvas, spread_x, 4, spread_text, label, font_size_px=self._fs(10.0))
        # Tiny maker delta marker: best-price displacement vs market book.
        if np.isfinite(self._latest_bid_prices).any() and np.isfinite(self._latest_ask_prices).any():
            best_bid_mkt = float(np.nanmax(self._latest_bid_prices))
            best_ask_mkt = float(np.nanmin(self._latest_ask_prices))
            bid_factor = float(max(0.0, 1.0 - self._maker_fee_rate))
            ask_factor = float(1.0 + self._maker_fee_rate)
            bid_delta = (best_bid_mkt * bid_factor) - best_bid_mkt
            ask_delta = (best_ask_mkt * ask_factor) - best_ask_mkt
            delta_text = f"Δbid: {self._format_scientific(bid_delta, 2)}  Δask: {self._format_scientific(ask_delta, 2)}"
            delta_w, _ = text_size(delta_text, font_size_px=self._fs(8.0))
            delta_x = max(8, x1 - delta_w - 8)
            draw_text(canvas, delta_x, 16, delta_text, label, font_size_px=self._fs(8.0))
        if self._source in {"sse", "snapshot"}:
            host_ts = int(time.time())
            heatmap_ts = (
                int(self._column_ts[-1])
                if self._column_ts.size > 0 and np.isfinite(self._column_ts[-1])
                else None
            )
            book_ts_text = str(self._latest_exchange_ts) if self._latest_exchange_ts is not None else "--"
            heatmap_ts_text = str(heatmap_ts) if heatmap_ts is not None else "--"
            stream_meta = (
                f"stream: {self._stream_status} | mode: {'maker' if self._maker_mode else 'market'} | "
                f"host_ts: {host_ts} | book_ts: {book_ts_text} | heatmap_ts: {heatmap_ts_text}"
            )
            stream_meta = f"{stream_meta} | kbd_status: {self._keyboard_status}"
            if self._last_key_debug:
                stream_meta = f"{stream_meta} | kbd: {self._last_key_debug[:64]}"
            if self._last_stream_error:
                stream_meta = f"{stream_meta} | err: {self._last_stream_error[:42]}"
            if self._debug_log and np.isfinite(self._latest_bid_prices).any() and np.isfinite(self._latest_ask_prices).any():
                best_bid_dbg = float(np.nanmax(self._latest_bid_prices))
                best_ask_dbg = float(np.nanmin(self._latest_ask_prices))
                bid_idx_dbg = self._bin_index_for_price(best_bid_dbg)
                ask_idx_dbg = self._bin_index_for_price(best_ask_dbg)
                if 0 <= bid_idx_dbg < self._bin_count and 0 <= ask_idx_dbg < self._bin_count:
                    bid_lbl_dbg = self._price_min + float(bid_idx_dbg) * self._tick_size
                    ask_lbl_dbg = self._price_min + float(ask_idx_dbg) * self._tick_size
                    stream_meta = (
                        f"{stream_meta} | ymap_err "
                        f"bid:{self._format_scientific(best_bid_dbg - bid_lbl_dbg, 2)} "
                        f"ask:{self._format_scientific(best_ask_dbg - ask_lbl_dbg, 2)}"
                    )
            draw_text(canvas, x0 + 8, 4, stream_meta, label, font_size_px=self._fs(8.0))

        # Label each ordered price bin (not row centers). Major cadence labels are larger and emboldened.
        for b in range(self._bin_count):
            row_start = ph - int(round((b + 1) * ph / self._bin_count))
            row_end = ph - int(round(b * ph / self._bin_count)) - 1
            row_start = max(0, min(ph - 1, row_start))
            row_end = max(0, min(ph - 1, row_end))
            if row_end < row_start:
                continue
            y_center = y0 + (row_start + row_end) // 2
            price = self._price_min + float(b) * self._tick_size
            text = self._format_price_axis(price)
            is_major = (b % 5) == 0
            draw_hline(canvas, x1, min(self._width - 1, x1 + (6 if is_major else 3)), y_center, frame)
            rule_font = self._fs(9.0 if is_major else 7.25)
            t_w, t_h = text_size(text, font_size_px=rule_font)
            label_x = max(8, min(self._width - t_w - 8, y_label_left))
            draw_text(
                canvas,
                label_x,
                max(0, y_center - (t_h // 2)),
                text,
                label,
                font_size_px=rule_font,
                embolden_px=(2 if is_major else 1),
            )

        if divider_bottom >= divider_top:
            divider_bg = np.array([8, 11, 17], dtype=np.uint8)
            canvas[divider_top : divider_bottom + 1, x0 : x0 + pw, :3] = divider_bg
            canvas[divider_top : divider_bottom + 1, x0 : x0 + pw, 3] = 255
            draw_hline(canvas, x0, x1, divider_top, frame)
            draw_hline(canvas, x0, x1, divider_bottom, frame)
        else:
            draw_text(
                canvas,
                x0 + max(0, pw // 2 - 58),
                min(self._height - 14, y1 + 14),
                "time (s, recent -> right)",
                label,
                font_size_px=self._fs(8.0),
            )

        # Draw x-axis ticks/labels after divider so they are not overpainted.
        x_ticks = 6
        tick_y0 = y1
        tick_y1 = min(self._height - 1, y1 + 4)
        label_y = min(self._height - 12, y1 + 8)
        x_tick_rotate = self._x_tick_rotate_deg()
        bin_w_px = float(pw) / max(1.0, float(self._display_window_sec))
        half_bin_px = 0.5 * bin_w_px
        for i in range(x_ticks + 1):
            frac = i / x_ticks
            x_unclamped = x0 + (frac * float(pw)) + half_bin_px
            x_min_center = x0 + half_bin_px
            x_max_center = x0 + float(pw) - half_bin_px
            x = int(round(max(x_min_center, min(x_max_center, x_unclamped))))
            draw_vline(canvas, x, tick_y0, tick_y1, frame)
            local_x = max(0, min(pw - 1, int(round((x - x0)))))
            source_col = source_start + int(src_idx[local_x])
            tick_ts = self._column_ts[source_col] if 0 <= source_col < self._column_ts.shape[0] else np.nan
            if np.isfinite(tick_ts):
                tick_text = str(int(tick_ts))
            else:
                seconds_ago = int(round((1.0 - frac) * float(self._display_window_sec)))
                if self._latest_exchange_ts is not None and self._source in {"snapshot", "sse"}:
                    tick_text = str(int(self._latest_exchange_ts - seconds_ago))
                else:
                    tick_text = f"-{seconds_ago}s"
            tw, _ = text_size(tick_text, font_size_px=self._fs(9.0), rotate_deg=x_tick_rotate)
            # Right-anchor each angled label near its tick to reduce right-edge clipping.
            lx = max(0, min(self._width - tw - 1, x - tw + 2))
            draw_text(canvas, lx, label_y, tick_text, label, font_size_px=self._fs(9.0), rotate_deg=x_tick_rotate)

        if divider_bottom >= divider_top:
            x_title = "time (s, recent -> right)"
            tx_w, tx_h = text_size(x_title, font_size_px=self._fs(8.0))
            tx_x = x0 + max(0, (pw - tx_w) // 2)
            # Place x-title below rotated tick labels with explicit spacing.
            tx_y = label_y + self._x_tick_label_height_px() + 3
            tx_y = min(divider_bottom - tx_h - 1, tx_y)
            tx_y = max(divider_top + 1, tx_y)
            draw_text(canvas, tx_x, tx_y, x_title, label, font_size_px=self._fs(8.0))
            draw_hline(canvas, tx_x, min(x1, tx_x + tx_w), min(divider_bottom - 1, tx_y + tx_h + 1), label)

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

        live_book_ts_text = str(self._latest_exchange_ts) if self._latest_exchange_ts is not None else "--"
        b_title = f"Market Book Bids (SELL) | ts: {live_book_ts_text}"
        c_title = f"Market Book Asks (BUY) | ts: {live_book_ts_text}"
        b_tw, b_th = text_size(b_title, font_size_px=self._fs(10.0))
        c_tw, c_th = text_size(c_title, font_size_px=self._fs(10.0))
        b_tx = b_x0 + max(0, (b_w - b_tw) // 2)
        c_tx = c_x0 + max(0, (c_w - c_tw) // 2)
        b_ty, c_ty = by0 + 7, by0 + 7
        draw_text(canvas, b_tx, b_ty, b_title, label, font_size_px=self._fs(10.0))
        draw_text(canvas, c_tx, c_ty, c_title, label, font_size_px=self._fs(10.0))
        draw_hline(canvas, b_tx, min(b_x1, b_tx + b_tw), min(by1, b_ty + b_th + 1), label)
        draw_hline(canvas, c_tx, min(c_x1, c_tx + c_tw), min(by1, c_ty + c_th + 1), label)

        b_y_title = "bid price bin"
        c_y_title = "ask price bin"
        b_yw, b_yh = text_size(b_y_title, font_size_px=self._fs(8.0))
        c_yw, c_yh = text_size(c_y_title, font_size_px=self._fs(8.0))
        b_yx, c_yx = b_x0 + 6, c_x0 + 6
        b_title_underline_y = b_ty + b_th + 1
        c_title_underline_y = c_ty + c_th + 1
        b_yy = max(by0 + 2, b_title_underline_y - b_yh - 1)
        c_yy = max(by0 + 2, c_title_underline_y - c_yh - 1)
        draw_text(canvas, b_yx, b_yy, b_y_title, label, font_size_px=self._fs(8.0))
        draw_text(canvas, c_yx, c_yy, c_y_title, label, font_size_px=self._fs(8.0))
        draw_hline(canvas, b_yx, min(b_x1, b_yx + b_yw), min(by1, b_yy + b_yh + 1), label)
        draw_hline(canvas, c_yx, min(c_x1, c_yx + c_yw), min(by1, c_yy + c_yh + 1), label)

        def _draw_sideways_distribution(
            panel_x0: int,
            panel_x1: int,
            prices: np.ndarray,
            sizes: np.ndarray,
            bar_color: tuple[int, int, int, int],
        ) -> None:
            panel_num_font = self._fs(7.0)
            bar_left = panel_x0 + 88
            bar_right = panel_x1 - 72
            bar_w = max(10, bar_right - bar_left)
            header_h = min(30, max(18, bh // 4))
            usable_h = max(1, bh - header_h)
            row_h = max(1, usable_h // self._levels_per_side)
            # Display both sides in descending price order (high -> low, top -> bottom)
            # so panel row direction matches Graph A's y-axis orientation.
            finite = np.isfinite(prices)
            if finite.any():
                order = np.argsort(prices[finite])[::-1]
                ordered_prices = prices[finite][order]
                ordered_sizes = sizes[finite][order]
            else:
                ordered_prices = np.array([], dtype=np.float64)
                ordered_sizes = np.array([], dtype=np.float32)

            max_qty = float(np.max(ordered_sizes)) if ordered_sizes.size > 0 else 0.0
            if max_qty <= 0.0:
                max_qty = 1.0
            for i in range(self._levels_per_side):
                y_top = by0 + header_h + i * row_h
                y_bot = min(by1, y_top + row_h - 1)
                if y_bot < y_top:
                    continue
                if i < ordered_prices.shape[0]:
                    price = float(ordered_prices[i])
                    qty = float(ordered_sizes[i])
                else:
                    price = float("nan")
                    qty = 0.0
                frac = max(0.0, min(1.0, qty / max_qty))
                fill = int(round(frac * bar_w))
                if fill > 0:
                    x_fill_end = min(panel_x1, bar_left + fill)
                    for yy in range(y_top, y_bot + 1):
                        draw_hline(canvas, bar_left, x_fill_end, yy, bar_color)
                if np.isfinite(price):
                    idx = self._bin_index_for_price(price)
                    if 0 <= idx < self._bin_count:
                        display_price = self._price_min + float(idx) * self._tick_size
                    else:
                        display_price = price
                    price_text = self._format_price_axis(float(display_price))
                else:
                    price_text = "--"
                price_w, _ = text_size(price_text, font_size_px=panel_num_font)
                price_x = max(panel_x0 + 6, (bar_left - 6) - price_w)
                draw_text(
                    canvas,
                    price_x,
                    max(0, y_top + 1),
                    price_text,
                    label,
                    font_size_px=panel_num_font,
                )
                draw_text(
                    canvas,
                    min(self._width - 80, bar_right + 5),
                    max(0, y_top + 1),
                    self._format_fixed(qty, 6),
                    label,
                    font_size_px=panel_num_font,
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
        if self._source == "sse":
            self._stream_status = "connecting"
            self._sse.start()
        if self._source == "snapshot":
            self._stream_status = "connecting"
            self._snapshot_feed.start()
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
        try:
            events = ctx.poll_hdi_events(max_events=64)
        except Exception as exc:  # noqa: BLE001
            self._keyboard_status = f"err:{str(exc)[:28]}"
            events = []
        self._poll_keyboard_toggles(events)
        self._poll_pointer_toggle(events)
        self._step_market(dt)
        self._emit_console_stream_meta()
        frame = self._render()
        ctx.submit_write_batch(compile_full_rewrite_batch(frame))
        return None

    def stop(self, ctx) -> None:
        _ = ctx
        if self._source == "sse":
            self._sse.stop()
        if self._source == "snapshot":
            self._snapshot_feed.stop()
        return None


def create() -> TradingDashboardApp:
    return TradingDashboardApp()
