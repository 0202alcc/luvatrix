"""Per-glyph font fallback for the PIL/FreeType text paths.

Live Mac bug (round 9): the scene text paths load ONE font file per family,
so FreeType draws .notdef (an empty box) for any glyph outside that font's
coverage — playlist names with CJK/emoji/symbols render as "[][]shamu[][]".
There is no Core Text underneath to cascade for us (rasterization is PIL),
so the cascade lives here: a primary font plus a platform-curated list of
fallback font files, picking the first font that actually covers each glyph.

Coverage is detected by comparing a char's rendered mask against the font's
own .notdef rendering (a noncharacter sentinel) — FreeType has no public
charmap API through Pillow. Color bitmap fonts (Apple Color Emoji,
NotoColorEmoji) only load at their native bitmap strikes, so they are loaded
at the strike size and their renders scaled down to the requested px.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SENTINEL = "\uFFFE"  # noncharacter: renders as the font's .notdef

# Bitmap-only color emoji fonts expose discrete strikes; loading at any other
# size raises. Requested size is tried first, then known strikes.
_BITMAP_STRIKES = (20, 32, 40, 48, 64, 96, 109, 128, 160)

_FALLBACK_BASENAMES = {
    "darwin": (
        "applesymbols",      # math brackets, decorative symbols
        "hiraginosans",      # CJK + fullwidth brackets 【】
        "stheiti",
        "arialunicode",
        "arial",
        "helvetica",
        "applecoloremoji",   # bitmap strikes only — last resort
    ),
    "linux": (
        "notosanssymbols2",
        "notosanssymbols",
        "dejavusans",
        "wqymicrohei",
        "notosanscjk",
        "notocoloremoji",    # bitmap strikes only — last resort
    ),
}


def _norm(text: str) -> str:
    return text.lower().replace(" ", "").replace("-", "").replace("_", "")


def _font_dirs() -> list[Path]:
    import os

    py_packages_dir = Path(__file__).resolve().parents[2]
    dirs = [
        Path(item)
        for item in os.getenv("LUVATRIX_FONT_DIRS", "").split(os.pathsep)
        if item.strip()
    ]
    dirs.extend([py_packages_dir / "luvatrix_assets" / "fonts", py_packages_dir / "assets" / "fonts"])
    for entry in sys.path:
        if entry:
            dirs.append(Path(entry) / "luvatrix_assets" / "fonts")
    dirs.extend([
        Path.home() / "Library/Fonts",
        Path("/Library/Fonts"),
        Path("/System/Library/Fonts"),
        Path("/System/Library/Fonts/Supplemental"),
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
    ])
    return dirs


_FALLBACK_PATHS_CACHE: list[str] | None = None


def fallback_font_paths() -> list[str]:
    """Curated cascade of fallback font files that exist on this host."""
    global _FALLBACK_PATHS_CACHE
    if _FALLBACK_PATHS_CACHE is not None:
        return list(_FALLBACK_PATHS_CACHE)
    candidates: list[Path] = []
    for base in _font_dirs():
        if base.exists():
            for ext in ("*.ttf", "*.otf", "*.ttc"):
                candidates.extend(base.rglob(ext))
    platform = "darwin" if sys.platform == "darwin" else "linux"
    ordered: list[str] = []
    for pattern in _FALLBACK_BASENAMES[platform]:
        for path in candidates:
            if pattern in _norm(path.name) or pattern in _norm(path.stem):
                ordered.append(str(path))
                break
    _FALLBACK_PATHS_CACHE = ordered
    return list(ordered)


class ChainFont:
    """One font in the chain, measured in REQUESTED px units.

    ``scale_down`` is 1.0 for outline fonts loaded at the requested size. For
    bitmap-strike fonts (color emoji) it is strike/requested: the PIL font is
    bigger than requested, so metrics divide by it and renders are scaled.
    """

    def __init__(self, pil_font, *, scale_down: float = 1.0) -> None:
        self.pil = pil_font
        self.scale_down = float(scale_down)
        self._notdef = bytes(pil_font.getmask(_SENTINEL))
        self._cover_cache: dict[str, bool] = {}

    def covers(self, ch: str) -> bool:
        cached = self._cover_cache.get(ch)
        if cached is None:
            cached = bytes(self.pil.getmask(ch)) != self._notdef
            self._cover_cache[ch] = cached
        return cached

    def getlength(self, text: str) -> float:
        return float(self.pil.getlength(text)) / self.scale_down

    def getbbox(self, ch: str) -> tuple[float, float, float, float]:
        left, top, right, bottom = self.pil.getbbox(ch)
        f = self.scale_down
        return (left / f, top / f, right / f, bottom / f)

    def getmetrics(self) -> tuple[float, float]:
        ascent, descent = self.pil.getmetrics()
        return (ascent / self.scale_down, descent / self.scale_down)

    def draw_text(self, image, x: float, y: float, text: str, *, fill: int = 255) -> None:
        from PIL import Image, ImageDraw

        if self.scale_down == 1.0:
            ImageDraw.Draw(image).text((x, y), text, fill=fill, font=self.pil)
            return
        for ch in text:
            self.draw_char(image, x, y, ch)
            x += self.getlength(ch)

    def draw_char(self, image, x: float, y: float, ch: str, *, fill: int = 255) -> None:
        """Draw ``ch`` at the PIL text origin (x, y), in requested px units."""
        from PIL import Image, ImageDraw

        if self.scale_down == 1.0:
            ImageDraw.Draw(image).text((x, y), ch, fill=fill, font=self.pil)
            return
        left, top, right, bottom = self.pil.getbbox(ch)
        w = max(1, int(right - left))
        h = max(1, int(bottom - top))
        tmp = Image.new("L", (w, h), 0)
        ImageDraw.Draw(tmp).text((-left, -top), ch, fill=fill, font=self.pil)
        f = self.scale_down
        tmp = tmp.resize((max(1, round(w / f)), max(1, round(h / f))), Image.Resampling.LANCZOS)
        image.paste(tmp, (round(x + left / f), round(y + top / f)), tmp)


def _load_chain_font(font_path: str, size_px: float) -> ChainFont | None:
    """Load a font at the requested px, falling back to a native bitmap
    strike (scaled down) when the font is bitmap-only (color emoji)."""
    from PIL import ImageFont

    size = max(1, int(round(size_px)))
    try:
        return ChainFont(ImageFont.truetype(font_path, size=size))
    except Exception:
        pass
    for strike in _BITMAP_STRIKES:
        if strike <= size:
            continue
        try:
            font = ImageFont.truetype(font_path, size=strike)
        except Exception:
            continue
        return ChainFont(font, scale_down=strike / float(size))
    return None


class FontChain:
    def __init__(self, primary: ChainFont, fallbacks: list[ChainFont]) -> None:
        self.primary = primary
        self._fonts = [primary, *fallbacks]
        self._pick_cache: dict[str, ChainFont] = {}

    def font_for(self, ch: str) -> ChainFont:
        """First font covering the glyph; whitespace and total-misses stay on
        the primary (a visible .notdef box beats a silent gap)."""
        pick = self._pick_cache.get(ch)
        if pick is not None:
            return pick
        if ch.isspace():
            pick = self.primary
        else:
            pick = self.primary
            for font in self._fonts:
                if font.covers(ch):
                    pick = font
                    break
        self._pick_cache[ch] = pick
        return pick


_CHAIN_CACHE: dict[tuple[str, int], FontChain] = {}


def get_font_chain(font_family: str, size_px: float) -> FontChain:
    """Primary font for ``font_family`` + this host's fallback cascade."""
    from luvatrix_core.core.ui_frame_renderer import _load_font, _resolve_system_font_path

    key = (font_family, max(1, int(round(size_px))))
    chain = _CHAIN_CACHE.get(key)
    if chain is not None:
        return chain
    primary_path = _resolve_system_font_path(font_family)
    primary = _load_chain_font(primary_path, size_px)
    if primary is None:
        # Keep the historical last-resort behavior (PIL default / fallback font).
        primary = ChainFont(_load_font(primary_path, size_px))
    fallbacks = []
    for path in fallback_font_paths():
        if primary_path and Path(path) == Path(primary_path):
            continue
        cfont = _load_chain_font(path, size_px)
        if cfont is not None:
            fallbacks.append(cfont)
    chain = FontChain(primary, fallbacks)
    if len(_CHAIN_CACHE) > 32:
        _CHAIN_CACHE.pop(next(iter(_CHAIN_CACHE)))
    _CHAIN_CACHE[key] = chain
    return chain


