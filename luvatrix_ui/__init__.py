"""First-party UI contracts and components for Luvatrix."""

from .component_schema import (
    BoundingBox,
    ComponentBase,
    CoordinatePoint,
    CoordinateTransformer,
    DisplayableArea,
    parse_coordinate_notation,
)
from .controls.button import ButtonModel, ButtonState
from .controls.interaction import HDIPressEvent, PressPhase, parse_hdi_press_event
from .controls.svg_component import SVGComponent
from .controls.svg_renderer import SVGRenderBatch, SVGRenderCommand, SVGRenderer
from .style.theme import ThemeTokens, validate_theme_tokens
from .text.component import TextComponent
from .text.renderer import (
    FontSpec,
    TextAppearance,
    TextLayoutMetrics,
    TextMeasureRequest,
    TextRenderBatch,
    TextRenderCommand,
    TextRenderer,
    TextSizeSpec,
)
from .ui_ir import (
    ComponentSemantics,
    ComponentTransform,
    CoordinateFrameSpec,
    Insets,
    InteractionBinding,
    MatrixSpec,
    UIIRAsset,
    UIIRComponent,
    UIIRPage,
    default_ui_ir_page_schema,
    validate_ui_ir_payload,
)

__all__ = [
    "BoundingBox",
    "ButtonModel",
    "ButtonState",
    "ComponentBase",
    "CoordinatePoint",
    "CoordinateTransformer",
    "DisplayableArea",
    "FontSpec",
    "HDIPressEvent",
    "PressPhase",
    "SVGComponent",
    "SVGRenderBatch",
    "SVGRenderCommand",
    "SVGRenderer",
    "TextAppearance",
    "TextComponent",
    "TextLayoutMetrics",
    "TextMeasureRequest",
    "TextRenderBatch",
    "TextRenderCommand",
    "TextRenderer",
    "TextSizeSpec",
    "ThemeTokens",
    "UIIRAsset",
    "UIIRComponent",
    "UIIRPage",
    "ComponentSemantics",
    "ComponentTransform",
    "CoordinateFrameSpec",
    "InteractionBinding",
    "Insets",
    "MatrixSpec",
    "default_ui_ir_page_schema",
    "parse_coordinate_notation",
    "parse_hdi_press_event",
    "validate_ui_ir_payload",
    "validate_theme_tokens",
]
