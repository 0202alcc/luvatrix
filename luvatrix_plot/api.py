from __future__ import annotations

from luvatrix_plot.display import (
    DEFAULT_ASPECT_RATIO,
    DEFAULT_DISPLAY_FRACTION,
    DEFAULT_MIN_HEIGHT,
    DEFAULT_MIN_WIDTH,
    resolve_default_figure_size,
)
from luvatrix_plot.figure import Figure


def figure(
    width: int | None = None,
    height: int | None = None,
    *,
    aspect_ratio: float = DEFAULT_ASPECT_RATIO,
    display_fraction: float = DEFAULT_DISPLAY_FRACTION,
    min_width: int = DEFAULT_MIN_WIDTH,
    min_height: int = DEFAULT_MIN_HEIGHT,
) -> Figure:
    if width is None and height is None:
        width, height = resolve_default_figure_size(
            aspect_ratio=aspect_ratio,
            display_fraction=display_fraction,
            min_width=min_width,
            min_height=min_height,
        )
    elif width is None and height is not None:
        if height <= 0:
            raise ValueError("height must be > 0")
        width = max(1, int(round(height * aspect_ratio)))
    elif width is not None and height is None:
        if width <= 0:
            raise ValueError("width must be > 0")
        height = max(1, int(round(width / aspect_ratio)))
    assert width is not None and height is not None
    return Figure(width=width, height=height)
