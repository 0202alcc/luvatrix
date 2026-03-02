from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ui_ir import (
    BoundingBoxSpec,
    CoordinateRef,
    InteractionBinding,
    MatrixSpec,
    UIIRAsset,
    UIIRComponent,
    UIIRPage,
    UIIRPlaneRef,
    UIIRSectionCut,
)


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
    _require_str(payload.get("planes_protocol_version"), "planes_protocol_version")
    app = _expect_obj(payload.get("app"), "app")
    resolve_web_metadata(app)
    _require_str(app.get("id"), "app.id")

    components = payload.get("components")
    if not isinstance(components, list):
        raise PlanesValidationError("components must be a list")
    scripts = payload.get("scripts", [])
    if not isinstance(scripts, list):
        raise PlanesValidationError("scripts must be a list")

    has_v2 = isinstance(payload.get("planes"), list)
    if has_v2:
        _validate_v2_payload(payload, strict=strict)
    else:
        _validate_v0_payload(payload, strict=strict)

    script_ids = _validate_scripts(scripts)
    _validate_components(payload, components, script_ids, strict=strict, has_v2=has_v2)


def compile_planes_to_ui_ir(
    payload: dict[str, Any],
    *,
    matrix_width: int,
    matrix_height: int,
    aspect_mode: str = "stretch",
    strict: bool = True,
) -> UIIRPage:
    validate_planes_payload(payload, strict=strict)
    if isinstance(payload.get("planes"), list):
        return _compile_v2(payload, matrix_width=matrix_width, matrix_height=matrix_height, aspect_mode=aspect_mode)
    return _compile_v0(payload, matrix_width=matrix_width, matrix_height=matrix_height, aspect_mode=aspect_mode)


def _compile_v0(payload: dict[str, Any], *, matrix_width: int, matrix_height: int, aspect_mode: str) -> UIIRPage:
    app = _expect_obj(payload["app"], "app")
    plane = _expect_obj(payload["plane"], "plane")
    components_raw = payload["components"]
    default_frame = str(plane["default_frame"])
    plane_id = str(plane["id"])

    components: list[UIIRComponent] = []
    for mount_order, comp in enumerate(components_raw):
        comp_obj = _expect_obj(comp, "component")
        component = _compile_component(
            comp_obj,
            mount_order=mount_order,
            matrix_width=matrix_width,
            matrix_height=matrix_height,
            default_frame=default_frame,
            plane_id=plane_id,
            plane_global_z=0,
            strict=False,
            default_attachment_kind="plane",
        )
        components.append(component)

    return UIIRPage(
        ir_version="planes-v0",
        app_protocol_version=str(payload.get("planes_protocol_version", "0.1.0")),
        page_id=plane_id,
        matrix=MatrixSpec(width=matrix_width, height=matrix_height),
        aspect_mode="preserve" if aspect_mode == "preserve" else "stretch",
        default_frame=default_frame,
        background=str(_expect_obj(plane.get("background", {}), "plane.background").get("color", "#000000")),
        components=tuple(components),
        route=f"planes:{app.get('id', '')}",
    )


