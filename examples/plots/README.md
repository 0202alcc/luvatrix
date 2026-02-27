# Plot Examples

All in-repo plotting demos live here.

## Demos

1. `plot_demo/`
   - Dynamic line + scatter plot updated every app loop tick.

2. `static_plot/`
   - Static line + scatter plot from pre-generated 1-D data.

3. `static_plot_2d/`
   - Static line + scatter plot from pre-generated 2-D `(x, y)` arrays.

4. `dynamic_plot_2d/`
   - Dynamic monotonic-`x` 2-D stream with gap handling via `Dynamic2DMonotonicAxis`.

## Run

From repo root:

```bash
uv run --python 3.14 python main.py run-app examples/plots/plot_demo --render headless --ticks 300 --fps 60 --width 640 --height 360
```

```bash
uv run --python 3.14 python main.py run-app examples/plots/static_plot --render headless --ticks 300 --fps 60 --width 640 --height 360
```

```bash
uv run --python 3.14 python main.py run-app examples/plots/static_plot_2d --render headless --ticks 300 --fps 60 --width 640 --height 360
```

```bash
uv run --python 3.14 python main.py run-app examples/plots/dynamic_plot_2d --render headless --ticks 300 --fps 60 --width 640 --height 360
```
