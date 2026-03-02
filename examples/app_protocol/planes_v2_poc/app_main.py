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
    plane_scroll = app_state.setdefault("plane_scroll", {})
    if isinstance(plane_scroll, dict):
        plane_scroll["x"] = 0.0
        plane_scroll["y"] = 0.0


def record_scroll(event_ctx: dict[str, Any], app_state: dict[str, Any]) -> None:
    payload = event_ctx.get("payload", {})
    if isinstance(payload, dict):
        app_state["last_scroll_dx"] = float(payload.get("delta_x", 0.0))
        app_state["last_scroll_dy"] = float(payload.get("delta_y", 0.0))


def _apply_centered_section_cut_geometry(app: Any, ctx: Any) -> None:
    width = float(getattr(ctx.matrix, "width", 0))
    height = float(getattr(ctx.matrix, "height", 0))
    if width <= 0 or height <= 0:
        return

    plane_height = int(round(3.0 * height))
    side = max(1, int(round(0.40 * height)))
    x = int(round((width - float(side)) / 2.0))
    y = int(round((float(plane_height) - float(side)) / 2.0))

    components = app._planes.get("components", [])
    if not isinstance(components, list):
        return
    for component in components:
        if not isinstance(component, dict):
            continue
        comp_id = component.get("id")
        if comp_id not in {"section_cut", "section_cut_frame"}:
            continue
        component["position"] = {"x": x, "y": y, "frame": "screen_tl"}
        component["size"] = {
            "width": {"unit": "px", "value": int(side)},
            "height": {"unit": "px", "value": int(side)},
        }


def create():
    app = load_plane_app(
        PLANES_JSON,
        handlers={
            "handlers::toggle_theme": toggle_theme,
            "handlers::reset_scroll": reset_scroll,
            "handlers::record_scroll": record_scroll,
        },
        strict=True,
    )
    original_init = app.init

    def _init_with_centered_section_cut(ctx: Any) -> None:
        _apply_centered_section_cut_geometry(app, ctx)
        original_init(ctx)

    app.init = _init_with_centered_section_cut
    return app