def _compile_v2(payload: dict[str, Any], *, matrix_width: int, matrix_height: int, aspect_mode: str) -> UIIRPage:
    app = _expect_obj(payload["app"], "app")
    planes_raw = payload["planes"]
    assert isinstance(planes_raw, list)
    components_raw = payload["components"]
    routes_raw = payload.get("routes", [])
    section_cuts_raw = payload.get("section_cuts", [])
    if not isinstance(routes_raw, list):
        routes_raw = []
    if not isinstance(section_cuts_raw, list):
        section_cuts_raw = []

    plane_map: dict[str, UIIRPlaneRef] = {}
    ordered_planes: list[UIIRPlaneRef] = []
    first_background = "#000000"
    default_frame = "screen_tl"

    for i, raw in enumerate(planes_raw):
        plane_obj = _expect_obj(raw, f"planes[{i}]")
        plane_id = _require_str(plane_obj.get("id"), f"planes[{i}].id")
        frame = _require_str(plane_obj.get("default_frame"), f"planes[{i}].default_frame")
        bg = _expect_obj(plane_obj.get("background", {}), f"planes[{i}].background")
        if i == 0:
            first_background = str(bg.get("color", "#000000"))
            default_frame = frame
        plane_global_z = int(plane_obj.get("plane_global_z", 0))
        pos = _expect_obj(plane_obj.get("position", {"x": 0.0, "y": 0.0}), f"planes[{i}].position")
        size = _expect_obj(
            plane_obj.get(
                "size",
                {
                    "width": {"unit": "px", "value": matrix_width},
                    "height": {"unit": "px", "value": matrix_height},
                },
            ),
            f"planes[{i}].size",
        )
        px = float(pos.get("x", 0.0))
        py = float(pos.get("y", 0.0))
        pw = _resolve_dimension(size.get("width"), matrix_width, matrix_height)
        ph = _resolve_dimension(size.get("height"), matrix_width, matrix_height)
        plane_ref = UIIRPlaneRef(
            plane_id=plane_id,
            plane_global_z=plane_global_z,
            active=bool(plane_obj.get("active", True)),
            resolved_position=CoordinateRef(x=px, y=py, frame=str(pos.get("frame", frame))),
            resolved_bounds=BoundingBoxSpec(x=px, y=py, width=pw, height=ph, frame=str(pos.get("frame", frame))),
            default_frame=frame,
        )
        plane_map[plane_id] = plane_ref
        ordered_planes.append(plane_ref)

    ordered_planes.sort(key=lambda p: (p.plane_global_z, p.plane_id))
    active_route_id, active_plane_ids = _resolve_route_activation(routes_raw, ordered_planes)
    if not active_plane_ids:
        active_plane_ids = tuple(p.plane_id for p in ordered_planes if p.active)

    section_cuts: list[UIIRSectionCut] = []
    for i, raw in enumerate(section_cuts_raw):
        cut = _expect_obj(raw, f"section_cuts[{i}]")
        region = _expect_obj(cut.get("region"), f"section_cuts[{i}].region")
        section_cuts.append(
            UIIRSectionCut(
                cut_id=_require_str(cut.get("id"), f"section_cuts[{i}].id"),
                owner_plane_id=_require_str(cut.get("owner_plane_id"), f"section_cuts[{i}].owner_plane_id"),
                target_plane_ids=tuple(str(t) for t in cut.get("target_plane_ids", []) if isinstance(t, str)),
                region_bounds=BoundingBoxSpec(
                    x=float(region.get("x", 0.0)),
                    y=float(region.get("y", 0.0)),
                    width=float(region.get("width", 0.0)),
                    height=float(region.get("height", 0.0)),
                    frame=None if region.get("frame") is None else str(region.get("frame")),
                ),
                enabled=bool(cut.get("enabled", True)),
            )
        )

    components: list[UIIRComponent] = []
    for mount_order, comp in enumerate(components_raw):
        comp_obj = _expect_obj(comp, "component")
        attachment_kind = str(comp_obj.get("attachment_kind", "plane"))
        attach_to = comp_obj.get("attach_to")
        plane_id = str(attach_to) if isinstance(attach_to, str) else None
        plane_global_z: int | None = None
        if attachment_kind == "plane":
            if plane_id is None:
                plane_id = ordered_planes[0].plane_id
            plane_global_z = plane_map[plane_id].plane_global_z
            default_component_frame = plane_map[plane_id].default_frame
        else:
            default_component_frame = default_frame
        component = _compile_component(
            comp_obj,
            mount_order=mount_order,
            matrix_width=matrix_width,
            matrix_height=matrix_height,
            default_frame=default_component_frame,
            plane_id=plane_id if attachment_kind == "plane" else None,
            plane_global_z=plane_global_z,
            strict=True,
            default_attachment_kind=attachment_kind,
        )
        components.append(component)

    return UIIRPage(
        ir_version="planes-v2",
        app_protocol_version=str(payload.get("planes_protocol_version", "0.2.0-dev")),
        page_id=str(app.get("id", "planes-v2")),
        matrix=MatrixSpec(width=matrix_width, height=matrix_height),
        aspect_mode="preserve" if aspect_mode == "preserve" else "stretch",
        default_frame=default_frame,
        background=first_background,
        components=tuple(components),
        route=f"planes:{app.get('id', '')}",
        active_route_id=active_route_id,
        active_plane_ids=active_plane_ids,
        ordering_contract_version="plane-z-local-z-overlay-v1",
        section_cuts=tuple(section_cuts),
        plane_manifest=tuple(ordered_planes),
    )


