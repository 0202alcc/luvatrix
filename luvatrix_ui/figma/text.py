from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .geometry import Affine, Coverage, Rect, intersect

BUNDLED_FONT_DIR = Path(__file__).resolve().parent / "fonts"
DEFAULT_FAMILY = "Inter"
# Below this overflow the clipped-away part is a glyph sliver; an ellipsis
# (which drops a whole word) reads worse than the shave.
_ELLIPSIS_MIN_OVERFLOW_PX = 12.0
SYSTEM_FONT_DIRS = (
    "/System/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
    "/Library/Fonts",
    "~/Library/Fonts",
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "~/.fonts",
    "~/.local/share/fonts",
)
_FONT_SUFFIXES = (".ttf", ".otf", ".ttc")
_WEIGHT_NAMES = {
    100: ("thin", "hairline"),
    200: ("extralight", "ultralight"),
    300: ("light",),
    400: ("regular", "book", "normal", ""),
    500: ("medium",),
    600: ("semibold", "demibold"),
    700: ("bold",),
    800: ("extrabold", "ultrabold"),
    900: ("black", "heavy"),
}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


class FontLibrary:
    """Resolves Figma (family, weight, italic) triples to font files."""

    def __init__(self, dirs: Iterable[str | Path] = (), *, include_system: bool = True) -> None:
        search: list[Path] = [Path(d).expanduser() for d in dirs]
        env = os.environ.get("LUVATRIX_FONT_DIRS", "")
        search.extend(Path(p).expanduser() for p in env.split(os.pathsep) if p)
        search.append(BUNDLED_FONT_DIR)
        if include_system:
            search.extend(Path(p).expanduser() for p in SYSTEM_FONT_DIRS)
        self._index: dict[str, Path] = {}
        for directory in search:
            self._scan(directory)
        self._fonts: dict[tuple[Path | None, float], Any] = {}

    def _scan(self, directory: Path, depth: int = 0) -> None:
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return
        for entry in entries:
            try:
                if entry.is_dir():
                    if depth < 3:
                        self._scan(entry, depth + 1)
                elif entry.suffix.lower() in _FONT_SUFFIXES:
                    self._index.setdefault(_norm(entry.stem), entry)
            except OSError:
                continue

    def resolve(self, family: str, weight: float = 400, italic: bool = False) -> Path | None:
        for fam in (family, DEFAULT_FAMILY):
            path = self._resolve_family(fam, weight, italic)
            if path is not None:
                return path
        return None

    def _resolve_family(self, family: str, weight: float, italic: bool) -> Path | None:
        fam = _norm(family)
        if not fam:
            return None
        target = int(round(float(weight) / 100.0) * 100) if weight else 400
        order = sorted(_WEIGHT_NAMES, key=lambda w: (abs(w - target), -w if target >= 400 else w))
        styles = ("italic", "") if italic else ("",)
        for style in styles:
            for w in order:
                for name in _WEIGHT_NAMES[w]:
                    key = fam + name + style
                    if w == 400 and style and not name:
                        key = fam + style
                    if key in self._index:
                        return self._index[key]
        return None

    def font(self, path: Path | None, size_px: float) -> Any:
        key = (path, round(size_px, 2))
        cached = self._fonts.get(key)
        if cached is not None:
            return cached
        font: Any
        if path is None:
            try:
                font = ImageFont.load_default(size=size_px)
            except TypeError:
                font = ImageFont.load_default()
        else:
            try:
                font = ImageFont.truetype(str(path), size_px)
            except (TypeError, ValueError):
                font = ImageFont.truetype(str(path), max(1, int(round(size_px))))
        self._fonts[key] = font
        return font


@dataclass(frozen=True)
class _Style:
    family: str
    weight: float
    italic: bool
    size: float
    letter_spacing: float
    line_height: float
    paragraph_spacing: float
    decoration: str
    fills_key: str
    fills: tuple[dict[str, Any], ...]


@dataclass
class _Piece:
    text: str
    style: _Style
    width: float


