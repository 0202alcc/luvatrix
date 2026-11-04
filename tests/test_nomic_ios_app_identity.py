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


def _plist() -> dict:
    import plistlib

    with (APP_DIR / "ios" / "Luvatrix" / "Info.plist").open("rb") as handle:
        return plistlib.load(handle)


def test_app_is_categorized_as_productivity_not_a_game() -> None:
    spec = _spec()
    assert re.search(r"^\s+LSApplicationCategoryType: public\.app-category\.productivity$", spec, re.MULTILINE)
    assert "GameMode" not in spec
    plist = _plist()
    assert plist["LSApplicationCategoryType"] == "public.app-category.productivity"
    assert not any("GameMode" in key for key in plist)


def test_appearance_is_unpinned_and_the_status_bar_follows_the_trait() -> None:
    spec = _spec()
    plist = _plist()
    # The app supports light and dark, so nothing pins the interface style.
    assert "UIUserInterfaceStyle" not in spec
    assert "UIUserInterfaceStyle" not in plist
    # UIStatusBarStyleDefault draws dark content in light mode and light
    # content in dark mode automatically.
    assert re.search(r"^\s+UIStatusBarStyle: UIStatusBarStyleDefault$", spec, re.MULTILINE)
    assert re.search(r"^\s+UIViewControllerBasedStatusBarAppearance: false$", spec, re.MULTILINE)
    assert plist["UIStatusBarStyle"] == "UIStatusBarStyleDefault"
    assert plist["UIViewControllerBasedStatusBarAppearance"] is False
