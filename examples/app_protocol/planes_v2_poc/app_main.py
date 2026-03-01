from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from luvatrix_ui.planes_runtime import load_plane_app


PLANES_JSON = APP_DIR / "plane.json"


def toggle_theme(event_ctx: dict[str, Any], app_state: dict[str, Any]) -> None:
    _ = event_ctx
    current = str(app_state.get("active_theme", "default"))
    app_state["active_theme"] = "sunset" if current == "default" else "default"


def create():
    return load_plane_app(
        PLANES_JSON,
        handlers={
            "handlers::toggle_theme": toggle_theme,
        },
        strict=True,
    )
