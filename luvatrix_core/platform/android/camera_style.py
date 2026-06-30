from __future__ import annotations

import json
import math
from pathlib import Path


REQUIRED_STYLE_FIELDS = (
    "name",
    "version",
    "shadow_lift",
    "highlight_rolloff",
    "global_saturation",
    "local_contrast",
    "sharpening",
    "skin_smoothing",
    "sky_saturation",
    "foliage_saturation",
    "white_balance_bias",
)

WHITE_BALANCE_BIASES = frozenset({"neutral", "slightly_warm", "warm", "cool", "daylight"})
SATURATION_FIELDS = frozenset({"global_saturation", "sky_saturation", "foliage_saturation"})


def load_style_profile(path: Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("style profile root must be an object")
    validate_style_profile(payload)
    return payload


def validate_style_profile(profile: dict[str, object]) -> None:
    for field in REQUIRED_STYLE_FIELDS:
        if field not in profile:
            raise ValueError(f"missing required style profile field: {field}")
    name = profile["name"]
    if not isinstance(name, str) or not name:
        raise ValueError("style profile name must be a non-empty string")
    version = profile["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("style profile version must be a positive integer")
    for field in REQUIRED_STYLE_FIELDS:
        if field in {"name", "version", "white_balance_bias"}:
            continue
        value = profile[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"{field} must be a finite number")
        number = float(value)
        if field in SATURATION_FIELDS and not 0.0 <= number <= 3.0:
            raise ValueError(f"{field} must be between 0.0 and 3.0")
        if field == "sharpening" and not 0.0 <= number <= 3.0:
            raise ValueError("sharpening must be between 0.0 and 3.0")
        if field not in SATURATION_FIELDS and field != "sharpening" and not 0.0 <= number <= 3.0:
            raise ValueError(f"{field} must be between 0.0 and 3.0")
    white_balance = profile["white_balance_bias"]
    if white_balance not in WHITE_BALANCE_BIASES:
        raise ValueError(f"unknown white_balance_bias: {white_balance}")
