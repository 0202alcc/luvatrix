# Trading Dashboard

Order-book over time dashboard demo using `luvatrix_plot` raster + compile utilities.

Mosaic layout:
- `A` (top): order-book heatmap (bid green / ask red)
- `B` (bottom-left): live sideways bid distribution bars with exact quantities
- `C` (bottom-right): live sideways ask distribution bars with exact quantities

Visualization model:
- `x` axis: time (seconds, newest on the right)
- `y` axis: quote price bins (based on tick size)
- bids: green intensity (normalized per frame)
- asks: red intensity (normalized per frame)

Optional env vars:
- `LUVATRIX_ORDERBOOK_SOURCE` (`sim` default, or `sse` for live stream mode)
- `LUVATRIX_ORDERBOOK_SNAPSHOT_BASE_URL` (snapshot mode base URL, default `https://mgabatangnyc.tail9574b0.ts.net:8443`)
- `LUVATRIX_ORDERBOOK_SNAPSHOT_LEVELS` (default `15`)
- `LUVATRIX_ORDERBOOK_SNAPSHOT_POLL_INTERVAL_SEC` (default `1.0`)
- `LUVATRIX_ORDERBOOK_SNAPSHOT_STALE_AFTER_SEC` (default `10.0`; stale timestamp warning threshold)
- `LUVATRIX_ORDERBOOK_SSE_URL` (default `https://mgabatangnyc.tail9574b0.ts.net:8443/sse/prices`)
- `LUVATRIX_ORDERBOOK_PRODUCT` (optional; lock to one pair like `BTC-USD`; otherwise first seen pair is used)
- `LUVATRIX_ORDERBOOK_SSE_INSECURE_TLS` (`1`/`true` to skip TLS verification for local testing only)
- `LUVATRIX_ORDERBOOK_TIME_WINDOW_SEC` (default `120`)
- `LUVATRIX_ORDERBOOK_TICK_SIZE` (default `0.25`)
- bid/ask depth levels are fixed at `15` per side
- `LUVATRIX_ORDERBOOK_DISPLAY_WINDOW_SEC` (default equals `LUVATRIX_ORDERBOOK_TIME_WINDOW_SEC`; shows cropped recent x-domain)
- `LUVATRIX_ORDERBOOK_INITIAL_MID` (default `100.0`)
- `LUVATRIX_ORDERBOOK_DRIFT` (default `0.12`)
- `LUVATRIX_ORDERBOOK_FIT_PAD_TICKS` (default `1.0`; pad above ask/below bid when fitting y-range)
- `LUVATRIX_ORDERBOOK_GRADIENT_BLUR_PX` (default `3`; vertical blur radius for smooth no-gap gradient)

Run from repo root:

```bash
uv run --python 3.14 python main.py run-app examples/trading_dashboard --render headless --ticks 120 --fps 60 --width 640 --height 360
```

Live SSE mode (CoinbaseTraderBot stream):

```bash
LUVATRIX_ORDERBOOK_SOURCE=sse \
LUVATRIX_ORDERBOOK_SSE_URL="https://mgabatangnyc.tail9574b0.ts.net:8443/sse/prices" \
LUVATRIX_ORDERBOOK_PRODUCT="BTC-USD" \
uv run --python 3.14 python main.py run-app examples/trading_dashboard --render headless --ticks 1200 --fps 120 --width 1280 --height 720
```

Live snapshot mode (true orderbook depth over HTTP polling):

```bash
LUVATRIX_ORDERBOOK_SOURCE=snapshot \
LUVATRIX_ORDERBOOK_SNAPSHOT_BASE_URL="https://mgabatangnyc.tail9574b0.ts.net:8443" \
LUVATRIX_ORDERBOOK_PRODUCT="ADA-USD" \
LUVATRIX_ORDERBOOK_SNAPSHOT_LEVELS=15 \
LUVATRIX_ORDERBOOK_SNAPSHOT_POLL_INTERVAL_SEC=1.0 \
uv run --python 3.14 python main.py run-app examples/trading_dashboard --ticks 1200 --fps 120 --width 1280 --height 720
```

Orderbook snapshot polling client (HTTP, no deltas):

```python
from examples.trading_dashboard.orderbook_snapshot_client import (
    OrderBookSnapshotClient,
    best_quote,
)

client = OrderBookSnapshotClient(
    base_url="https://mgabatangnyc.tail9574b0.ts.net:8443",
    product_id="ADA-USD",
    levels=15,
    poll_interval_sec=1.0,
)

for snapshot in client.poll_forever():
    q = best_quote(snapshot)
    print(
        q["product_id"],
        q["timestamp"],
        q["best_bid"],
        q["best_ask"],
        q["spread"],
        len(q["bids"]),
        len(q["asks"]),
    )
```
