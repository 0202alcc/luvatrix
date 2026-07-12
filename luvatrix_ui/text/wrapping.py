"""Prepared multiline text layout inspired by chenglou/pretext (MIT).

Architecture reference: https://github.com/chenglou/pretext

The layout engine is renderer-neutral: callers measure graphemes once during
preparation, then may lay out the immutable result at many widths without
touching the font backend again.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Literal
import unicodedata


WhiteSpace = Literal["normal", "pre-wrap"]
WordBreak = Literal["normal", "keep-all"]


@dataclass(frozen=True)
class TextWrapping:
    mode: Literal["pretext"] = "pretext"
    white_space: WhiteSpace = "normal"
    word_break: WordBreak = "normal"

    def __post_init__(self) -> None:
        if self.mode != "pretext":
            raise ValueError("TextWrapping mode must be 'pretext'")
        if self.white_space not in {"normal", "pre-wrap"}:
            raise ValueError("white_space must be 'normal' or 'pre-wrap'")
        if self.word_break not in {"normal", "keep-all"}:
            raise ValueError("word_break must be 'normal' or 'keep-all'")


@dataclass(frozen=True)
class PreparedToken:
    text: str
    graphemes: tuple[str, ...]
    grapheme_widths: tuple[float, ...]
    width_px: float
    kind: Literal["word", "space", "break"]


@dataclass(frozen=True)
class PreparedText:
    text: str
    wrapping: TextWrapping
    tokens: tuple[PreparedToken, ...]
    natural_width_px: float


@dataclass(frozen=True)
class WrappedLine:
    text: str
    width_px: float


@dataclass(frozen=True)
class TextLayout:
    lines: tuple[WrappedLine, ...]
    width_px: float
    height_px: float
    line_height_px: float

    @property
    def line_count(self) -> int:
        return len(self.lines)


def prepare_text(
    text: str,
    *,
    measure: Callable[[str], float],
    wrapping: TextWrapping | None = None,
) -> PreparedText:
    """Segment and measure text once for subsequent width-only layouts."""
    wrapping = wrapping or TextWrapping()
    raw_tokens = _tokenize(str(text), wrapping.white_space)
    prepared: list[PreparedToken] = []
    natural_line_width = 0.0
    natural_width = 0.0
    for value, kind in raw_tokens:
        if kind == "break":
            prepared.append(PreparedToken("", (), (), 0.0, "break"))
            natural_width = max(natural_width, natural_line_width)
            natural_line_width = 0.0
            continue
        graphemes = _graphemes(value)
        widths = tuple(_measured_width(measure, grapheme) for grapheme in graphemes)
        width = _measured_width(measure, value)
        prepared.append(PreparedToken(value, graphemes, widths, width, kind))
        natural_line_width += width
    natural_width = max(natural_width, natural_line_width)
    return PreparedText(str(text), wrapping, tuple(prepared), natural_width)


def layout_text(prepared: PreparedText, *, max_width_px: float, line_height_px: float) -> TextLayout:
    """Lay out prepared text using cached widths only."""
    max_width = float(max_width_px)
    line_height = float(line_height_px)
    if not math.isfinite(max_width) or not math.isfinite(line_height):
        raise ValueError("max_width_px and line_height_px must be finite")
    if max_width <= 0:
        raise ValueError("max_width_px must be > 0")
    if line_height <= 0:
        raise ValueError("line_height_px must be > 0")
    if not prepared.tokens:
        return TextLayout((), 0.0, 0.0, line_height)

    lines: list[WrappedLine] = []
    parts: list[str] = []
    width = 0.0

    def flush(*, preserve_empty: bool = False) -> None:
        nonlocal parts, width
        text = "".join(parts)
        if text or preserve_empty:
            lines.append(WrappedLine(text, width))
        parts = []
        width = 0.0

    pending_space: PreparedToken | None = None
    for token in prepared.tokens:
        if token.kind == "break":
            if pending_space is not None and prepared.wrapping.white_space == "pre-wrap":
                parts.append(pending_space.text)
                width += pending_space.width_px
            pending_space = None
            flush(preserve_empty=True)
            continue
        if token.kind == "space" and prepared.wrapping.white_space == "normal":
            pending_space = token if parts else None
            continue

        prefix_text = pending_space.text if pending_space is not None else ""
        prefix_width = pending_space.width_px if pending_space is not None else 0.0
        pending_space = None
        required = prefix_width + token.width_px
        if parts and width + required > max_width:
            flush()
            prefix_text = ""
            prefix_width = 0.0

        if token.width_px <= max_width:
            parts.extend((prefix_text, token.text))
            width += prefix_width + token.width_px
            continue

        if prefix_text and parts:
            parts.append(prefix_text)
            width += prefix_width
        for grapheme, grapheme_width in zip(token.graphemes, token.grapheme_widths, strict=True):
            if parts and width + grapheme_width > max_width:
                flush()
            parts.append(grapheme)
            width += grapheme_width

    if pending_space is not None and prepared.wrapping.white_space == "pre-wrap":
        parts.append(pending_space.text)
        width += pending_space.width_px
    if prepared.tokens[-1].kind == "break":
        lines.append(WrappedLine("", 0.0))
    else:
        flush()
    widest = max((line.width_px for line in lines), default=0.0)
    return TextLayout(tuple(lines), widest, len(lines) * line_height, line_height)


def _tokenize(text: str, white_space: WhiteSpace) -> list[tuple[str, Literal["word", "space", "break"]]]:
    if not text:
        return []
    if white_space == "normal":
        words = text.split()
        result: list[tuple[str, Literal["word", "space", "break"]]] = []
        for index, word in enumerate(words):
            if index:
                result.append((" ", "space"))
            result.append((word, "word"))
        return result

    result = []
    buffer: list[str] = []
    kind: Literal["word", "space"] | None = None
    for char in text:
        if char == "\n":
            if buffer and kind is not None:
                result.append(("".join(buffer), kind))
            buffer = []
            kind = None
            result.append(("", "break"))
            continue
        next_kind: Literal["word", "space"] = "space" if char.isspace() else "word"
        if kind is not None and next_kind != kind:
            result.append(("".join(buffer), kind))
            buffer = []
        kind = next_kind
        buffer.append(char)
    if buffer and kind is not None:
        result.append(("".join(buffer), kind))
    return result


def _graphemes(text: str) -> tuple[str, ...]:
    clusters: list[str] = []
    regional_count = 0
    for char in text:
        code = ord(char)
        combining = unicodedata.combining(char) != 0
        modifier = 0x1F3FB <= code <= 0x1F3FF
        variation = 0xFE00 <= code <= 0xFE0F
        regional = 0x1F1E6 <= code <= 0x1F1FF
        joins_previous = combining or modifier or variation or char == "\u200d"
        if clusters and clusters[-1].endswith("\u200d"):
            joins_previous = True
        if regional:
            joins_previous = bool(clusters and regional_count % 2 == 1)
            regional_count += 1
        else:
            regional_count = 0
        if clusters and joins_previous:
            clusters[-1] += char
        else:
            clusters.append(char)
    return tuple(clusters)


def _measured_width(measure: Callable[[str], float], text: str) -> float:
    width = float(measure(text))
    if not math.isfinite(width):
        raise ValueError("text measurements must be finite")
    return max(0.0, width)
