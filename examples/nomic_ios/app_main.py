from __future__ import annotations

from pathlib import Path

from luvatrix_ui.figma import FigmaApp

DESIGN = Path(__file__).resolve().parent / "design" / "figma_file.json"

COMPOSER_HINT = "Preview only"


def _composer_hint(app: FigmaApp, node: str) -> None:
    """Tapping the model chip answers with a hint instead of a real menu."""
    app.set_text(node, COMPOSER_HINT)


def create() -> FigmaApp:
    app = FigmaApp(DESIGN)
    app.on_tap("Mode Chip", _composer_hint)
    return app