def _is_default_ignorable(ch: str) -> bool:
    """Default-ignorable chars (format controls + variation selectors) have
    no visible glyph in any chain font — the .notdef policy would draw a box
    (live bug: "🌶️[]beepboop", the box being U+FE0F after the pepper). They
    render invisible/zero-width instead. Proper cluster shaping (ZWJ emoji,
    VS16 presentation) is HarfBuzz territory, out of scope for v1."""
    import unicodedata

    if unicodedata.category(ch) == "Cf":
        return True
    cp = ord(ch)
    return 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF


def split_runs(chain: FontChain, text: str) -> list[tuple[ChainFont, str]]:
    """Group consecutive chars by their covering font for run drawing.
    Default-ignorable chars are dropped (invisible, zero advance)."""
    runs: list[tuple[ChainFont, str]] = []
    for ch in text:
        if _is_default_ignorable(ch):
            continue
        font = chain.font_for(ch)
        if runs and runs[-1][0] is font:
            runs[-1] = (font, runs[-1][1] + ch)
        else:
            runs.append((font, ch))
    return runs


def measure_runs(runs: list[tuple[ChainFont, str]]) -> tuple[float, float, float]:
    """(width, ascent, descent) of the run list, baselines aligned."""
    width = sum(font.getlength(text) for font, text in runs)
    ascent = max((font.getmetrics()[0] for font, _ in runs), default=1.0)
    descent = max((font.getmetrics()[1] for font, _ in runs), default=0.0)
    return (width, ascent, descent)


def draw_runs(image, x: float, y: float, runs: list[tuple[ChainFont, str]], *, fill: int = 255) -> None:
    """Draw runs at (x, y) with baselines aligned to the tallest ascent."""
    ascent_max = max((font.getmetrics()[0] for font, _ in runs), default=0.0)
    pen = x
    for font, text in runs:
        run_y = y + (ascent_max - font.getmetrics()[0])
        font.draw_text(image, pen, run_y, text, fill=fill)
        pen += font.getlength(text)