def _compile_component(
    comp_obj: dict[str, Any],
    *,
    mount_order: int,
    matrix_width: int,
    matrix_height: int,
    default_frame: str,
    plane_id: str | None,
    plane_global_z: int | None,
    strict: bool,
    default_attachment_kind: str,
) -> UIIRComponent:
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

    attachment_kind = str(comp_obj.get("attachment_kind", default_attachment_kind))
    if strict and attachment_kind not in {"plane", "camera_overlay"}:
        raise PlanesValidationError("component.attachment_kind must be `plane` or `camera_overlay`")
    if attachment_kind not in {"plane", "camera_overlay"}:
        attachment_kind = default_attachment_kind
    component_local_z = int(comp_obj.get("component_local_z", comp_obj.get("z_index", 0)))
    blend_mode = str(comp_obj.get("blend_mode", "absolute_rgba"))
    if blend_mode not in {"absolute_rgba", "delta_rgba"}:
        if strict:
            raise PlanesValidationError("component.blend_mode must be `absolute_rgba` or `delta_rgba`")
        blend_mode = "absolute_rgba"
    attachment_rank = 0 if attachment_kind == "plane" else 1
    stable_order_key = (
        attachment_rank,
        int(plane_global_z or 0),
        int(component_local_z),
        int(mount_order),
    )
    px = float(pos.get("x", 0.0))
    py = float(pos.get("y", 0.0))
    comp_frame = frame if isinstance(frame, str) else default_frame
    world_bounds = BoundingBoxSpec(x=px, y=py, width=width, height=height, frame=comp_frame)
    return UIIRComponent(
        component_id=str(comp_obj["id"]),
        component_type=comp_type,
        position=CoordinateRef(px, py, frame=frame),
        width=width,
        height=height,
        z_index=int(comp_obj.get("z_index", 0)),
        visible=bool(comp_obj.get("visible", True)),
        style=style,
        interactions=interactions,
        asset=asset,
        attachment_kind="camera_overlay" if attachment_kind == "camera_overlay" else "plane",
        plane_id=plane_id if attachment_kind == "plane" else None,
        plane_global_z=plane_global_z if attachment_kind == "plane" else None,
        component_local_z=component_local_z,
        blend_mode=blend_mode,
        world_bounds=world_bounds,
        world_bounds_hint=world_bounds,
        culling_hint={},
        section_cut_refs=(),
        stable_order_key=stable_order_key,
    )


def _validate_v0_payload(payload: dict[str, Any], *, strict: bool) -> None:
    _ = strict
    plane = _expect_obj(payload.get("plane"), "plane")
    _require_str(plane.get("id"), "plane.id")
    _require_str(plane.get("default_frame"), "plane.default_frame")


