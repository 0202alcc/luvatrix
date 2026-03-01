from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np


SeriesMode = Literal["markers", "lines", "lines+markers", "bars", "bars-horizontal"]


@dataclass(frozen=True)
class SeriesData:
    x: np.ndarray
    y: np.ndarray
    mask: np.ndarray
    source_name: str | None = None


@dataclass(frozen=True)
class SeriesStyle:
    mode: SeriesMode
    color: tuple[int, int, int, int] = (62, 149, 255, 255)
    marker_size: int = 1
    line_width: int = 1
    bar_width: float = 0.8


@dataclass(frozen=True)
class SeriesSpec:
    data: SeriesData
    style: SeriesStyle
    label: str | None = None
