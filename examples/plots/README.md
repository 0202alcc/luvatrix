# Plot Examples

All in-repo plotting demos live here.

## Demos

1. `plot_demo/`
   - Dynamic line + scatter plot updated every app loop tick.

2. `static_plot/`
   - Static line + scatter plot from pre-generated 1-D data.

## Run

From repo root:

```bash
uv run --python 3.14 python main.py run-app examples/plots/plot_demo --render headless --ticks 300 --fps 60 --width 640 --height 360
```

```bash
uv run --python 3.14 python main.py run-app examples/plots/static_plot --render headless --ticks 300 --fps 60 --width 640 --height 360
```
