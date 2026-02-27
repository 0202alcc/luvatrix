from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Mapping

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")


@dataclass(frozen=True)
class ThemeTokens:
    """Core v0 token set for in-repo Luvatrix UI components."""

    button_bg_idle: str = "#2B3442"
    button_bg_hover: str = "#334155"
    button_bg_press_down: str = "#1E293B"
    button_bg_press_hold: str = "#0F172A"
    button_bg_disabled: str = "#9CA3AF"
    button_text: str = "#F8FAFC"
    font_family: str = "System"
    font_size_px: float = 14.0


DEFAULT_TOKENS = ThemeTokens()


def validate_theme_tokens(overrides: Mapping[str, Any] | None = None) -> ThemeTokens:
    """Validate and merge user token overrides against v0 defaults.

    TODO(extract): keep this validation contract strict for future package split.
    """

    raw: dict[str, Any] = asdict(DEFAULT_TOKENS)
    if overrides:
        for key, value in overrides.items():
            if key not in raw:
                raise ValueError(f"Unknown theme token: {key}")
            raw[key] = value

    for key in (
        "button_bg_idle",
        "button_bg_hover",
        "button_bg_press_down",
        "button_bg_press_hold",
        "button_bg_disabled",
        "button_text",
    ):
        if not isinstance(raw[key], str) or not _HEX_COLOR.match(raw[key]):
            raise ValueError(f"Token `{key}` must be a hex color (#RRGGBB or #RRGGBBAA)")

    if not isinstance(raw["font_family"], str) or not raw["font_family"].strip():
        raise ValueError("Token `font_family` must be a non-empty string")

    if not isinstance(raw["font_size_px"], (int, float)) or float(raw["font_size_px"]) <= 0:
        raise ValueError("Token `font_size_px` must be a positive number")

    return ThemeTokens(
        button_bg_idle=str(raw["button_bg_idle"]),
        button_bg_hover=str(raw["button_bg_hover"]),
        button_bg_press_down=str(raw["button_bg_press_down"]),
        button_bg_press_hold=str(raw["button_bg_press_hold"]),
        button_bg_disabled=str(raw["button_bg_disabled"]),
        button_text=str(raw["button_text"]),
        font_family=str(raw["font_family"]),
        font_size_px=float(raw["font_size_px"]),
    )
