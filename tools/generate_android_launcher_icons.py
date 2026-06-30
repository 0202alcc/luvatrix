from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


DENSITIES = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Android launcher icon PNGs from one source image.")
    parser.add_argument("--source", type=Path, default=Path("assets/icon.png"))
    parser.add_argument("--res-dir", type=Path, default=Path("android/app/src/main/res"))
    parser.add_argument("--name", default="ic_launcher.png")
    args = parser.parse_args()

    source = Image.open(args.source).convert("RGBA")
    for folder, size in DENSITIES.items():
        dest_dir = args.res_dir / folder
        dest_dir.mkdir(parents=True, exist_ok=True)
        source.resize((size, size), Image.Resampling.LANCZOS).save(dest_dir / args.name)
    print(f"generated {len(DENSITIES)} launcher icons from {args.source}")


if __name__ == "__main__":
    main()
