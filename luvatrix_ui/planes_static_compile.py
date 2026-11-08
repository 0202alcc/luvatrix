"""Static-tier AOT compiler for planes container apps.

Compiles a container document into a `static_bundle` JSON that a tiny
browser runtime (`runtime/static-core.js` + `runtime/luvatrix-static.js`)
renders with the existing Canvas command-buffer pipeline — **no Pyodide,
no Python at request time**. The container is data; this emitter is the
"any language" promise applied to the frontend itself.

Eligibility (`is_static_eligible`): every component function binding is
declarative (`trigger:<name>`, validated against route transitions by
`compile_container`), and no `on_state` animations are present (those
require runtime state). Apps opt in via `[web] static_container` in
`app.toml`; `build_web_app` then emits `static_bundle.json` and rewrites
the index entrypoint.

The emitted bundle carries unitized geometry (px stays absolute; vw/vh
resolve against the canvas at runtime; %, pt, cm resolve to px at build
time against the display size). v1 supports `screen_tl`-framed,
plane-attached components in px-sized planes.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Mapping

from .planes_container import CompiledAppContainer, PlanesValidationError, compile_container

STATIC_BUNDLE_SCHEMA_VERSION = 1
SUPPORTED_POSITION_UNITS = frozenset({"px", "vw", "vh"})
_DEFAULT_TEXT_COLOR = "#F5FBFF"
_DEFAULT_FONT_SIZE_PX = 14.0


def is_static_eligible(payload: Mapping[str, Any] | str | Path) -> bool:
    """True when the container can render with the static (no-Python) runtime."""
    try:
        compiled = _compile(payload)
    except (PlanesValidationError, ValueError, OSError, json.JSONDecodeError):
        return False
    if compiled.planes_payload is None:
        return False
    if not _bindings_are_declarative(compiled.planes_payload.get("components", [])):
        return False
    for animation in compiled.animations:
        if animation.trigger == "on_state":
            return False
    return True


def compile_static_bundle(source: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    """Compile a container document into the static runtime bundle JSON."""
    compiled = _compile(source)
    payload = compiled.planes_payload
    if payload is None:
        raise PlanesValidationError("static compile requires a container payload")
    container_root = _source_root(source)

    planes_bundle = _serialize_planes(payload)
    if not planes_bundle:
        raise PlanesValidationError("static compile requires at least one plane")
    display = planes_bundle[0]["size"]
    bundle: dict[str, Any] = {
        "schema_version": STATIC_BUNDLE_SCHEMA_VERSION,
        "app": _serialize_app(payload),
        "entry_route": compiled.entry_route,
        "page_background": planes_bundle[0]["background_color"],
        "display": {"width": display["width"], "height": display["height"]},
        "planes": planes_bundle,
        "routes": [
            {
                "id": route.id,
                "default": route.default,
                "active_planes": list(route.active_planes),
                "transitions": [
                    {
                        "trigger": transition.trigger,
                        "to_route": transition.to_route,
                        "kind": transition.kind,
                        "duration_ms": transition.duration_ms,
                        "easing": transition.easing,
                    }
                    for transition in route.transitions
                ],
            }
            for route in compiled.routes
        ],
        "components": _serialize_components(payload.get("components", []), planes_bundle, container_root),
        "animations": [
            {
                "target": animation.target,
                "trigger": animation.trigger,
                "kind": animation.kind,
                "duration_ms": animation.duration_ms,
                "delay_ms": animation.delay_ms,
                "easing": animation.easing,
                "loop": animation.loop,
                "keyframes": [
                    {"at": keyframe.at, "props": dict(keyframe.props)} for keyframe in animation.keyframes
                ],
            }
            for animation in compiled.animations
        ],
    }
    return bundle


def _compile(source: Mapping[str, Any] | str | Path) -> CompiledAppContainer:
    if isinstance(source, Mapping):
        return compile_container(source)
    path = Path(source)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return compile_container(payload)


def _source_root(source: Mapping[str, Any] | str | Path) -> Path | None:
    if isinstance(source, Mapping):
        return None
    return Path(source).resolve().parent


def _serialize_app(payload: Mapping[str, Any]) -> dict[str, Any]:
    app = payload.get("app")
    app_obj = dict(app) if isinstance(app, Mapping) else {}
    return {
        "title": str(app_obj.get("title", "Luvatrix")),
        "icon": str(app_obj.get("icon", "")),
    }


def _serialize_planes(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    planes_raw = payload.get("planes")
    if isinstance(planes_raw, list) and planes_raw:
        raw_planes = planes_raw
    elif isinstance(payload.get("plane"), Mapping):
        raw_planes = [payload["plane"]]
    else:
        raw_planes = []
    planes: list[dict[str, Any]] = []
    for plane in raw_planes:
        if not isinstance(plane, Mapping):
            raise PlanesValidationError("plane entries must be objects")
        background = plane.get("background")
        background_color = "#000000"
        if isinstance(background, Mapping):
            color = background.get("color")
            if isinstance(color, str) and color.strip():
                background_color = color
        size = _plane_size_px(plane)
        planes.append(
            {
                "id": str(plane.get("id", "")),
                "background_color": background_color,
                "global_z": int(plane.get("plane_global_z", 0)),
                "size": size,
            }
        )
    return planes


def _plane_size_px(plane: Mapping[str, Any]) -> dict[str, float]:
    size = plane.get("size")
    if not isinstance(size, Mapping):
        raise PlanesValidationError("static tier requires plane sizes")
    width = _unitized_px(size.get("width"), axis="width")
    height = _unitized_px(size.get("height"), axis="height")
    return {"width": width, "height": height}


def _unitized_px(raw: Any, *, axis: str) -> float:
    """Resolve a size value to px; vw/vh pass through as ratio units."""
    if isinstance(raw, Mapping):
        unit = str(raw.get("unit", "px"))
        value = float(raw.get("value", 0.0))
        if unit == "px":
            return value
        if unit in ("vw", "vh"):
            # Cannot resolve against the display before the display exists;
            # planes must declare px sizes for the static tier.
            raise PlanesValidationError(f"static tier requires plane sizes in px (got `{unit}` for {axis})")
        raise PlanesValidationError(f"unsupported plane size unit `{unit}` for {axis}")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    raise PlanesValidationError(f"plane {axis} must be a number or unitized object")


def _serialize_components(
    components_raw: Any,
    planes: list[dict[str, Any]],
    container_root: Path | None,
) -> list[dict[str, Any]]:
    if not isinstance(components_raw, list):
        return []
    plane_by_id = {plane["id"]: plane for plane in planes}
    serialized: list[dict[str, Any]] = []
    for index, raw in enumerate(components_raw):
        component = raw if isinstance(raw, Mapping) else {}
        plane_id = str(component.get("attach_to", ""))
        if plane_id not in plane_by_id:
            raise PlanesValidationError(
                f"components[{index}] must attach to a declared plane for the static tier"
            )
        frame = _component_frame(component, plane_id, plane_by_id)
        if frame != "screen_tl":
            raise PlanesValidationError(
                f"components[{index}] uses unsupported frame `{frame}` for the static tier (screen_tl only)"
            )
        position = component.get("position")
        if not isinstance(position, Mapping):
            raise PlanesValidationError(f"components[{index}].position must be an object")
        size = component.get("size")
        if not isinstance(size, Mapping):
            raise PlanesValidationError(f"components[{index}].size must be an object")
        unit, x, y = _serialize_position(position)
        width = _size_unit_value(size.get("width"), "width")
        height = _size_unit_value(size.get("height"), "height")
        props = component.get("props")
        props_obj = dict(props) if isinstance(props, Mapping) else {}
        comp_type = str(component.get("type", ""))
        entry: dict[str, Any] = {
            "id": str(component.get("id", "")),
            "type": comp_type,
            "plane_id": plane_id,
            "z": int(component.get("component_local_z", component.get("z_index", 0))),
            "x": x,
            "y": y,
            "unit": unit,
            "width": width,
            "height": height,
            "opacity": float(component.get("opacity", 1.0)),
            "trigger": _component_trigger(component, index),
        }
        if comp_type == "text":
            entry["text"] = str(props_obj.get("text", ""))
            entry["font_size_px"] = float(props_obj.get("font_size_px", _DEFAULT_FONT_SIZE_PX))
            entry["color_hex"] = str(props_obj.get("color_hex", _DEFAULT_TEXT_COLOR))
        elif comp_type == "svg":
            entry["svg_data_url"] = _svg_data_url(props_obj.get("svg"), container_root, index)
        else:
            raise PlanesValidationError(
                f"components[{index}] type `{comp_type}` is not supported by the static tier"
            )
        serialized.append(entry)
    return serialized


def _component_frame(component: Mapping[str, Any], plane_id: str, plane_by_id: Mapping[str, Any]) -> str:
    position = component.get("position")
    if isinstance(position, Mapping):
        frame = position.get("frame")
        if isinstance(frame, str) and frame.strip():
            return frame
    plane = plane_by_id.get(plane_id, {})
    return str(plane.get("default_frame", "screen_tl"))


def _serialize_position(position: Mapping[str, Any]) -> tuple[str, float, float]:
    x = position.get("x", 0)
    y = position.get("y", 0)
    if not isinstance(x, (int, float)) or isinstance(x, bool):
        raise PlanesValidationError("static tier positions must be plain numbers (screen_tl px)")
    if not isinstance(y, (int, float)) or isinstance(y, bool):
        raise PlanesValidationError("static tier positions must be plain numbers (screen_tl px)")
    return ("px", float(x), float(y))


def _size_unit_value(raw: Any, axis: str) -> float:
    if isinstance(raw, Mapping):
        unit = str(raw.get("unit", "px"))
        if unit not in SUPPORTED_POSITION_UNITS:
            raise PlanesValidationError(
                f"static tier supports px/vw/vh sizes (got `{unit}` for {axis})"
            )
        return float(raw.get("value", 0.0))
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    raise PlanesValidationError(f"size {axis} must be a number or unitized object")


def _component_trigger(component: Mapping[str, Any], index: int) -> str | None:
    functions = component.get("functions")
    if not isinstance(functions, Mapping):
        return None
    trigger: str | None = None
    for hook, target in functions.items():
        if not isinstance(target, str):
            continue
        if target.startswith("trigger:"):
            name = target[len("trigger:") :].strip()
            if trigger is not None and trigger != name:
                raise PlanesValidationError(
                    f"components[{index}] binds multiple different triggers; the static tier requires one"
                )
            trigger = name
    return trigger


def _svg_data_url(svg_source: Any, container_root: Path | None, index: int) -> str:
    if not isinstance(svg_source, str) or not svg_source.strip():
        raise PlanesValidationError(f"components[{index}] svg requires props.svg")
    if svg_source.startswith("data:"):
        return svg_source
    if container_root is None:
        raise PlanesValidationError(
            f"components[{index}] svg file assets require compiling from a container path"
        )
    svg_path = (container_root / svg_source).resolve()
    if not svg_path.exists():
        raise PlanesValidationError(f"components[{index}] svg asset not found: {svg_source}")
    encoded = base64.b64encode(svg_path.read_text(encoding="utf-8").encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _bindings_are_declarative(components_raw: Any) -> bool:
    if not isinstance(components_raw, list):
        return True
    for raw in components_raw:
        component = raw if isinstance(raw, Mapping) else {}
        functions = component.get("functions")
        if not isinstance(functions, Mapping):
            continue
        for target in functions.values():
            if not isinstance(target, str) or not target.startswith("trigger:"):
                return False
    return True