from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SVGRenderCommand:
    """Backend-agnostic SVG render instruction.

    Width/height are explicit target raster bounds; renderer should rasterize vector
    data directly at this target size (no intermediate bitmap up/down-sampling).
    """

    component_id: str
    svg_markup: str
    x: float
    y: float
    width: float
    height: float
    frame: str
    opacity: float = 1.0


@dataclass(frozen=True)
class SVGRenderBatch:
    commands: tuple[SVGRenderCommand, ...]


class SVGRenderer(Protocol):
    """Backend-agnostic SVG renderer interface for component paint calls."""

    def draw_svg_batch(self, batch: SVGRenderBatch) -> None:
        ...
