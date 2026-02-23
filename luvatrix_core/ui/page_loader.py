from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from .element import Element
from luvatrix_core.render.framebuffer import Color
from luvatrix_core.render.svg import _parse_color


@dataclass(frozen=True)
class Page:
    page_id: str
    width: int
    height: int
    background: Color
    elements: list[Element]


def load_page(app_dir: Path) -> Page:
    page_path = app_dir / "page.json"
    data = json.loads(page_path.read_text())
    viewport = data.get("viewport", {})
    width = int(viewport.get("width", 640))
    height = int(viewport.get("height", 360))
    bg_color = _parse_color(data.get("background")) or (12, 14, 18, 255)
    elements: list[Element] = []
    for raw in data.get("elements", []):
        svg_ref = raw.get("svg")
        if not svg_ref:
            continue
        svg_path = (app_dir / svg_ref).resolve()
        elements.append(
            Element(
                element_id=raw.get("id", svg_path.stem),
                svg_path=svg_path,
                x=float(raw.get("x", 0.0)),
                y=float(raw.get("y", 0.0)),
                scale=float(raw.get("scale", 1.0)),
                opacity=float(raw.get("opacity", 1.0)),
                animation=raw.get("animate"),
            )
        )
    return Page(
        page_id=data.get("page_id", app_dir.name),
        width=width,
        height=height,
        background=bg_color,
        elements=elements,
    )
