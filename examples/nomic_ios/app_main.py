from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DESIGN = APP_DIR / "design" / "figma_file.json"
DESIGN_DARK = APP_DIR / "design" / "figma_file.dark.json"


def _load_composer():
    """Load the sibling composer module by path (the app dir is not a package)."""
    spec = importlib.util.spec_from_file_location("nomic_ios_composer", APP_DIR / "composer.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def create():
    composer = _load_composer()
    dark = DESIGN_DARK if DESIGN_DARK.exists() else None
    return composer.create_app(DESIGN, dark=dark)
