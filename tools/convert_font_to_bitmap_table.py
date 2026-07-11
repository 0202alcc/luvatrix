from __future__ import annotations

import argparse
from pathlib import Path
import string

from PIL import Image, ImageDraw, ImageFont


DEFAULT_CHARS = string.ascii_uppercase + string.digits + " :.,-_=|/"
ALIASES = {
    " ": "U+0020",
    ":": "colon",
    ".": "period",
    ",": "comma",
    "-": "dash",
    "_": "underscore",
    "=": "equals",
    "|": "pipe",
    "/": "slash",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a TTF/OTF font into a Luvatrix glyph table.")
    parser.add_argument("font", type=Path, help="Path to a .ttf or .otf font file.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("android/app/src/main/assets/luvatrix_bitmap_font.txt"),
        help="Output glyph table path.",
    )
    parser.add_argument("--size", type=int, default=18, help="Font render size in pixels.")
    parser.add_argument("--width", type=int, default=16, help="Fixed glyph cell width. Max 32.")
    parser.add_argument("--height", type=int, default=22, help="Fixed glyph cell height.")
    parser.add_argument("--advance", type=int, default=14, help="Glyph advance in bitmap columns.")
    parser.add_argument(
        "--chars",
        default=DEFAULT_CHARS,
        help="Characters to include. Defaults to uppercase ASCII, digits, and punctuation used by the demo.",
    )
    parser.add_argument("--threshold", type=int, default=96, help="Alpha threshold for turning pixels on.")
    parser.add_argument(
        "--format",
        choices=("bitmask", "alpha"),
        default="bitmask",
        help="Write 1-bit row masks or 8-bit alpha coverage rows.",
    )
    parser.add_argument(
        "--supersample",
        type=int,
        default=2,
        help="Scale factor for alpha output before downsampling.",
    )
    args = parser.parse_args()

    if args.width < 1 or args.width > 32:
        raise SystemExit("--width must be between 1 and 32")
    if args.height < 1:
        raise SystemExit("--height must be positive")
    if args.advance < 1:
        raise SystemExit("--advance must be positive")
    if args.supersample < 1:
        raise SystemExit("--supersample must be positive")

    font_size = args.size * args.supersample if args.format == "alpha" else args.size
    font = ImageFont.truetype(str(args.font), font_size)
    lines = [
        "# Luvatrix bitmap font table v1." if args.format == "bitmask" else "# Luvatrix matrix font alpha table v1.",
        f"# Generated from {args.font}",
        (
            "# Rows are hexadecimal bitmasks, leftmost pixel in the high bit of each row."
            if args.format == "bitmask"
            else "# Rows are hexadecimal alpha bytes per pixel, left to right."
        ),
        f"format={args.format}",
        f"width={args.width}",
        f"height={args.height}",
        f"advance={args.advance}",
    ]
    if args.format == "alpha":
        lines.append(f"supersample={args.supersample}")
    for ch in _unique_chars(args.chars):
        if args.format == "alpha":
            rows = _alpha_glyph_rows(
                font,
                ch,
                width=args.width,
                height=args.height,
                supersample=args.supersample,
            )
            lines.append(f"{_glyph_key(ch)}={','.join(''.join(f'{value:02x}' for value in row) for row in rows)}")
        else:
            rows = _glyph_rows(
                font,
                ch,
                width=args.width,
                height=args.height,
                threshold=max(0, min(255, args.threshold)),
            )
            lines.append(f"{_glyph_key(ch)}={','.join(f'{row:0{max(1, (args.width + 3) // 4)}x}' for row in rows)}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(_unique_chars(args.chars))} glyphs, {args.width}x{args.height}, advance={args.advance})")


def _unique_chars(chars: str) -> list[str]:
    out: list[str] = []
    for ch in chars:
        if ch not in out:
            out.append(ch)
    return out


def _glyph_key(ch: str) -> str:
    return ALIASES.get(ch, ch if len(ch) == 1 and 32 < ord(ch) < 127 else f"U+{ord(ch):04X}")


def _glyph_rows(font: ImageFont.FreeTypeFont, ch: str, *, width: int, height: int, threshold: int) -> list[int]:
    image = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox((0, 0), ch, font=font)
    glyph_w = bbox[2] - bbox[0]
    glyph_h = bbox[3] - bbox[1]
    x = max(0, (width - glyph_w) // 2 - bbox[0])
    y = max(0, (height - glyph_h) // 2 - bbox[1])
    draw.text((x, y), ch, fill=255, font=font)

    rows: list[int] = []
    pixels = image.load()
    for yy in range(height):
        row = 0
        for xx in range(width):
            if pixels[xx, yy] >= threshold:
                row |= 1 << (width - 1 - xx)
        rows.append(row)
    return rows


def _alpha_glyph_rows(
    font: ImageFont.FreeTypeFont,
    ch: str,
    *,
    width: int,
    height: int,
    supersample: int,
) -> list[list[int]]:
    scaled_width = width * supersample
    scaled_height = height * supersample
    image = Image.new("L", (scaled_width, scaled_height), 0)
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox((0, 0), ch, font=font)
    glyph_w = bbox[2] - bbox[0]
    glyph_h = bbox[3] - bbox[1]
    x = max(0, (scaled_width - glyph_w) // 2 - bbox[0])
    y = max(0, (scaled_height - glyph_h) // 2 - bbox[1])
    draw.text((x, y), ch, fill=255, font=font)

    resampling = getattr(Image, "Resampling", Image).BOX
    downsampled = image.resize((width, height), resampling)
    pixels = downsampled.load()
    rows: list[list[int]] = []
    for yy in range(height):
        rows.append([int(pixels[xx, yy]) for xx in range(width)])
    return rows


if __name__ == "__main__":
    main()