def _make_style(base: dict[str, Any], override: dict[str, Any] | None, node_fills: Sequence[dict[str, Any]]) -> _Style:
    merged = dict(base)
    if override:
        merged.update({k: v for k, v in override.items() if k != "fills"})
    fills = tuple((override or {}).get("fills") or node_fills or ())
    size = float(merged.get("fontSize", 14.0) or 14.0)
    lh = merged.get("lineHeightPx")
    unit = str(merged.get("lineHeightUnit", "PIXELS"))
    if override and "lineHeightPx" not in override and "fontSize" in override and unit != "PIXELS":
        lh = None
    if lh is None:
        pct = merged.get("lineHeightPercentFontSize")
        lh = size * (float(pct) / 100.0 if pct else 1.21)
    return _Style(
        family=str(merged.get("fontFamily", DEFAULT_FAMILY) or DEFAULT_FAMILY),
        weight=float(merged.get("fontWeight", 400) or 400),
        italic=bool(merged.get("italic", False)),
        size=size,
        letter_spacing=float(merged.get("letterSpacing", 0.0) or 0.0),
        line_height=float(lh),
        paragraph_spacing=float(merged.get("paragraphSpacing", 0.0) or 0.0),
        decoration=str(merged.get("textDecoration", "NONE") or "NONE"),
        fills_key=json.dumps(fills, sort_keys=True),
        fills=fills,
    )


def truncate_pieces_to_width(
    pieces: list[_Piece],
    avail: float,
    ellipsis: _Piece,
) -> list[_Piece]:
    """Fit styled pieces into ``avail`` device px, ending with ``ellipsis``.

    Drops whole trailing pieces (never splits a piece) until the ellipsis
    fits. Returns ``pieces`` unchanged when the line already fits, ``[]`` when
    even the ellipsis alone does not fit.
    """
    total = sum(piece.width for piece in pieces)
    if total <= avail:
        return pieces
    kept = list(pieces)
    while kept and sum(piece.width for piece in kept) + ellipsis.width > avail:
        kept.pop()
    if not kept and ellipsis.width > avail:
        return []
    return [*kept, ellipsis]


def _fit_line_count(metrics: list[tuple[float, float, float, float]], box_px: float) -> int:
    """How many lines fit in a fixed-height box (at least one)."""
    total = 0.0
    for i, (lh, _asc, _desc, gap) in enumerate(metrics):
        total += lh + (gap if i else 0.0)
        if total > box_px + 0.5 and i > 0:
            return i
    return len(metrics)


def _apply_case(text: str, case: str | None) -> str:
    if case == "UPPER":
        return text.upper()
    if case == "LOWER":
        return text.lower()
    if case == "TITLE":
        return text.title()
    return text


