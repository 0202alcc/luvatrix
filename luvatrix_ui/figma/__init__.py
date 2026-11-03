"""Render Figma designs and click-through prototypes with Luvatrix.

The input is the JSON returned by Figma's REST API (`GET /v1/files/:key` with
`geometry=paths`, or `GET /v1/files/:key/nodes`). `luvatrix figma pull` saves
that JSON plus image fills; `FigmaApp` runs it as a Luvatrix app.
"""

from __future__ import annotations

from .document import (
    BackAction,
    FigmaDocument,
    FigmaFormatError,
    Frame,
    Hotspot,
    NavigateAction,
    UrlAction,
)
from .render import FigmaRenderer, render_frame
from .text import FontLibrary

__all__ = [
    "BackAction",
    "FigmaApp",
    "FigmaDocument",
    "FigmaFormatError",
    "FigmaRenderer",
    "FontLibrary",
    "Frame",
    "Hotspot",
    "NavigateAction",
    "UrlAction",
    "render_frame",
]


def __getattr__(name: str):
    if name == "FigmaApp":
        from .app import FigmaApp

        return FigmaApp
    raise AttributeError(name)
