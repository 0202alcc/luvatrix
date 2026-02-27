# Luvatrix Plotting Module Design (v0 -> v1)

## 1. Goals

Primary goals:

1. Add in-repo plotting package: `luvatrix_plot/`.
2. Support `scatter` and `line` plot from:
   - `pandas` (`Series` and 1-D numeric `DataFrame` columns)
   - `numpy` arrays
   - `torch` tensors
3. Compile plots into Luvatrix app-protocol UI frames and matrix writes.
4. Optimize for speed using layered raster strategy, not generic high-overhead UI IR.

Non-goals for v0:

1. Multi-axis transforms (log, datetime, categorical)
2. Complex layouts (legends outside plot area, constrained layout engine)
3. Rich interactivity (hover, pan, zoom)

## 2. Core Terms

Use these terms as first-class contracts:

1. `Canvas`: mutable RGBA pixel matrix.
2. `TemplateLayer`: immutable pre-drawn pixel buffer.
3. `DrawingLayer`: mutable layer for series geometry.
4. `PlotArea`: layered composition of plot background + data drawing.
5. `Framing`: composition where some regions are static template and others dynamic.
6. `Subplot`: one logical chart viewport with frame, axes, grid, series, and labels.

## 3. Rendering Order (Back -> Front)

Deterministic draw order per subplot:

1. Clear or reuse target canvas.
2. Blit `frame_template` (panel border/chrome/static backdrop).
3. Blit `plot_bg_template` (static grid/background when cache-valid).
4. Draw dynamic series geometry (`scatter`, `line`) to `drawing_layer`.
5. Draw axis rules/ticks when dynamic for current limits.
6. Draw text overlay (title, axis units, tick labels) last for legibility.

Formal equation:

`final = frame_template + plot_bg_template + drawing_layer + axis_overlay + text_overlay`

Tie-breaking rules:

1. Line path renders before markers for same series.
2. Series render in insertion order unless explicit `z` provided.
3. Alpha blending order is stable and testable.

## 4. Data and API Model

### 4.1 Public API (v0)

```python
from luvatrix_plot import figure

fig = figure(width=640, height=360)
ax = fig.axes(title="CPU")
ax.scatter(y=data)            # implicit x = index
ax.plot(y=data, mode="line")
ax.plot(x=x, y=y)             # explicit x/y
batch = fig.compile_write_batch()   # app-protocol ready
```

Convenience signatures:

1. `Axes.scatter(y, *, x=None, color=..., size=..., alpha=...)`
2. `Axes.plot(y, *, x=None, color=..., width=..., alpha=...)`
3. `Axes.series(x=None, y=..., mode="markers|lines|lines+markers", ...)`

Input acceptance:

1. 1-D numeric `pandas.Series`
2. `pandas.DataFrame` via column selection (`x="col_a", y="col_b"`)
3. 1-D `numpy.ndarray`
4. 1-D `torch.Tensor` (CPU/GPU; GPU copied to CPU for render)
5. numeric types: `int`, `float`, `Decimal`

### 4.2 Internal Data Contracts

```python
@dataclass(frozen=True)
class SeriesData:
    x: np.ndarray        # float64, shape (n,)
    y: np.ndarray        # float64, shape (n,)
    mask: np.ndarray     # bool validity mask
    source_name: str | None

@dataclass(frozen=True)
class Viewport:
    x0: int
    y0: int
    width: int
    height: int

@dataclass(frozen=True)
class DataLimits:
    xmin: float
    xmax: float
    ymin: float
    ymax: float

@dataclass(frozen=True)
class PlotTransform:
    sx: float
    tx: float
    sy: float
    ty: float
```

Policy: adapters normalize all accepted inputs into `SeriesData`; renderer only consumes normalized numeric arrays.

## 5. Scaling and Mapping Semantics

### 5.1 Domain/Range Defaults

For 1-D `y` input:

1. Assume ordered and evenly spaced samples.
2. Domain defaults to index range: `[0, n - 1]`.
3. Range defaults to data min/max expanded by margin buffer.

Default buffer:

1. If `ymin != ymax`: pad by `5%` of span.
2. If `ymin == ymax`: pad by `max(1.0, abs(ymin)*0.05)`.

### 5.2 Pixel Mapping

For subplot viewport `W x H` (plot area only, excluding label gutters):

1. `px = round((x - xmin) * (W - 1) / (xmax - xmin))`
2. `py = H - 1 - round((y - ymin) * (H - 1) / (ymax - ymin))`

Notes:

1. Y is inverted for screen coordinates.
2. Clamp to `[0, W-1]` and `[0, H-1]` after rounding.

### 5.3 When Samples and Pixels Differ

For horizontal axis:

1. If `n <= W`: map each sample directly; natural spacing appears from transform.
2. If `n > W`: downsample by pixel-column aggregation:
   - bucket by target `px`
   - scatter: keep representative point(s) per column
   - line: preserve vertical extent per column to avoid losing spikes

Avoid extrapolating synthetic points in v0.

## 6. Tick, Rule, and Grid Generation

Dynamic generation per current limits and viewport size:

1. Use "nice ticks" (1/2/5 * 10^k stepping).
2. Target tick count:
   - x: ~6-10 ticks based on width
   - y: ~4-8 ticks based on height
