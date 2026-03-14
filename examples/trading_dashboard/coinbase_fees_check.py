"""Quick Coinbase fee check for the trading dashboard workspace.

Usage:
    uv run python examples/trading_dashboard/coinbase_fees_check.py
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

try:
    from coinbase_trader_api import CoinbaseAPI
except ModuleNotFoundError:
    # Compatibility fallback for local package layout where CoinbaseAPI.py is repo-root.
    local_pkg_root = Path("/Users/aleccandidato/Projects/CoinbaseTraderBot")
    if str(local_pkg_root) not in sys.path:
        sys.path.insert(0, str(local_pkg_root))
    from coinbase_trader_api import CoinbaseAPI


def _as_decimal_string(value: Any) -> str:
    if isinstance(value, Decimal):
        normalized = value.normalize()
        return format(normalized, "f") if normalized == normalized.to_integral() else format(normalized, "g")
    return str(value)


def main() -> int:
    load_dotenv()

    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    if not api_key or not api_secret:
        print("Missing required env vars: COINBASE_API_KEY and/or COINBASE_API_SECRET")
        return 1

    client = CoinbaseAPI(api_key, api_secret)
    fees = client.get_maker_taker_fees()

    maker_fee = fees.get("maker_fee_rate")
    taker_fee = fees.get("taker_fee_rate")
    pricing_tier = fees.get("pricing_tier")
    total_volume = fees.get("total_volume")
    total_fees = fees.get("total_fees")

    print("Coinbase fee summary")
    print(f"maker_fee_rate: {_as_decimal_string(maker_fee)}")
    print(f"taker_fee_rate: {_as_decimal_string(taker_fee)}")
    print(f"pricing_tier: {pricing_tier}")
    print(f"total_volume: {_as_decimal_string(total_volume)}")
    print(f"total_fees: {_as_decimal_string(total_fees)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
