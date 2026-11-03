from __future__ import annotations

from pathlib import Path

from luvatrix_ui.figma import FigmaApp

DESIGN = Path(__file__).resolve().parent / "design" / "figma_file.json"


def create() -> FigmaApp:
    return FigmaApp(DESIGN)
