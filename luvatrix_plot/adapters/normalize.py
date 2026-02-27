from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import numpy as np

from luvatrix_plot.errors import PlotDataError
from luvatrix_plot.series import SeriesData


try:
    import pandas as pd
except Exception:  # pragma: no cover - optional dependency
    pd = None  # type: ignore[assignment]

try:
    import torch
except Exception:  # pragma: no cover - optional dependency
    torch = None  # type: ignore[assignment]


def normalize_xy(
    y: Any = None,
    *,
    x: Any = None,
    data: Any = None,
    source_name: str | None = None,
) -> SeriesData:
    y_values = _resolve_input(y=y, key="y", data=data)
    if y_values is None:
        raise PlotDataError("y input is required")

    y_arr = _coerce_1d_numeric(y_values, label="y")
    if y_arr.size == 0:
        raise PlotDataError("empty series")

    if x is None:
        x_arr = np.arange(y_arr.size, dtype=np.float64)
    else:
        x_values = _resolve_input(y=x, key="x", data=data)
        x_arr = _coerce_1d_numeric(x_values, label="x")

    if x_arr.shape != y_arr.shape:
        raise PlotDataError(f"x and y length mismatch: {x_arr.size} != {y_arr.size}")

    mask = np.isfinite(x_arr) & np.isfinite(y_arr)
    if not np.any(mask):
        raise PlotDataError("series contains no finite points")

    return SeriesData(x=x_arr, y=y_arr, mask=mask, source_name=source_name)


def _resolve_input(y: Any, key: str, data: Any) -> Any:
    if data is not None:
        if pd is None:
            raise PlotDataError("pandas is required when using `data=`")
        if not isinstance(data, pd.DataFrame):
            raise PlotDataError("`data` must be a pandas DataFrame")
        if isinstance(y, str):
            if y not in data.columns:
                raise PlotDataError(f"column not found: {y}")
            return data[y]
        if y is None:
            if key == "y":
                numeric_cols = [c for c in data.columns if _is_numeric_dtype(data[c])]
                if len(numeric_cols) != 1:
                    raise PlotDataError("when y is omitted, data must have exactly one numeric column")
                return data[numeric_cols[0]]
            return None
        return y

    if pd is not None and isinstance(y, pd.DataFrame):
        numeric_cols = [c for c in y.columns if _is_numeric_dtype(y[c])]
        if len(numeric_cols) != 1:
            raise PlotDataError("1-D DataFrame input must contain exactly one numeric column")
        return y[numeric_cols[0]]

    return y


def _is_numeric_dtype(series: Any) -> bool:
    if pd is None:
        return False
    try:
        return bool(pd.api.types.is_numeric_dtype(series))
    except Exception:
        return False


def _coerce_1d_numeric(value: Any, *, label: str) -> np.ndarray:
    if torch is not None and isinstance(value, torch.Tensor):
        tensor = value.detach()
        if tensor.ndim != 1:
            raise PlotDataError(f"{label} must be 1-D")
        if tensor.is_cuda:
            tensor = tensor.cpu()
        return tensor.to(torch.float64).numpy()

    if pd is not None and isinstance(value, pd.Series):
        if value.ndim != 1:
            raise PlotDataError(f"{label} must be 1-D")
        return _coerce_ndarray(value.to_numpy(), label=label)

    if isinstance(value, np.ndarray):
        if value.ndim != 1:
            raise PlotDataError(f"{label} must be 1-D")
        return _coerce_ndarray(value, label=label)

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return _coerce_ndarray(np.asarray(value, dtype=object), label=label)

    raise PlotDataError(f"unsupported {label} input type: {type(value)!r}")


def _coerce_ndarray(arr: np.ndarray, *, label: str) -> np.ndarray:
    if arr.dtype.kind in {"i", "u", "f", "b"}:
        return arr.astype(np.float64, copy=False)

    out = np.empty(arr.shape[0], dtype=np.float64)
    for i, raw in enumerate(arr.tolist()):
        if raw is None:
            out[i] = np.nan
            continue
        if isinstance(raw, Decimal):
            out[i] = float(raw)
            continue
        try:
            out[i] = float(raw)
        except Exception as exc:  # pragma: no cover - defensive
            raise PlotDataError(f"{label} contains non-numeric value at index {i}: {raw!r}") from exc
    return out
