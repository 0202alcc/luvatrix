from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import numpy as np


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


def compute_limits(x: np.ndarray, y: np.ndarray, mask: np.ndarray, y_buffer_ratio: float = 0.05) -> DataLimits:
    vx = x[mask]
    vy = y[mask]
    xmin = float(np.min(vx))
    xmax = float(np.max(vx))
    ymin = float(np.min(vy))
    ymax = float(np.max(vy))

    if ymin == ymax:
        delta = max(1.0, abs(ymin) * y_buffer_ratio)
        ymin -= delta
        ymax += delta
    else:
        span = ymax - ymin
        pad = span * y_buffer_ratio
        ymin -= pad
        ymax += pad

    if xmin == xmax:
        xmin -= 1.0
        xmax += 1.0

    return DataLimits(xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax)


def build_transform(limits: DataLimits, width: int, height: int) -> PlotTransform:
    if width <= 1 or height <= 1:
        raise ValueError("plot viewport width/height must be > 1")
    sx = (width - 1) / (limits.xmax - limits.xmin)
    tx = -limits.xmin * sx
    sy = (height - 1) / (limits.ymax - limits.ymin)
    ty = -limits.ymin * sy
    return PlotTransform(sx=sx, tx=tx, sy=sy, ty=ty)


def map_to_pixels(x: np.ndarray, y: np.ndarray, transform: PlotTransform, width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    px = np.rint(x * transform.sx + transform.tx).astype(np.int32)
    py = np.rint(y * transform.sy + transform.ty).astype(np.int32)
    py = (height - 1) - py
    np.clip(px, 0, width - 1, out=px)
    np.clip(py, 0, height - 1, out=py)
    return px, py


def downsample_by_pixel_column(
    px: np.ndarray,
    py: np.ndarray,
    *,
    width: int,
    mode: str,
) -> tuple[np.ndarray, np.ndarray]:
    if px.size <= width:
        return px, py

    buckets = [[] for _ in range(width)]
    for x_val, y_val in zip(px.tolist(), py.tolist(), strict=False):
        buckets[x_val].append(y_val)

    xs: list[int] = []
    ys: list[int] = []
    for col, values in enumerate(buckets):
        if not values:
            continue
        if mode == "markers":
            ys.append(int(values[len(values) // 2]))
            xs.append(col)
            continue
        ymin = min(values)
        ymax = max(values)
        xs.append(col)
        ys.append(int(ymin))
        if ymax != ymin:
            xs.append(col)
            ys.append(int(ymax))
    return np.asarray(xs, dtype=np.int32), np.asarray(ys, dtype=np.int32)


def generate_nice_ticks(vmin: float, vmax: float, target: int, preferred_step: float | None = None) -> np.ndarray:
    if target <= 0:
        raise ValueError("target must be > 0")
    if vmin == vmax:
        return np.asarray([vmin], dtype=np.float64)

    span = _nice_number(vmax - vmin, round_result=False)
    step = _nice_number(span / max(target - 1, 1), round_result=True)
    if preferred_step is not None and np.isfinite(preferred_step) and preferred_step > 0:
        # Use finer preferred step only if it doesn't explode label count.
        est_ticks = int(np.ceil((vmax - vmin) / preferred_step)) + 1
        if preferred_step < step and est_ticks <= max(target * 2, 12):
            step = preferred_step
    tick_min = np.floor(vmin / step) * step
    tick_max = np.ceil(vmax / step) * step

    ticks = np.arange(tick_min, tick_max + 0.5 * step, step, dtype=np.float64)
    # Normalize floating-point drift so values like -4.44e-16 become 0.
    ticks = np.rint(ticks / step) * step
    ticks[np.isclose(ticks, 0.0, rtol=0.0, atol=step * 1e-9)] = 0.0
    return ticks


def format_tick(value: float, *, step: float | None = None) -> str:
    if not np.isfinite(value):
        return str(value)
    if step is not None and np.isfinite(step) and step > 0 and abs(value) <= step * 1e-9:
        value = 0.0
    abs_v = abs(value)
    decimals = _decimals_from_step(step) if step is not None else 6
    if abs_v != 0 and (abs_v >= 1e6 or (step is not None and abs(step) < 1e-4) or abs_v < 1e-6):
        return f"{value:.4e}"

    d = Decimal(str(value))
    quant = Decimal("1").scaleb(-decimals)
    try:
        q = d.quantize(quant)
    except InvalidOperation:
        q = d
    out = format(q, "f")
    # Only trim trailing zeros for fractional values (preserve integer zeros like 30, 40).
    if "." in out:
        out = out.rstrip("0").rstrip(".")
    if out == "-0":
        out = "0"
    return out


def format_ticks_for_axis(ticks: np.ndarray) -> list[str]:
    if ticks.size == 0:
        return []
    if ticks.size == 1:
        return [format_tick(float(ticks[0]))]
    step = float(abs(ticks[1] - ticks[0]))
    return [format_tick(float(v), step=step) for v in ticks]


def infer_resolution(values: np.ndarray) -> float | None:
    if values.size < 2:
        return None
    finite = values[np.isfinite(values)]
    if finite.size < 2:
        return None
    uniq = np.unique(finite)
    if uniq.size < 2:
        return None
    diffs = np.diff(uniq)
    positive = diffs[diffs > 0]
    if positive.size == 0:
        return None
    span = float(uniq[-1] - uniq[0])
    eps = max(1e-12, span * 1e-9)
    significant = positive[positive > eps]
    if significant.size == 0:
        return None
    return float(np.min(significant))


def preferred_major_step_from_resolution(resolution: float | None) -> float | None:
    if resolution is None or not np.isfinite(resolution) or resolution <= 0:
        return None
    return _nice_number(resolution * 5.0, round_result=True)


def _nice_number(value: float, *, round_result: bool) -> float:
    exp = np.floor(np.log10(value))
    frac = value / (10**exp)

    if round_result:
        if frac < 1.5:
            nice_frac = 1.0
        elif frac < 3.0:
            nice_frac = 2.0
        elif frac < 7.0:
            nice_frac = 5.0
        else:
            nice_frac = 10.0
    else:
        if frac <= 1.0:
            nice_frac = 1.0
        elif frac <= 2.0:
            nice_frac = 2.0
        elif frac <= 5.0:
            nice_frac = 5.0
        else:
            nice_frac = 10.0

    return float(nice_frac * (10**exp))


def _decimals_from_step(step: float) -> int:
    if step <= 0 or not np.isfinite(step):
        return 6
    d = Decimal(str(step)).normalize()
    exp = d.as_tuple().exponent
    decimals = max(0, -int(exp))
    return min(12, decimals)
