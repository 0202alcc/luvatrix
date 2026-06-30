from __future__ import annotations

from pathlib import Path

import pytest

from luvatrix_core.platform.android.camera_style import load_style_profile, validate_style_profile


STYLE_DIR = Path(__file__).resolve().parents[1] / "examples" / "camera" / "styles"
PLANNED_STYLES = {
    "neutral.json",
    "samsung_pop.json",
    "apple_natural.json",
    "google_hdr.json",
    "xiaomi_vibrant.json",
}


def test_all_planned_style_files_exist() -> None:
    assert {path.name for path in STYLE_DIR.glob("*.json")} == PLANNED_STYLES


def test_checked_in_style_profiles_validate() -> None:
    for path in sorted(STYLE_DIR.glob("*.json")):
        profile = load_style_profile(path)
        validate_style_profile(profile)


def test_invalid_saturation_fails() -> None:
    profile = load_style_profile(STYLE_DIR / "neutral.json")
    profile["global_saturation"] = 3.5

    with pytest.raises(ValueError, match="global_saturation must be between 0.0 and 3.0"):
        validate_style_profile(profile)


def test_missing_name_fails() -> None:
    profile = load_style_profile(STYLE_DIR / "neutral.json")
    del profile["name"]

    with pytest.raises(ValueError, match="missing required style profile field: name"):
        validate_style_profile(profile)
