from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from luvatrix_ui.component_schema import BoundingBox, ComponentBase, CoordinatePoint
from luvatrix_ui.text.renderer import FontSpec


@dataclass(frozen=True)
class StainedGlassButtonRenderCommand:
    component_id: str
    x: float
    y: float
    width: float
    height: float
    frame: str
    opacity: float = 1.0
    corner_radius_px: float = 18.0
    kernel_size: int = 9
    sigma_px: float = 3.0
    convolution_strength: float = 1.0
    scatter_sigma_px: float = 2.5
    refract_px: float = 2.0
    refract_calm_radius: float = 0.58
    refract_transition: float = 0.08
    chromatic_aberration_px: float = 0.5
    tint_delta_rgba: tuple[float, float, float, float] = (16.0, 20.0, 26.0, 0.0)
    color_filter_rgb: tuple[float, float, float] = (1.12, 0.56, 0.52)
    pane_mix: float = 0.42
    edge_highlight_alpha: float = 0.4
    depth_highlight_alpha: float = 0.28
    depth_shadow_alpha: float = 0.34
    rim_darken_alpha: float = 0.2
    label: str = ""
    label_color_hex: str = "#FFF8EE"
    label_font: FontSpec = field(default_factory=FontSpec)
    label_font_size_px: float = 20.0


@dataclass(frozen=True)
class StainedGlassButtonRenderBatch:
    commands: tuple[StainedGlassButtonRenderCommand, ...]


class StainedGlassButtonRenderer(Protocol):
    def draw_stained_glass_button_batch(self, batch: StainedGlassButtonRenderBatch) -> None:
        ...


@dataclass
class StainedGlassButtonComponent(ComponentBase):
    position: CoordinatePoint = field(default_factory=lambda: CoordinatePoint(0.0, 0.0, None))
    width: float = 1.0
    height: float = 1.0
    opacity: float = 1.0
    corner_radius_px: float = 18.0
    kernel_size: int = 9
    sigma_px: float = 3.0
    convolution_strength: float = 1.0
    scatter_sigma_px: float = 2.5
    refract_px: float = 2.0
    refract_calm_radius: float = 0.58
    refract_transition: float = 0.08
    chromatic_aberration_px: float = 0.5
    tint_delta_rgba: tuple[float, float, float, float] = (16.0, 20.0, 26.0, 0.0)
    color_filter_rgb: tuple[float, float, float] = (1.12, 0.56, 0.52)
    pane_mix: float = 0.42
    edge_highlight_alpha: float = 0.4
    depth_highlight_alpha: float = 0.28
    depth_shadow_alpha: float = 0.34
    rim_darken_alpha: float = 0.2
    label: str = ""
    label_color_hex: str = "#FFF8EE"
    label_font: FontSpec = field(default_factory=FontSpec)
    label_font_size_px: float = 20.0
    _visual_bounds_cache: BoundingBox | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("StainedGlassButtonComponent width/height must be > 0")
        if self.opacity < 0.0 or self.opacity > 1.0:
            raise ValueError("StainedGlassButtonComponent opacity must be in [0, 1]")
        if self.kernel_size < 3:
            raise ValueError("StainedGlassButtonComponent kernel_size must be >= 3")
        if self.kernel_size % 2 == 0:
            raise ValueError("StainedGlassButtonComponent kernel_size must be odd")

    def _resolved_frame(self) -> str:
        return self.position.frame or self.default_frame

    def layout(self) -> tuple[StainedGlassButtonRenderCommand, BoundingBox]:
        frame = self._resolved_frame()
        command = StainedGlassButtonRenderCommand(
            component_id=self.component_id,
            x=self.position.x,
            y=self.position.y,
            width=self.width,
            height=self.height,
            frame=frame,
            opacity=self.opacity,
            corner_radius_px=self.corner_radius_px,
            kernel_size=self.kernel_size,
            sigma_px=self.sigma_px,
            convolution_strength=self.convolution_strength,
            scatter_sigma_px=self.scatter_sigma_px,
            refract_px=self.refract_px,
            refract_calm_radius=self.refract_calm_radius,
            refract_transition=self.refract_transition,
            chromatic_aberration_px=self.chromatic_aberration_px,
            tint_delta_rgba=self.tint_delta_rgba,
            color_filter_rgb=self.color_filter_rgb,
            pane_mix=self.pane_mix,
            edge_highlight_alpha=self.edge_highlight_alpha,
            depth_highlight_alpha=self.depth_highlight_alpha,
            depth_shadow_alpha=self.depth_shadow_alpha,
            rim_darken_alpha=self.rim_darken_alpha,
            label=self.label,
            label_color_hex=self.label_color_hex,
            label_font=self.label_font,
            label_font_size_px=self.label_font_size_px,
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

    def render(self, renderer: StainedGlassButtonRenderer) -> StainedGlassButtonRenderBatch:
        command, _ = self.layout()
        batch = StainedGlassButtonRenderBatch(commands=(command,))
        renderer.draw_stained_glass_button_batch(batch)
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