def text_coverages(
    node: dict[str, Any],
    tf: Affine,
    size: tuple[float, float],
    clip: Rect,
    fonts: FontLibrary,
) -> list[tuple[Coverage, tuple[dict[str, Any], ...]]]:
    """Rasterize a TEXT node into one coverage mask per distinct fill set."""
    base = dict(node.get("style") or {})
    chars = _apply_case(str(node.get("characters", "")), base.get("textCase"))
    if not chars:
        return []
    node_fills = tuple(node.get("fills") or ())
    table = node.get("styleOverrideTable") or {}
    overrides = list(node.get("characterStyleOverrides") or ())
    style_cache: dict[Any, _Style] = {}

    def style_at(i: int) -> _Style:
        key = overrides[i] if i < len(overrides) else 0
        if key not in style_cache:
            style_cache[key] = _make_style(base, table.get(str(key)) if key else None, node_fills)
        return style_cache[key]

    s = tf.mean_scale
    box_w, box_h = size
    wrap = str(base.get("textAutoResize", "NONE")) != "WIDTH_AND_HEIGHT"
    limit = box_w * s * 1.02 + 1.0 if wrap else math.inf

    def font_for(style: _Style) -> Any:
        return fonts.font(fonts.resolve(style.family, style.weight, style.italic), style.size * s)

    def measure(text: str, style: _Style) -> float:
        if not text:
            return 0.0
        return float(font_for(style).getlength(text)) + style.letter_spacing * s * len(text)

    # Split into words that carry their trailing whitespace; a word may span styles.
    words: list[list[_Piece]] = []
    breaks_after: list[bool] = []
    for match in re.finditer(r"\n|[^ \n]+ *| +", chars):
        if match.group() == "\n":
            words.append([])
            breaks_after.append(True)
            continue
        pieces: list[_Piece] = []
        start = match.start()
        for k in range(match.start() + 1, match.end() + 1):
            if k == match.end() or style_at(k) is not style_at(start):
                seg = chars[start:k]
                pieces.append(_Piece(seg, style_at(start), measure(seg, style_at(start))))
                start = k
        words.append(pieces)
        breaks_after.append(False)

    lines: list[tuple[list[_Piece], bool]] = []
    line: list[_Piece] = []
    width = 0.0
    for pieces, hard in zip(words, breaks_after):
        word_w = sum(p.width for p in pieces)
        trimmed_w = word_w - sum(measure(p.text[len(p.text.rstrip(" ")) :], p.style) for p in pieces[-1:])
        if line and width + trimmed_w > limit:
            lines.append((line, False))
            line, width = [], 0.0
        if not line and trimmed_w > limit:
            for piece in pieces:
                for ch in piece.text:
                    cw = measure(ch, piece.style)
                    if line and width + cw > limit and ch != " ":
                        lines.append((line, False))
                        line, width = [], 0.0
                    line.append(_Piece(ch, piece.style, cw))
                    width += cw
        else:
            line.extend(pieces)
            width += word_w
        if hard:
            lines.append((line, True))
            line, width = [], 0.0
    if line:
        lines.append((line, True))

    base_style = style_at(0)
    metrics = []
    for pieces, hard in lines:
        styles = [p.style for p in pieces] or [base_style]
        lh = max(st.line_height for st in styles) * s
        asc = max(font_for(st).getmetrics()[0] for st in styles)
        desc = max(font_for(st).getmetrics()[1] for st in styles)
        gap = max(st.paragraph_spacing for st in styles) * s if hard else 0.0
        metrics.append((lh, asc, desc, gap))

    limit = int(base.get("maxLines", 0) or 0) if str(base.get("textTruncation", "") or "").upper() == "ENDING" else 0
    if limit <= 0 and str(base.get("textAutoResize", "NONE")) == "NONE" and box_h > 0:
        limit = _fit_line_count(metrics, box_h * s)
    if limit > 0 and len(lines) > limit:
        lines = lines[:limit]
        metrics = metrics[:limit]
        pieces = lines[-1][0]
        if pieces:
            style = pieces[-1].style
            pieces.append(_Piece("…", style, measure("…", style)))

    total_h = 0.0
    for lh, _asc, _desc, gap in metrics:
        total_h += lh + gap
    if metrics:
        total_h -= metrics[-1][3]

    valign = str(base.get("textAlignVertical", "TOP"))
    halign = str(base.get("textAlignHorizontal", "LEFT"))
    aligned_tf = abs(tf.b) < 1e-6 and abs(tf.c) < 1e-6
    pad = int(math.ceil(max(st.size for st in style_cache.values()) * s)) + 2
    img_w = int(math.ceil(box_w * s)) + 2 * pad
    img_h = int(math.ceil(max(box_h * s, total_h))) + 2 * pad
    y = {"CENTER": (box_h * s - total_h) / 2, "BOTTOM": box_h * s - total_h}.get(valign, 0.0)
    layers: dict[str, tuple[Image.Image, tuple[dict[str, Any], ...]]] = {}

    for (pieces, _hard), (lh, asc, desc, gap) in zip(lines, metrics):
        visible = list(pieces)
        while visible and not visible[-1].text.strip(" "):
            visible.pop()
        if visible:
            last = visible[-1]
            stripped = last.text.rstrip(" ")
            visible[-1] = _Piece(stripped, last.style, measure(stripped, last.style))
        line_w = sum(p.width for p in visible)
        x = {"CENTER": (box_w * s - line_w) / 2, "RIGHT": box_w * s - line_w}.get(halign, 0.0)
        if aligned_tf and visible:
            # The compiled text box can be wider than the clip ancestor
            # (nowrap spans in flex/table rows); truncate with an ellipsis at
            # the clip boundary instead of cutting a glyph mid-stroke. The
            # draw offset x is already in device px, so the glyphs start at
            # tf.tx + x.
            start_dev = tf.tx + x
            if start_dev + line_w > clip[2] + _ELLIPSIS_MIN_OVERFLOW_PX:
                ellipsis_style = visible[-1].style
                ellipsis = _Piece("…", ellipsis_style, measure("…", ellipsis_style))
                visible = truncate_pieces_to_width(visible, clip[2] - start_dev, ellipsis) or visible
        baseline = y + (lh - (asc + desc)) / 2 + asc
        for piece in visible:
            if piece.style.fills_key not in layers:
                layers[piece.style.fills_key] = (Image.new("L", (img_w, img_h), 0), piece.style.fills)
            canvas = layers[piece.style.fills_key][0]
            _draw_piece(ImageDraw.Draw(canvas), piece, font_for(piece.style), pad + x, pad + baseline, s)
            x += piece.width
        y += lh + gap

    to_device = tf @ Affine.scale(1.0 / s) @ Affine.translate(-pad, -pad)
    out = []
    for img, fills in layers.values():
        cov = _place(img, to_device, clip)
        if cov is not None:
            out.append((cov, fills))
    return out


