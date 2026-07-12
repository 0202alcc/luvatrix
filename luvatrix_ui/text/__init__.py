"""Text interfaces and components for Luvatrix UI."""

from .component import TextComponent
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
from .wrapping import PreparedText, TextLayout, TextWrapping, WrappedLine, layout_text, prepare_text

__all__ = [
    "FontSpec",
    "TextAppearance",
    "TextComponent",
    "TextLayoutMetrics",
    "TextMeasureRequest",
    "TextRenderBatch",
    "TextRenderCommand",
    "TextRenderer",
    "TextSizeSpec",
    "TextWrapping",
    "PreparedText",
    "TextLayout",
    "WrappedLine",
    "prepare_text",
    "layout_text",
]
