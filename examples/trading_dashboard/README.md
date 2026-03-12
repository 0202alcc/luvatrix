# Trading Dashboard

Order-book over time heatmap demo using `luvatrix_plot` raster + compile utilities.

Visualization model:
- `x` axis: time (seconds, newest on the right)
- `y` axis: quote price bins (based on tick size)
- bids: green intensity (normalized per frame)
- asks: red intensity (normalized per frame)

Optional env vars:
- `LUVATRIX_ORDERBOOK_TIME_WINDOW_SEC` (default `120`)
- `LUVATRIX_ORDERBOOK_PRICE_BINS` (default `96`)
- `LUVATRIX_ORDERBOOK_TICK_SIZE` (default `0.25`)
- bid/ask depth levels are fixed at `15` per side
- `LUVATRIX_ORDERBOOK_INITIAL_MID` (default `100.0`)
- `LUVATRIX_ORDERBOOK_DRIFT` (default `0.12`)
- `LUVATRIX_ORDERBOOK_FIT_PAD_TICKS` (default `1.0`; pad above ask/below bid when fitting y-range)
- `LUVATRIX_ORDERBOOK_GRADIENT_BLUR_PX` (default `3`; vertical blur radius for smooth no-gap gradient)

Run from repo root:

```bash
uv run --python 3.14 python main.py run-app examples/trading_dashboard --render headless --ticks 120 --fps 60 --width 640 --height 360
```
