from __future__ import annotations

from pathlib import Path

from luvatrix_ui.figma import FigmaApp

DESIGN = Path(__file__).resolve().parent / "design" / "figma_file.json"


def _water(app: FigmaApp, _node: str) -> bool:
    app.set_text("Water Label", "Watered today")
    return False


def create() -> FigmaApp:
    app = FigmaApp(DESIGN)
    app.on_tap("Water Now", _water)
    return app
