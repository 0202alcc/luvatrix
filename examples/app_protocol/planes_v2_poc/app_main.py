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


def open_card(event_ctx: dict[str, Any], app_state: dict[str, Any]) -> None:
    app_state["last_action"] = ("open_card", event_ctx.get("component_id"))


def hover_logo(event_ctx: dict[str, Any], app_state: dict[str, Any]) -> None:
    app_state["last_action"] = ("hover_logo", event_ctx.get("component_id"))


def pan_timeline(event_ctx: dict[str, Any], app_state: dict[str, Any]) -> None:
    app_state["last_action"] = ("pan_timeline", event_ctx.get("component_id"))


def select_task(event_ctx: dict[str, Any], app_state: dict[str, Any]) -> None:
    app_state["last_action"] = ("select_task", event_ctx.get("component_id"))


def create():
    return load_plane_app(
        PLANES_JSON,
        handlers={
            "handlers::open_card": open_card,
            "handlers::hover_logo": hover_logo,
            "handlers::pan_timeline": pan_timeline,
            "handlers::select_task": select_task,
        },
        strict=True,
    )
