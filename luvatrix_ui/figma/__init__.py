"""Render Figma designs and click-through prototypes with Luvatrix.

The input is the JSON returned by Figma's REST API (`GET /v1/files/:key` with
`geometry=paths`, or `GET /v1/files/:key/nodes`). `luvatrix figma pull` saves
that JSON plus image fills; `FigmaApp` runs it as a Luvatrix app.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "BackAction": "document",
    "FigmaDocument": "document",
    "FigmaFormatError": "document",
    "Frame": "document",
    "Hotspot": "document",
    "NavigateAction": "document",
    "OverlayAction": "document",
    "UrlAction": "document",
    "FigmaRenderer": "render",
    "render_frame": "render",
    "FontLibrary": "text",
    "FigmaApp": "app",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value
