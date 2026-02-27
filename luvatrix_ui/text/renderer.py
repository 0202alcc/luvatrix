from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from luvatrix_ui.component_schema import DisplayableArea


FontSlant = Literal["regular", "italic", "oblique"]
TextSizeUnit = Literal[
    "px",
    "ratio_display_height",
    "ratio_display_width",
    "ratio_display_min",
    "ratio_display_max",
]


@dataclass(frozen=True)
class FontSpec:
    """Font definition from either system lookup or explicit file path.

    If `file_path` is set, renderer should prefer file-backed font loading.
    """

    family: str = "Comic Mono"
    file_path: str | None = None
    weight: int = 400
    slant: FontSlant = "regular"

    def __post_init__(self) -> None:
        if not self.family.strip() and self.file_path is None:
            raise ValueError("FontSpec requires `family` when `file_path` is not set")
        if self.file_path is not None and not str(self.file_path).strip():
            raise ValueError("FontSpec `file_path` must be non-empty when provided")
        if self.weight < 1 or self.weight > 1000:
            raise ValueError("FontSpec `weight` must be in [1, 1000]")

    @property
    def source_kind(self) -> Literal["system", "file"]:
        return "file" if self.file_path else "system"

    @property
    def normalized_file_path(self) -> Path | None:
        if self.file_path is None:
            return None
        return Path(self.file_path)


@dataclass(frozen=True)
class TextSizeSpec:
    unit: TextSizeUnit = "px"
    value: float = 14.0

    def resolve_px(self, display: DisplayableArea) -> float:
        if self.value <= 0:
            raise ValueError("Text size value must be > 0")
        if self.unit == "px":
            return self.value
        if self.unit == "ratio_display_height":
            return display.content_height_px * self.value
        if self.unit == "ratio_display_width":
            return display.content_width_px * self.value
        if self.unit == "ratio_display_min":
            return min(display.content_height_px, display.content_width_px) * self.value
        if self.unit == "ratio_display_max":
            return max(display.content_height_px, display.content_width_px) * self.value
        raise ValueError(f"unknown text size unit: {self.unit}")


@dataclass(frozen=True)
class TextAppearance:
    color_hex: str = "#111111"
    opacity: float = 1.0
    letter_spacing_px: float = 0.0
    line_height_multiplier: float = 1.2
    underline: bool = False
    strike: bool = False

    def __post_init__(self) -> None:
        if self.opacity < 0.0 or self.opacity > 1.0:
            raise ValueError("TextAppearance opacity must be in [0, 1]")
        if self.line_height_multiplier <= 0:
            raise ValueError("TextAppearance line_height_multiplier must be > 0")


@dataclass(frozen=True)
class TextMeasureRequest:
    text: str
    font: FontSpec
    font_size_px: float
    appearance: TextAppearance
    max_width_px: float | None = None


@dataclass(frozen=True)
class TextLayoutMetrics:
    width_px: float
    height_px: float
    baseline_px: float
    line_count: int = 1


@dataclass(frozen=True)
class TextRenderCommand:
    component_id: str
    text: str
    x: float
    y: float
    frame: str
    font: FontSpec
    font_size_px: float
    appearance: TextAppearance
    max_width_px: float | None = None


@dataclass(frozen=True)
class TextRenderBatch:
    """Render list for a single pass; backends should draw in one batch call."""

    commands: tuple[TextRenderCommand, ...]


class TextRenderer(Protocol):
    """Backend-agnostic text renderer that supports batched full-string commands."""

    def measure_text(self, request: TextMeasureRequest) -> TextLayoutMetrics:
        ...

    def draw_text_batch(self, batch: TextRenderBatch) -> None:
        ...