3. Build grid lines from the same tick values.
4. Label format policy:
   - fixed-point for moderate magnitudes
   - scientific notation for very large/small
   - trim trailing zeros

This layer is cacheable by key:

`(viewport_size, xmin, xmax, ymin, ymax, style_hash)`

## 7. Layer Caching and Invalidation

### 7.1 Layers

1. `frame_template`: rarely changes.
2. `plot_bg_template`: changes when ticks/grid or background style change.
3. `drawing_layer`: changes whenever visible data/style changes.
4. `text_overlay`: changes when labels/title/ticks text changes.

### 7.2 Dirty-Rect Strategy

1. Compute bounding rect of changed geometry per series update.
2. Clear/repaint only dirty rect in dynamic layers.
3. Full redraw fallback when limits or viewport dimensions change.

### 7.3 Cache Keys

1. Frame cache key: `(subplot_size, frame_style_hash)`
2. Grid cache key: `(subplot_plot_size, limits, tick_policy_hash, bg_style_hash)`
3. Text cache key: `(labels, fonts, limits, tick_values, text_style_hash)`

## 8. Subplot Layout Contract

Single subplot in v0 still uses explicit regions:

1. Outer frame rect.
2. Plot rect (data raster area).
3. Axis/title gutters.

Subplot fields:

1. `title`
2. `x_label_bottom`, `x_label_top` (top optional)
3. `y_label_left`, `y_label_right` (right optional)
4. `show_top_axis`, `show_right_axis`
5. `plot_padding`

In v0 default to bottom x-axis and left y-axis enabled; top/right off.

## 9. App-Protocol Integration

Compilation path:

1. Plot API builds `Figure/Axes/Series` object graph.
2. Renderer rasterizes subplot composition into RGBA frame.
3. Compiler emits app-protocol write payload as one frame rewrite.

Adapter surface:

1. `Figure.to_rgba()` -> `np.ndarray[H, W, 4]`
2. `Figure.compile_write_batch()` -> runtime write batch object
3. Optional: `Axes.to_component()` for future mixed UI/component composition

This keeps plotting fast-path independent from generic UI component IR, while still interoperating with app-protocol frame submission.

## 10. Error Handling and Data Hygiene

v0 behavior:

1. Empty input: raise `PlotDataError("empty series")`.
2. Non-numeric dtype after coercion: raise `PlotDataError`.
3. `NaN`/`None`:
   - scatter: drop invalid points
   - line: break path at invalid points
4. `Decimal`: coerce to `float64` with documented precision caveat.
5. Torch CUDA tensor: copy to CPU with explicit cost warning (once per call).

## 11. Testing Strategy

Required tests for v0:

1. Normalization tests across pandas/numpy/torch and dtypes.
2. Mapping tests for domain/range -> pixel coordinates.
3. Degenerate range tests (`ymin == ymax`).
4. Downsampling correctness tests (`n > W`).
5. Layer ordering snapshot tests.
6. Determinism tests (same input -> byte-identical frame).
7. App-protocol integration test (`compile_write_batch` emits valid full-frame write).

## 12. Package Layout (Proposed)

```text
luvatrix_plot/
  __init__.py
  api.py                # figure(), axes(), top-level helpers
  figure.py             # Figure, Axes, subplot layout
  series.py             # Series config + mode markers/lines
  adapters/
    __init__.py
    pandas_adapter.py
    numpy_adapter.py
    torch_adapter.py
  scales.py             # limits, transforms, tick generation
  raster/
    __init__.py
    canvas.py           # RGBA canvas + blit ops
    draw_markers.py
    draw_lines.py
    draw_text.py
    layers.py           # template/drawing/text layer manager
  compile/
    __init__.py
    app_protocol.py     # write-batch compiler
  errors.py
```

## 13. Iteration Plan

### Iteration 1: Skeleton + Normalization

1. Create package structure and public API stubs.
2. Implement adapters -> `SeriesData` normalization.
3. Add normalization tests.

Exit: scatter/line can accept all source types and produce validated internal data.

### Iteration 2: Single-Subplot Raster MVP

1. Implement canvas, mapping transform, marker draw.
2. Add line rasterization.
3. Produce RGBA output for one subplot.

Exit: `Axes.scatter/plot` produce deterministic image arrays.

### Iteration 3: Axes/Grid/Labels + Caching

1. Implement nice ticks + grid generation.
2. Add rules/labels overlay.
3. Add template caches and invalidation keys.

Exit: full subplot rendering with cached static layers.

### Iteration 4: App-Protocol Compiler

1. Convert RGBA to write batch payload.
2. Add integration test with runtime contract.
3. Validate performance for representative sizes.

Exit: plot can be submitted in app loop as a frame write.

### Iteration 5: Hardening and Extension Hooks

1. Benchmark and optimize downsampling and draw loops.
2. Add extensibility points for future series types.
3. Publish `v0.1` with docs/examples.

Exit: stable scatter + line baseline with clear extension boundary.

## 14. Open Decisions to Lock Before Coding

1. Exact write-batch object type and import boundary from app runtime.
2. Text rendering path for labels (reuse existing text renderer vs minimal plotting text raster path).
3. Default color/theme constants for plot styles.
4. Whether v0 includes multi-subplot figure layout or only single subplot.

Recommended default: single subplot only for v0 to keep performance work focused.
