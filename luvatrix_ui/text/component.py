from __future__ import annotations

from dataclasses import dataclass, field

from luvatrix_ui.component_schema import BoundingBox, ComponentBase, CoordinatePoint, CoordinateTransformer, DisplayableArea

from .renderer import (
    FontSpec,
    TextAppearance,
    TextLayoutMetrics,
    TextMeasureRequest,
    TextRenderBatch,
    TextRenderCommand,
    TextRenderer,
    TextSizeSpec,
)


@dataclass
class TextComponent(ComponentBase):
    """First-party text component.

    - Uses full-string batch commands (no per-character draw loop in component contract).
    - Visual bounds are derived from measured text by default.
    - Interaction bounds may be overridden independently.
    """

    text: str = ""
    position: CoordinatePoint = field(default_factory=lambda: CoordinatePoint(0.0, 0.0, None))
    font: FontSpec = field(default_factory=FontSpec)
    size: TextSizeSpec = field(default_factory=TextSizeSpec)
    appearance: TextAppearance = field(default_factory=TextAppearance)
    max_width_px: float | None = None
    _visual_bounds_cache: BoundingBox | None = field(default=None, init=False, repr=False)

    def _resolved_frame(self) -> str:
        return self.position.frame or self.default_frame

    def _resolved_xy(self, transformer: CoordinateTransformer | None = None) -> tuple[float, float]:
        _ = transformer
        return (self.position.x, self.position.y)

    def _measure(self, renderer: TextRenderer, display: DisplayableArea) -> tuple[float, TextLayoutMetrics]:
        font_size_px = self.size.resolve_px(display)
        req = TextMeasureRequest(
            text=self.text,
            font=self.font,
            font_size_px=font_size_px,
            appearance=self.appearance,
            max_width_px=self.max_width_px,
        )
        return font_size_px, renderer.measure_text(req)

    def layout(
        self,
        renderer: TextRenderer,
        display: DisplayableArea,
        *,
        transformer: CoordinateTransformer | None = None,
    ) -> tuple[TextRenderCommand, BoundingBox]:
        font_size_px, metrics = self._measure(renderer, display)
        x, y = self._resolved_xy(transformer)
        frame = self._resolved_frame()
        command = TextRenderCommand(
            component_id=self.component_id,
            text=self.text,
            x=x,
            y=y,
            frame=frame,
            font=self.font,
            font_size_px=font_size_px,
            appearance=self.appearance,
            max_width_px=self.max_width_px,
        )
        visual_bounds = BoundingBox(
            x=x,
            y=y,
            width=float(metrics.width_px),
            height=float(metrics.height_px),
            frame=frame,
        )
        self._visual_bounds_cache = visual_bounds
        return command, visual_bounds

    def render(
        self,
        renderer: TextRenderer,
        display: DisplayableArea,
        *,
        transformer: CoordinateTransformer | None = None,
    ) -> TextRenderBatch:
        command, _ = self.layout(renderer, display, transformer=transformer)
        batch = TextRenderBatch(commands=(command,))
        renderer.draw_text_batch(batch)
        return batch

    def visual_bounds(self) -> BoundingBox:
        if self._visual_bounds_cache is None:
            return BoundingBox(
                x=self.position.x,
                y=self.position.y,
                width=0.0,
                height=0.0,
                frame=self._resolved_frame(),
            )
        return self._visual_bounds_cache
