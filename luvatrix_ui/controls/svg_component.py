from __future__ import annotations

from dataclasses import dataclass, field

from luvatrix_ui.component_schema import BoundingBox, ComponentBase, CoordinatePoint

from .svg_renderer import SVGRenderBatch, SVGRenderCommand, SVGRenderer


@dataclass
class SVGComponent(ComponentBase):
    """First-party SVG component with explicit target render size."""

    svg_markup: str = ""
    position: CoordinatePoint = field(default_factory=lambda: CoordinatePoint(0.0, 0.0, None))
    width: float = 1.0
    height: float = 1.0
    opacity: float = 1.0
    _visual_bounds_cache: BoundingBox | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("SVGComponent width/height must be > 0")
        if self.opacity < 0.0 or self.opacity > 1.0:
            raise ValueError("SVGComponent opacity must be in [0, 1]")

    def _resolved_frame(self) -> str:
        return self.position.frame or self.default_frame

    def layout(self) -> tuple[SVGRenderCommand, BoundingBox]:
        frame = self._resolved_frame()
        command = SVGRenderCommand(
            component_id=self.component_id,
            svg_markup=self.svg_markup,
            x=self.position.x,
            y=self.position.y,
            width=self.width,
            height=self.height,
            frame=frame,
            opacity=self.opacity,
        )
        bounds = BoundingBox(
            x=self.position.x,
            y=self.position.y,
            width=self.width,
            height=self.height,
            frame=frame,
        )
        self._visual_bounds_cache = bounds
        return command, bounds

    def render(self, renderer: SVGRenderer) -> SVGRenderBatch:
        command, _ = self.layout()
        batch = SVGRenderBatch(commands=(command,))
        renderer.draw_svg_batch(batch)
        return batch

    def visual_bounds(self) -> BoundingBox:
        if self._visual_bounds_cache is None:
            return BoundingBox(
                x=self.position.x,
                y=self.position.y,
                width=self.width,
                height=self.height,
                frame=self._resolved_frame(),
            )
        return self._visual_bounds_cache