def _draw_piece(draw: ImageDraw.ImageDraw, piece: _Piece, font: Any, x: float, baseline: float, s: float) -> None:
    spacing = piece.style.letter_spacing * s
    if abs(spacing) < 1e-3:
        draw.text((x, baseline), piece.text, font=font, fill=255, anchor="ls")
    else:
        cx = x
        for ch in piece.text:
            draw.text((cx, baseline), ch, font=font, fill=255, anchor="ls")
            cx += float(font.getlength(ch)) + spacing
    if piece.style.decoration in {"UNDERLINE", "STRIKETHROUGH"} and piece.text.strip():
        thickness = max(1.0, piece.style.size * s / 14.0)
        offset = thickness * 1.5 if piece.style.decoration == "UNDERLINE" else -piece.style.size * s * 0.3
        ly = baseline + offset
        draw.rectangle([x, ly, x + piece.width, ly + thickness], fill=255)


def _place(img: Image.Image, to_device: Affine, clip: Rect) -> Coverage | None:
    w, h = img.size
    aligned = abs(to_device.b) < 1e-6 and abs(to_device.c) < 1e-6 and abs(to_device.a - 1) < 1e-6 and abs(to_device.d - 1) < 1e-6
    if aligned:
        x0, y0 = int(round(to_device.tx)), int(round(to_device.ty))
        mask = np.asarray(img, dtype=np.float32) / 255.0
        rect = intersect((x0, y0, x0 + w, y0 + h), clip)
        if rect is None:
            return None
        sub = mask[rect[1] - y0 : rect[3] - y0, rect[0] - x0 : rect[2] - x0]
        return Coverage(rect[0], rect[1], np.ascontiguousarray(sub))
    bx0, by0, bx1, by1 = to_device.bounds(0, 0, w, h)
    rect = intersect((int(math.floor(bx0)), int(math.floor(by0)), int(math.ceil(bx1)), int(math.ceil(by1))), clip)
    if rect is None:
        return None
    inv = to_device.inverse() @ Affine.translate(rect[0], rect[1])
    out = img.transform(
        (rect[2] - rect[0], rect[3] - rect[1]),
        Image.AFFINE,
        data=(inv.a, inv.c, inv.tx, inv.b, inv.d, inv.ty),
        resample=Image.BILINEAR,
    )
    return Coverage(rect[0], rect[1], np.asarray(out, dtype=np.float32) / 255.0)
