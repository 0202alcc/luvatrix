from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MatrixViewport:
    """A display-sized view into a larger canonical Matrix buffer.

    Coordinates are in Matrix pixels.  Wrapping is opt-in per axis so normal
    scrolling remains bounds-checked while cyclic visualizations can reuse a
    resident texture without rewriting its pixels.
    """

    x: int
    y: int
    width: int
    height: int
    wrap_x: bool = False
    wrap_y: bool = False
