"""Home-screen identity of the Nomic iOS example: label and app icon."""

from __future__ import annotations

import re
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "examples" / "nomic_ios"


def _spec() -> str:
    return (APP_DIR / "ios" / "project.yml").read_text(encoding="utf-8")


def test_home_screen_label_is_nomic() -> None:
    assert re.search(r"^\s+CFBundleDisplayName: Nomic$", _spec(), re.MULTILINE)


def test_bundle_id_and_product_name_are_unchanged() -> None:
    spec = _spec()
    assert re.search(r"^\s+PRODUCT_BUNDLE_IDENTIFIER: com\.luvatrix\.app\.nomic-ios$", spec, re.MULTILINE)
    # The runner and tour look up the built product as Luvatrix.app.
    assert "PRODUCT_NAME:" not in spec


def test_app_icon_is_an_opaque_1024_png() -> None:
    import PIL.Image

    with PIL.Image.open(APP_DIR / "assets" / "icon.png") as icon:
        assert icon.format == "PNG"
        assert icon.size == (1024, 1024)
        # iOS rejects app icons with an alpha channel.
        assert icon.mode == "RGB"
