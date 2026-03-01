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


def reset_scroll(event_ctx: dict[str, Any], app_state: dict[str, Any]) -> None:
    _ = event_ctx
    viewport_scroll = app_state.setdefault("viewport_scroll", {})
    if isinstance(viewport_scroll, dict):
        viewport_scroll["content_viewport"] = {"x": 0.0, "y": 0.0}


def record_scroll(event_ctx: dict[str, Any], app_state: dict[str, Any]) -> None:
    payload = event_ctx.get("payload", {})
    if isinstance(payload, dict):
        app_state["last_scroll_dx"] = float(payload.get("delta_x", 0.0))
        app_state["last_scroll_dy"] = float(payload.get("delta_y", 0.0))


def create():
    return load_plane_app(
        PLANES_JSON,
        handlers={
            "handlers::toggle_theme": toggle_theme,
            "handlers::reset_scroll": reset_scroll,
            "handlers::record_scroll": record_scroll,
        },
        strict=True,
    )