def _validate_v2_payload(payload: dict[str, Any], *, strict: bool) -> None:
    planes = payload.get("planes")
    if not isinstance(planes, list) or not planes:
        raise PlanesValidationError("planes must be a non-empty list")
    plane_ids: set[str] = set()
    for i, raw in enumerate(planes):
        plane = _expect_obj(raw, f"planes[{i}]")
        plane_id = _require_str(plane.get("id"), f"planes[{i}].id")
        if plane_id in plane_ids:
            raise PlanesValidationError(f"duplicate plane id: {plane_id}")
        plane_ids.add(plane_id)
        _require_str(plane.get("default_frame"), f"planes[{i}].default_frame")
        if strict and "plane_global_z" not in plane:
            raise PlanesValidationError(f"planes[{i}].plane_global_z required in strict mode")
        _expect_obj(plane.get("background", {}), f"planes[{i}].background")

    cuts = payload.get("section_cuts", [])
    if not isinstance(cuts, list):
        raise PlanesValidationError("section_cuts must be a list")
    for i, raw in enumerate(cuts):
        cut = _expect_obj(raw, f"section_cuts[{i}]")
        _require_str(cut.get("id"), f"section_cuts[{i}].id")
        owner = _require_str(cut.get("owner_plane_id"), f"section_cuts[{i}].owner_plane_id")
        if owner not in plane_ids:
            raise PlanesValidationError(f"section_cuts[{i}].owner_plane_id references unknown plane `{owner}`")
        targets = cut.get("target_plane_ids", [])
        if not isinstance(targets, list):
            raise PlanesValidationError(f"section_cuts[{i}].target_plane_ids must be list")
        for t in targets:
            if not isinstance(t, str) or t not in plane_ids:
                raise PlanesValidationError(f"section_cuts[{i}] has unknown target plane `{t}`")
        _expect_obj(cut.get("region"), f"section_cuts[{i}].region")

    routes = payload.get("routes", [])
    if not isinstance(routes, list):
        raise PlanesValidationError("routes must be a list")
    for i, raw in enumerate(routes):
        route = _expect_obj(raw, f"routes[{i}]")
        _require_str(route.get("id"), f"routes[{i}].id")
        active = route.get("active_planes", [])
        if not isinstance(active, list):
            raise PlanesValidationError(f"routes[{i}].active_planes must be list")
        for plane_id in active:
            if not isinstance(plane_id, str) or plane_id not in plane_ids:
                raise PlanesValidationError(f"routes[{i}] references unknown plane `{plane_id}`")


def _validate_scripts(scripts: list[Any]) -> set[str]:
    script_ids: set[str] = set()
    for i, script in enumerate(scripts):
        script_obj = _expect_obj(script, f"scripts[{i}]")
        script_id = _require_str(script_obj.get("id"), f"scripts[{i}].id")
        _require_str(script_obj.get("lang"), f"scripts[{i}].lang")
        _require_str(script_obj.get("src"), f"scripts[{i}].src")
        if script_id in script_ids:
            raise PlanesValidationError(f"duplicate script id: {script_id}")
        script_ids.add(script_id)
    return script_ids


def _validate_components(
    payload: dict[str, Any],
    components: list[Any],
    script_ids: set[str],
    *,
    strict: bool,
    has_v2: bool,
) -> None:
    component_ids: set[str] = set()
    plane_ids: set[str] = set()
    if has_v2:
        planes = payload.get("planes", [])
        assert isinstance(planes, list)
        for raw in planes:
            if isinstance(raw, dict) and isinstance(raw.get("id"), str):
                plane_ids.add(raw["id"])
    else:
        plane = payload.get("plane")
        if isinstance(plane, dict) and isinstance(plane.get("id"), str):
            plane_ids.add(plane["id"])

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

        if has_v2:
            attachment_kind = comp_obj.get("attachment_kind")
            if strict and not isinstance(attachment_kind, str):
                raise PlanesValidationError(f"components[{i}].attachment_kind is required in strict v2 mode")
            if attachment_kind is not None and attachment_kind not in {"plane", "camera_overlay"}:
                raise PlanesValidationError(f"components[{i}].attachment_kind invalid")
            if isinstance(attachment_kind, str) and attachment_kind == "plane":
                attach_to = comp_obj.get("attach_to")
                if not isinstance(attach_to, str) or attach_to not in plane_ids:
                    raise PlanesValidationError(f"components[{i}].attach_to must reference an existing plane")

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


def _resolve_route_activation(routes_raw: list[Any], planes: list[UIIRPlaneRef]) -> tuple[str | None, tuple[str, ...]]:
    if not routes_raw:
        return (None, tuple(p.plane_id for p in planes if p.active))
    default_route: dict[str, Any] | None = None
    for raw in routes_raw:
        if isinstance(raw, dict) and bool(raw.get("default", False)):
            default_route = raw
            break
    if default_route is None:
        for raw in routes_raw:
            if isinstance(raw, dict):
                default_route = raw
                break
    if default_route is None:
        return (None, tuple(p.plane_id for p in planes if p.active))
    route_id = str(default_route.get("id", ""))
    active = default_route.get("active_planes", [])
    if not isinstance(active, list):
        return (route_id or None, tuple(p.plane_id for p in planes if p.active))
    return (route_id or None, tuple(str(p) for p in active if isinstance(p, str)))


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
