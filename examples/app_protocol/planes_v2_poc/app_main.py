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
RUNTIME_GRADIENT_ASSET = APP_DIR / "assets" / "index_plane_gradient_runtime.svg"


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


def _lerp_channel(a: int, b: int, t: float) -> int:
    return int(round(float(a) + (float(b) - float(a)) * float(t)))


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    raw = value.strip().lstrip("#")
    if len(raw) != 6:
        raise ValueError("expected #RRGGBB color")
    return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def _write_runtime_gradient_asset(path: Path, *, width_px: int, height_px: int) -> None:
    top = _hex_to_rgb("#0b1f56")
    bottom = _hex_to_rgb("#ffffff")
    h = max(1, int(height_px))
    w = max(1, int(width_px))
    lines: list[str] = [
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'
    ]
    for y in range(h):
        t = float(y) / float(max(1, h - 1))
        rgb = (
            _lerp_channel(top[0], bottom[0], t),
            _lerp_channel(top[1], bottom[1], t),
            _lerp_channel(top[2], bottom[2], t),
        )
        lines.append(f'<rect x="0" y="{y}" width="{w}" height="1" fill="{_rgb_to_hex(rgb)}"/>')
    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")


def _apply_runtime_gradient_geometry(app: Any, ctx: Any) -> None:
    width = int(round(float(getattr(ctx.matrix, "width", 0))))
    height = int(round(float(getattr(ctx.matrix, "height", 0))))
    if width <= 0 or height <= 0:
        return
    plane_height = max(1, int(round(3.0 * float(height))))
    _write_runtime_gradient_asset(RUNTIME_GRADIENT_ASSET, width_px=width, height_px=plane_height)
    components = app._planes.get("components", [])
    if not isinstance(components, list):
        return
    for component in components:
        if not isinstance(component, dict):
            continue
        if component.get("id") != "index_gradient_bg":
            continue
        props = component.get("props")
        if not isinstance(props, dict):
            props = {}
            component["props"] = props
        props["svg"] = f"assets/{RUNTIME_GRADIENT_ASSET.name}"


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
        _apply_runtime_gradient_geometry(app, ctx)
        _apply_centered_section_cut_geometry(app, ctx)
        original_init(ctx)

    app.init = _init_with_centered_section_cut
    return app
