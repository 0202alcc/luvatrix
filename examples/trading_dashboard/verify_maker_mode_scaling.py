"""Verify Plot A maker-mode price scaling against real snapshot data.

Usage:
  uv run python examples/trading_dashboard/verify_maker_mode_scaling.py \
    --base-url "https://mgabatangnyc.tail9574b0.ts.net:8443" \
    --product "PEPE-USD" \
    --levels 15 \
    --maker-fee-rate 0.006
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.trading_dashboard.app_main import TradingDashboardApp
from examples.trading_dashboard.orderbook_snapshot_client import OrderBookSnapshotClient


def _build_app(*, maker_mode: bool, maker_fee_rate: float, product: str) -> TradingDashboardApp:
    os.environ["LUVATRIX_ORDERBOOK_SOURCE"] = "snapshot"
    os.environ["LUVATRIX_ORDERBOOK_PRODUCT"] = product
    os.environ["LUVATRIX_ORDERBOOK_MAKER_MODE"] = "1" if maker_mode else "0"
    os.environ["LUVATRIX_ORDERBOOK_MAKER_FEE_RATE"] = str(maker_fee_rate)
    app = TradingDashboardApp()
    app._width = 1400
    app._height = 820
    app._ensure_heatmap_buffers()
    return app


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify maker mode scaling in Plot A")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--product", default="PEPE-USD")
    parser.add_argument("--levels", type=int, default=15)
    parser.add_argument("--poll-interval-sec", type=float, default=1.0)
    parser.add_argument("--maker-fee-rate", type=float, default=0.006)
    parser.add_argument("--atol", type=float, default=1e-6)
    args = parser.parse_args()

    client = OrderBookSnapshotClient(
        base_url=args.base_url,
        product_id=args.product,
        levels=max(1, int(args.levels)),
        poll_interval_sec=max(0.1, float(args.poll_interval_sec)),
    )
    snap = client.fetch_once()
    if not snap.bids or not snap.asks:
        print(f"FAIL: empty snapshot for {args.product} (ts={snap.timestamp})")
        return 2

    app_base = _build_app(maker_mode=False, maker_fee_rate=args.maker_fee_rate, product=args.product)
    app_maker = _build_app(maker_mode=True, maker_fee_rate=args.maker_fee_rate, product=args.product)

    if not app_base._apply_snapshot(snap) or not app_maker._apply_snapshot(snap):
        print("FAIL: could not apply snapshot into app buffers")
        return 3

    fee = max(0.0, float(args.maker_fee_rate))
    bid_prices = app_base._latest_bid_prices.copy()
    ask_prices = app_base._latest_ask_prices.copy()
    bid_sizes = app_base._latest_bid_sizes_exact.copy()
    ask_sizes = app_base._latest_ask_sizes_exact.copy()

    bid_norm = bid_sizes.copy()
    ask_norm = ask_sizes.copy()
    bmx = float(np.max(bid_norm)) if bid_norm.size else 0.0
    amx = float(np.max(ask_norm)) if ask_norm.size else 0.0
    if bmx > 0.0:
        bid_norm /= bmx
    if amx > 0.0:
        ask_norm /= amx

    bid_expected_prices = bid_prices.copy()
    ask_expected_prices = ask_prices.copy()
    bid_mask = np.isfinite(bid_expected_prices)
    ask_mask = np.isfinite(ask_expected_prices)
    bid_expected_prices[bid_mask] *= float(max(0.0, 1.0 - fee))
    ask_expected_prices[ask_mask] *= float(1.0 + fee)

    bid_expected_col = app_maker._build_side_column(bid_expected_prices, bid_norm)
    ask_expected_col = app_maker._build_side_column(ask_expected_prices, ask_norm)
    bid_actual_col = app_maker._bid_heatmap[:, -1]
    ask_actual_col = app_maker._ask_heatmap[:, -1]

    bid_err = np.abs(bid_actual_col - bid_expected_col)
    ask_err = np.abs(ask_actual_col - ask_expected_col)
    bid_active = bid_expected_col > 1e-6
    ask_active = ask_expected_col > 1e-6
    bid_max_err = float(np.max(bid_err[bid_active])) if np.any(bid_active) else 0.0
    ask_max_err = float(np.max(ask_err[ask_active])) if np.any(ask_active) else 0.0
    bid_mean_err = float(np.mean(bid_err[bid_active])) if np.any(bid_active) else 0.0
    ask_mean_err = float(np.mean(ask_err[ask_active])) if np.any(ask_active) else 0.0

    print(
        f"snapshot product={snap.product_id} ts={snap.timestamp} "
        f"bids={len(snap.bids)} asks={len(snap.asks)} spread={snap.spread}"
    )
    print(f"maker_fee_rate={fee}")
    print(f"bid_column_error max={bid_max_err:.3e} mean={bid_mean_err:.3e}")
    print(f"ask_column_error max={ask_max_err:.3e} mean={ask_mean_err:.3e}")

    ok = bid_max_err <= float(args.atol) and ask_max_err <= float(args.atol)
    print("PASS: maker mode scaling verified" if ok else "FAIL: maker mode scaling mismatch")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
