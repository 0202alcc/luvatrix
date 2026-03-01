from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ui_ir import CoordinateRef, InteractionBinding, MatrixSpec, UIIRAsset, UIIRComponent, UIIRPage


SUPPORTED_HDI_HOOKS = {
    "on_press_down",
    "on_press_repeat",
    "on_press_hold_start",
    "on_press_hold_tick",
    "on_press_up",
    "on_press_hold_end",
    "on_press_single",
    "on_press_double",
    "on_press_cancel",
    "on_hover_start",
    "on_hover_end",
    "on_drag_start",
    "on_drag_move",
    "on_drag_end",
    "on_scroll",
    "on_pinch",
    "on_rotate",
}


@dataclass(frozen=True)
class PlanesAppMetadata:
    title: str
    icon: str
    tab_title: str
    tab_icon: str


class PlanesValidationError(ValueError):
    pass


def resolve_web_metadata(app: dict[str, Any]) -> PlanesAppMetadata:
    title = _require_str(app.get("title"), "app.title")
    icon = _require_str(app.get("icon"), "app.icon")
    web = app.get("web") or {}
    if not isinstance(web, dict):
        raise PlanesValidationError("app.web must be an object")
    tab_title = web.get("tab_title")
    tab_icon = web.get("tab_icon")
    if tab_title is None:
        tab_title = title
    if tab_icon is None:
        tab_icon = icon
    if not isinstance(tab_title, str) or not tab_title.strip():
        raise PlanesValidationError("app.web.tab_title must be a non-empty string")
    if not isinstance(tab_icon, str) or not tab_icon.strip():
        raise PlanesValidationError("app.web.tab_icon must be a non-empty string")
    return PlanesAppMetadata(title=title, icon=icon, tab_title=tab_title, tab_icon=tab_icon)


def validate_planes_payload(payload: dict[str, Any], *, strict: bool = True) -> None:
    _ = strict
    _require_str(payload.get("planes_protocol_version"), "planes_protocol_version")
    app = _expect_obj(payload.get("app"), "app")
    plane = _expect_obj(payload.get("plane"), "plane")
    components = payload.get("components")
    if not isinstance(components, list):
        raise PlanesValidationError("components must be a list")
    scripts = payload.get("scripts", [])
    if not isinstance(scripts, list):
        raise PlanesValidationError("scripts must be a list")

    resolve_web_metadata(app)
    _require_str(app.get("id"), "app.id")
    _require_str(plane.get("id"), "plane.id")
    _require_str(plane.get("default_frame"), "plane.default_frame")

    script_ids: set[str] = set()
    for i, script in enumerate(scripts):
        script_obj = _expect_obj(script, f"scripts[{i}]")
        script_id = _require_str(script_obj.get("id"), f"scripts[{i}].id")
        _require_str(script_obj.get("lang"), f"scripts[{i}].lang")
        _require_str(script_obj.get("src"), f"scripts[{i}].src")
        if script_id in script_ids:
            raise PlanesValidationError(f"duplicate script id: {script_id}")
        script_ids.add(script_id)

    component_ids: set[str] = set()
    for i, comp in enumerate(components):
        comp_obj = _expect_obj(comp, f"components[{i}]")
        comp_id = _require_str(comp_obj.get("id"), f"components[{i}].id")
        if comp_id in component_ids:
            raise PlanesValidationError(f"duplicate component id: {comp_id}")
        component_ids.add(comp_id)
        _require_str(comp_obj.get("type"), f"components[{i}].type")
        _expect_obj(comp_obj.get("position"), f"components[{i}].position")
        _expect_obj(comp_obj.get("size"), f"components[{i}].size")
        if not isinstance(comp_obj.get("z_index", 0), int):
            raise PlanesValidationError(f"components[{i}].z_index must be int")

        functions = comp_obj.get("functions", {})
        if not isinstance(functions, dict):
            raise PlanesValidationError(f"components[{i}].functions must be an object")
        for hook_name, target in functions.items():
            if hook_name not in SUPPORTED_HDI_HOOKS:
                raise PlanesValidationError(f"unsupported hook `{hook_name}`")
            if not isinstance(target, str) or "::" not in target:
                raise PlanesValidationError(
                    f"components[{i}].functions.{hook_name} must use <script_id>::<function_name>"
                )
            script_id, fn_name = target.split("::", 1)
            if not script_id or not fn_name:
                raise PlanesValidationError(
                    f"components[{i}].functions.{hook_name} has invalid target `{target}`"
                )
            if script_ids and script_id not in script_ids:
                raise PlanesValidationError(
                    f"components[{i}].functions.{hook_name} references unknown script `{script_id}`"
                )

        if comp_obj.get("type") == "viewport":
            props = _expect_obj(comp_obj.get("props", {}), f"components[{i}].props")
            if props.get("clip") is not True:
                raise PlanesValidationError("viewport requires props.clip=true")
            _require_str(props.get("content_ref"), f"components[{i}].props.content_ref")
            scroll = _expect_obj(props.get("scroll", {}), f"components[{i}].props.scroll")
            if not isinstance(scroll.get("x", 0), (int, float)) or not isinstance(scroll.get("y", 0), (int, float)):
                raise PlanesValidationError("viewport props.scroll requires numeric x/y")


