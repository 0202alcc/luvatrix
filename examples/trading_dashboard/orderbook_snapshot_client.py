from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class OrderBookLevel:
    level: int
    price: float
    size: float


@dataclass(frozen=True)
class OrderBookSnapshot:
    product_id: str
    timestamp: int | None
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def spread(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return float(self.best_ask - self.best_bid)


class OrderBookSnapshotClient:
    """Polling client for CoinbaseTraderBot orderbook snapshots."""

    def __init__(
        self,
        *,
        base_url: str,
        product_id: str,
        levels: int = 15,
        poll_interval_sec: float = 1.0,
        request_timeout_sec: float = 5.0,
        max_backoff_sec: float = 10.0,
        stale_after_sec: float = 10.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.product_id = product_id.strip().upper()
        self.levels = max(1, int(levels))
        self.poll_interval_sec = max(0.05, float(poll_interval_sec))
        self.request_timeout_sec = max(0.1, float(request_timeout_sec))
        self.max_backoff_sec = max(0.2, float(max_backoff_sec))
        self.stale_after_sec = max(0.2, float(stale_after_sec))
        self._logger = logger or logging.getLogger(__name__)

        self._last_timestamp: int | None = None
        self._unchanged_since_mono: float | None = None
        self._last_stale_log_mono: float = 0.0

    def snapshot_url(self) -> str:
        quoted_product = urllib.parse.quote(self.product_id, safe="-")
        return f"{self.base_url}/api/orderbook/{quoted_product}?levels={self.levels}"

    def fetch_once(self) -> OrderBookSnapshot:
        url = self.snapshot_url()
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.request_timeout_sec) as resp:
            status_code = int(getattr(resp, "status", 200))
            if status_code >= 400:
                raise urllib.error.HTTPError(url, status_code, f"HTTP {status_code}", hdrs=None, fp=None)
            raw = resp.read()
        payload = json.loads(raw.decode("utf-8"))
        return self._parse_snapshot(payload)

    def poll_forever(self) -> Iterator[OrderBookSnapshot]:
        backoff_sec = self.poll_interval_sec
        while True:
            loop_start = time.monotonic()
            try:
                snap = self.fetch_once()
                self._track_staleness(snap)
                backoff_sec = self.poll_interval_sec
                yield snap
                elapsed = time.monotonic() - loop_start
                sleep_s = max(0.0, self.poll_interval_sec - elapsed)
                if sleep_s > 0:
                    time.sleep(sleep_s)
            except Exception as exc:  # noqa: BLE001 - intentional retry loop
                transient = self._is_transient_error(exc)
                if not transient:
                    raise
                self._logger.warning(
                    "orderbook poll transient error product=%s: %s; retrying in %.2fs",
                    self.product_id,
                    exc,
                    backoff_sec,
                )
                time.sleep(backoff_sec)
                backoff_sec = min(self.max_backoff_sec, max(0.1, backoff_sec * 2.0))

    def _parse_snapshot(self, payload: dict) -> OrderBookSnapshot:
        if not isinstance(payload, dict):
            raise ValueError("orderbook payload must be an object")
        product_id = str(payload.get("product_id") or "").strip().upper()
        if not product_id:
            raise ValueError("orderbook payload missing product_id")

        ts_raw = payload.get("timestamp")
        timestamp = int(ts_raw) if isinstance(ts_raw, (int, float)) else None

        bids = self._parse_levels(payload.get("bids"))
        asks = self._parse_levels(payload.get("asks"))
        return OrderBookSnapshot(
            product_id=product_id,
            timestamp=timestamp,
            bids=bids,
            asks=asks,
        )

    def _parse_levels(self, raw: object) -> tuple[OrderBookLevel, ...]:
        if raw is None:
            return ()
        if not isinstance(raw, list):
            raise ValueError("orderbook side must be an array")
        out: list[OrderBookLevel] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            lvl = item.get("level")
            px = item.get("price")
            sz = item.get("size")
            if lvl is None or px is None or sz is None:
                continue
            try:
                out.append(
                    OrderBookLevel(
                        level=int(lvl),
                        price=float(px),
                        size=float(sz),
                    )
                )
            except (TypeError, ValueError):
                continue
        return tuple(out)

    def _track_staleness(self, snap: OrderBookSnapshot) -> None:
        now_mono = time.monotonic()
        ts = snap.timestamp
        if ts is None:
            self._logger.info(
                "orderbook snapshot has null timestamp product=%s bids=%d asks=%d",
                snap.product_id,
                len(snap.bids),
                len(snap.asks),
            )
            return

        if ts != self._last_timestamp:
            self._last_timestamp = ts
            self._unchanged_since_mono = now_mono
            return

        if self._unchanged_since_mono is None:
            self._unchanged_since_mono = now_mono
            return

        stale_for = now_mono - self._unchanged_since_mono
        should_log = stale_for >= self.stale_after_sec and (now_mono - self._last_stale_log_mono) >= self.stale_after_sec
        if should_log:
            self._last_stale_log_mono = now_mono
            self._logger.warning(
                "stale orderbook snapshot product=%s timestamp=%s unchanged_for=%.1fs",
                snap.product_id,
                ts,
                stale_for,
            )

    @staticmethod
    def _is_transient_error(exc: Exception) -> bool:
        if isinstance(exc, urllib.error.HTTPError):
            return exc.code in (408, 425, 429, 500, 502, 503, 504)
        if isinstance(exc, urllib.error.URLError):
            return True
        if isinstance(exc, TimeoutError):
            return True
        return False


def best_quote(snapshot: OrderBookSnapshot) -> dict:
    """Convenience accessor for top-of-book + spread + full depth arrays."""
    return {
        "product_id": snapshot.product_id,
        "timestamp": snapshot.timestamp,
        "best_bid": snapshot.best_bid,
        "best_ask": snapshot.best_ask,
        "spread": snapshot.spread,
        "bids": snapshot.bids,
        "asks": snapshot.asks,
    }