def compile_planes_to_ui_ir(
    payload: dict[str, Any],
    *,
    matrix_width: int,
    matrix_height: int,
    aspect_mode: str = "stretch",
    strict: bool = True,
) -> UIIRPage:
    validate_planes_payload(payload, strict=strict)
    app = _expect_obj(payload["app"], "app")
    plane = _expect_obj(payload["plane"], "plane")
    components_raw = payload["components"]
    default_frame = str(plane["default_frame"])

    components: list[UIIRComponent] = []
    for comp in components_raw:
        comp_obj = _expect_obj(comp, "component")
        pos = _expect_obj(comp_obj["position"], "component.position")
        frame = pos.get("frame")
        if frame is not None and not isinstance(frame, str):
            raise PlanesValidationError("component.position.frame must be string")
        width = _resolve_dimension(_expect_obj(comp_obj["size"], "component.size").get("width"), matrix_width, matrix_height)
        height = _resolve_dimension(_expect_obj(comp_obj["size"], "component.size").get("height"), matrix_width, matrix_height)
        interactions = _compile_interactions(comp_obj.get("functions", {}))
        comp_type = str(comp_obj["type"])
        props = comp_obj.get("props", {})
        style: dict[str, Any] = props if isinstance(props, dict) else {}
        asset = None
        if comp_type == "svg":
            svg_source = _require_str(style.get("svg"), "component.props.svg")
            asset = UIIRAsset(kind="svg", source=svg_source)
        components.append(
            UIIRComponent(
                component_id=str(comp_obj["id"]),
                component_type=comp_type,
                position=CoordinateRef(float(pos.get("x", 0.0)), float(pos.get("y", 0.0)), frame=frame),
                width=width,
                height=height,
                z_index=int(comp_obj.get("z_index", 0)),
                visible=bool(comp_obj.get("visible", True)),
                style=style,
                interactions=interactions,
                asset=asset,
            )
        )

    return UIIRPage(
        ir_version="planes-v0",
        app_protocol_version=str(payload.get("planes_protocol_version", "0.1.0")),
        page_id=str(plane["id"]),
        matrix=MatrixSpec(width=matrix_width, height=matrix_height),
        aspect_mode="preserve" if aspect_mode == "preserve" else "stretch",
        default_frame=default_frame,
        background=str(_expect_obj(plane.get("background", {}), "plane.background").get("color", "#000000")),
        components=tuple(components),
        route=f"planes:{app.get('id', '')}",
    )


def _compile_interactions(functions: Any) -> tuple[InteractionBinding, ...]:
    if not isinstance(functions, dict):
        raise PlanesValidationError("component.functions must be an object")
    out: list[InteractionBinding] = []
    for event, handler in functions.items():
        if not isinstance(event, str):
            raise PlanesValidationError("interaction event must be string")
        if event not in SUPPORTED_HDI_HOOKS:
            raise PlanesValidationError(f"unsupported hook `{event}`")
        if not isinstance(handler, str):
            raise PlanesValidationError(f"handler for {event} must be string")
        out.append(InteractionBinding(event=event, handler=handler))
    return tuple(out)


def _resolve_dimension(raw: Any, viewport_w: int, viewport_h: int) -> float:
    spec = _expect_obj(raw, "dimension")
    unit = _require_str(spec.get("unit"), "dimension.unit")
    value = spec.get("value")
    if not isinstance(value, (int, float)):
        raise PlanesValidationError("dimension.value must be numeric")
    v = float(value)
    if unit == "px":
        return v
    if unit == "vw":
        return (v / 100.0) * float(viewport_w)
    if unit == "vh":
        return (v / 100.0) * float(viewport_h)
    if unit == "%":
        return (v / 100.0) * float(viewport_w)
    if unit == "pt":
        return v * (96.0 / 72.0)
    if unit == "cm":
        return v * (96.0 / 2.54)
    raise PlanesValidationError(f"unsupported unit: {unit}")


def _expect_obj(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlanesValidationError(f"{name} must be an object")
    return value


def _require_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlanesValidationError(f"{name} must be a non-empty string")
    return value
