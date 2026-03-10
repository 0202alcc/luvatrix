from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .ui_ir import (
    BoundingBoxSpec,
    CoordinateFrameSpec,
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
DEFAULT_COORD_FRAME = "cartesian_center"


class _InlineFrameResolver:
    def __init__(self, *, matrix_width: int, matrix_height: int, app_default_frame: str) -> None:
        from luvatrix_core.core.coordinates import CoordinateFrameRegistry

        self._matrix_width = int(matrix_width)
        self._matrix_height = int(matrix_height)
        self._app_default_frame = str(app_default_frame)
        self._registry = CoordinateFrameRegistry(
            width=max(1, int(matrix_width)),
            height=max(1, int(matrix_height)),
            default_frame="screen_tl",
        )
        self._frames_by_key: dict[tuple[float, float, float, float, float, float], str] = {}
        self._specs: list[CoordinateFrameSpec] = []

    def resolve_frame_id(
        self,
        raw: Any,
        *,
        name: str,
        parent_w: float | None = None,
        parent_h: float | None = None,
    ) -> str:
        if isinstance(raw, str):
            if not raw.strip():
                raise PlanesValidationError(f"{name} must be non-empty when string")
            return str(raw)
        frame_obj = _expect_obj(raw, name)
        origin = _parse_pair(frame_obj.get("origin"), field_name=f"{name}.origin")
        basis_x = _parse_pair(frame_obj.get("basis_x"), field_name=f"{name}.basis_x")
        basis_y = _parse_pair(frame_obj.get("basis_y"), field_name=f"{name}.basis_y")
        try:
            basis_xf = (float(basis_x[0]), float(basis_x[1]))
            basis_yf = (float(basis_y[0]), float(basis_y[1]))
        except Exception as exc:  # noqa: BLE001
            raise PlanesValidationError(f"{name}.basis_x/basis_y must contain numeric values") from exc
        origin_x = _resolve_unitized_scalar(
            origin[0],
            viewport_w=self._matrix_width,
            viewport_h=self._matrix_height,
            parent_w=parent_w,
            parent_h=parent_h,
            axis="x",
            name=f"{name}.origin[0]",
        )
        origin_y = _resolve_unitized_scalar(
            origin[1],
            viewport_w=self._matrix_width,
            viewport_h=self._matrix_height,
            parent_w=parent_w,
            parent_h=parent_h,
            axis="y",
            name=f"{name}.origin[1]",
        )
        try:
            tl_x, tl_y = self._registry.transform_point(
                (float(origin_x), float(origin_y)),
                from_frame=self._app_default_frame,
                to_frame="screen_tl",
            )
        except Exception as exc:  # noqa: BLE001
            raise PlanesValidationError(
                f"{name}.origin cannot be resolved from app.default_frame `{self._app_default_frame}`"
            ) from exc
        key = (
            round(float(tl_x), 6),
            round(float(tl_y), 6),
            round(float(basis_xf[0]), 6),
            round(float(basis_xf[1]), 6),
            round(float(basis_yf[0]), 6),
            round(float(basis_yf[1]), 6),
        )
        cached = self._frames_by_key.get(key)
        if cached is not None:
            return cached
        frame_name = f"inline_frame_{len(self._specs):03d}"
        self._frames_by_key[key] = frame_name
        self._specs.append(
            CoordinateFrameSpec(
                name=frame_name,
                origin=(float(tl_x), float(tl_y)),
                basis_x=basis_xf,
                basis_y=basis_yf,
            )
        )
        return frame_name

    def specs(self) -> tuple[CoordinateFrameSpec, ...]:
        return tuple(self._specs)


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


def _resolve_app_default_frame(app: dict[str, Any]) -> str:
    raw = app.get("default_frame")
    if raw is None:
        return DEFAULT_COORD_FRAME
    if not isinstance(raw, str) or not raw.strip():
        raise PlanesValidationError("app.default_frame must be a non-empty string")
    return str(raw)


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


def compile_split_to_canonical_ir(
    payload: dict[str, Any],
    *,
    matrix_width: int,
    matrix_height: int,
    aspect_mode: str = "stretch",
    strict: bool = True,
) -> UIIRPage:
    """Compile split-file Planes payloads to canonical Planes IR."""
    validate_planes_payload(payload, strict=strict)
    if not isinstance(payload.get("planes"), list):
        raise PlanesValidationError("split-file canonical compile requires `planes` payload")
    return _compile_v2(payload, matrix_width=matrix_width, matrix_height=matrix_height, aspect_mode=aspect_mode)


def compile_monolith_to_canonical_ir(
    payload: dict[str, Any],
    *,
    matrix_width: int,
    matrix_height: int,
    aspect_mode: str = "stretch",
    strict: bool = True,
) -> UIIRPage:
    """Compile monolith Planes payloads to canonical Planes IR via adapter."""
    validate_planes_payload(payload, strict=strict)
    if isinstance(payload.get("planes"), list):
        raise PlanesValidationError("monolith canonical compile requires legacy `plane` payload")
    adapted = _adapt_v0_payload_to_v2(payload)
    return _compile_v2(adapted, matrix_width=matrix_width, matrix_height=matrix_height, aspect_mode=aspect_mode)


def compile_to_canonical_ir(
    payload: dict[str, Any],
    *,
    matrix_width: int,
    matrix_height: int,
    aspect_mode: str = "stretch",
    strict: bool = True,
) -> UIIRPage:
    if isinstance(payload.get("planes"), list):
        return compile_split_to_canonical_ir(
            payload,
            matrix_width=matrix_width,
            matrix_height=matrix_height,
            aspect_mode=aspect_mode,
            strict=strict,
        )
    return compile_monolith_to_canonical_ir(
        payload,
        matrix_width=matrix_width,
        matrix_height=matrix_height,
        aspect_mode=aspect_mode,
        strict=strict,
    )


def _adapt_v0_payload_to_v2(payload: dict[str, Any]) -> dict[str, Any]:
    app = _expect_obj(payload["app"], "app")
    plane = _expect_obj(payload["plane"], "plane")
    plane_id = _require_str(plane.get("id"), "plane.id")
    app_default_frame = _resolve_app_default_frame(app)
    default_frame_raw = plane.get("default_frame")
    if default_frame_raw is None:
        default_frame = app_default_frame
    else:
        default_frame = _require_str(default_frame_raw, "plane.default_frame")
    background = _expect_obj(plane.get("background", {}), "plane.background")

    components_raw = payload.get("components", [])
    if not isinstance(components_raw, list):
        raise PlanesValidationError("components must be a list")
    components: list[dict[str, Any]] = []
    for raw in components_raw:
        comp = _expect_obj(raw, "component")
        adapted_comp = dict(comp)
        attachment_kind = adapted_comp.get("attachment_kind", "plane")
        if attachment_kind == "plane" and "attach_to" not in adapted_comp:
            adapted_comp["attach_to"] = plane_id
        adapted_comp["attachment_kind"] = attachment_kind
        components.append(adapted_comp)

    return {
        "planes_protocol_version": payload.get("planes_protocol_version", "0.2.0-dev"),
        "app": app,
        "planes": [
            {
                "id": plane_id,
                "default_frame": default_frame,
                "background": background,
                "plane_global_z": 0,
                "position": {"x": 0, "y": 0, "frame": default_frame},
                "size": {
                    "width": {"unit": "px", "value": 1920},
                    "height": {"unit": "px", "value": 1080},
                },
            }
        ],
        "routes": [{"id": "monolith-default", "default": True, "active_planes": [plane_id]}],
        "scripts": payload.get("scripts", []),
        "components": components,
    }


def _compile_v0(payload: dict[str, Any], *, matrix_width: int, matrix_height: int, aspect_mode: str) -> UIIRPage:
    app = _expect_obj(payload["app"], "app")
    plane = _expect_obj(payload["plane"], "plane")
    components_raw = payload["components"]
    app_default_frame = _resolve_app_default_frame(app)
    default_frame = str(plane.get("default_frame", app_default_frame))
    frame_resolver = _InlineFrameResolver(
        matrix_width=matrix_width,
        matrix_height=matrix_height,
        app_default_frame=app_default_frame,
    )
    plane_id = str(plane["id"])

    components: list[UIIRComponent] = []
    for mount_order, comp in enumerate(components_raw):
        comp_obj = _expect_obj(comp, "component")
        component = _compile_component(
            comp_obj,
            mount_order=mount_order,
            matrix_width=matrix_width,
            matrix_height=matrix_height,
            parent_width=float(matrix_width),
            parent_height=float(matrix_height),
            default_frame=default_frame,
            plane_id=plane_id,
            plane_global_z=0,
            strict=False,
            default_attachment_kind="plane",
            frame_resolver=frame_resolver,
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
        coordinate_frames=frame_resolver.specs(),
        components=tuple(components),
        route=f"planes:{app.get('id', '')}",
    )


def _compile_v2(payload: dict[str, Any], *, matrix_width: int, matrix_height: int, aspect_mode: str) -> UIIRPage:
    app = _expect_obj(payload["app"], "app")
    app_default_frame = _resolve_app_default_frame(app)
    planes_raw = payload["planes"]
    assert isinstance(planes_raw, list)
    components_raw = payload["components"]
    routes_raw = payload.get("routes", [])
    section_cuts_raw = payload.get("section_cuts", [])
    if not isinstance(routes_raw, list):
        routes_raw = []
    if not isinstance(section_cuts_raw, list):
        section_cuts_raw = []
    frame_resolver = _InlineFrameResolver(
        matrix_width=matrix_width,
        matrix_height=matrix_height,
        app_default_frame=app_default_frame,
    )

    plane_map: dict[str, UIIRPlaneRef] = {}
    ordered_planes: list[UIIRPlaneRef] = []
    first_background = "#000000"
    default_frame = app_default_frame

    for i, raw in enumerate(planes_raw):
        plane_obj = _expect_obj(raw, f"planes[{i}]")
        plane_id = _require_str(plane_obj.get("id"), f"planes[{i}].id")
        frame_raw = plane_obj.get("default_frame")
        frame = _require_str(frame_raw, f"planes[{i}].default_frame") if frame_raw is not None else app_default_frame
        bg = _expect_obj(plane_obj.get("background", {}), f"planes[{i}].background")
        if i == 0:
            first_background = str(bg.get("color", "#000000"))
            default_frame = frame
        plane_global_z = _resolve_plane_depth(plane_obj, f"planes[{i}]", strict=False)
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
        px = _resolve_unitized_scalar(
            pos.get("x", 0.0),
            viewport_w=matrix_width,
            viewport_h=matrix_height,
            parent_w=float(matrix_width),
            parent_h=float(matrix_height),
            axis="x",
            name=f"planes[{i}].position.x",
        )
        py = _resolve_unitized_scalar(
            pos.get("y", 0.0),
            viewport_w=matrix_width,
            viewport_h=matrix_height,
            parent_w=float(matrix_width),
            parent_h=float(matrix_height),
            axis="y",
            name=f"planes[{i}].position.y",
        )
        pw = _resolve_dimension(size.get("width"), matrix_width, matrix_height)
        ph = _resolve_dimension(size.get("height"), matrix_width, matrix_height)
        raw_pos_frame = pos.get("frame", frame)
        pos_frame = (
            frame_resolver.resolve_frame_id(
                raw_pos_frame,
                name=f"planes[{i}].position.frame",
                parent_w=float(matrix_width),
                parent_h=float(matrix_height),
            )
            if raw_pos_frame is not None
            else frame
        )
        plane_ref = UIIRPlaneRef(
            plane_id=plane_id,
            plane_global_z=plane_global_z,
            active=bool(plane_obj.get("active", True)),
            resolved_position=CoordinateRef(x=px, y=py, frame=str(pos_frame)),
            resolved_bounds=BoundingBoxSpec(x=px, y=py, width=pw, height=ph, frame=str(pos_frame)),
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
        raw_region_frame = region.get("frame")
        section_cuts.append(
            UIIRSectionCut(
                cut_id=_require_str(cut.get("id"), f"section_cuts[{i}].id"),
                owner_plane_id=_require_str(cut.get("owner_plane_id"), f"section_cuts[{i}].owner_plane_id"),
                target_plane_ids=tuple(str(t) for t in cut.get("target_plane_ids", []) if isinstance(t, str)),
                region_bounds=BoundingBoxSpec(
                    x=_resolve_unitized_scalar(
                        region.get("x", 0.0),
                        viewport_w=matrix_width,
                        viewport_h=matrix_height,
                        parent_w=float(matrix_width),
                        parent_h=float(matrix_height),
                        axis="x",
                        name=f"section_cuts[{i}].region.x",
                    ),
                    y=_resolve_unitized_scalar(
                        region.get("y", 0.0),
                        viewport_w=matrix_width,
                        viewport_h=matrix_height,
                        parent_w=float(matrix_width),
                        parent_h=float(matrix_height),
                        axis="y",
                        name=f"section_cuts[{i}].region.y",
                    ),
                    width=_resolve_unitized_scalar(
                        region.get("width", 0.0),
                        viewport_w=matrix_width,
                        viewport_h=matrix_height,
                        parent_w=float(matrix_width),
                        parent_h=float(matrix_height),
                        axis="x",
                        name=f"section_cuts[{i}].region.width",
                    ),
                    height=_resolve_unitized_scalar(
                        region.get("height", 0.0),
                        viewport_w=matrix_width,
                        viewport_h=matrix_height,
                        parent_w=float(matrix_width),
                        parent_h=float(matrix_height),
                        axis="y",
                        name=f"section_cuts[{i}].region.height",
                    ),
                    frame=(
                        None
                        if raw_region_frame is None
                        else frame_resolver.resolve_frame_id(
                            raw_region_frame,
                            name=f"section_cuts[{i}].region.frame",
                            parent_w=float(matrix_width),
                            parent_h=float(matrix_height),
                        )
                    ),
                ),
                enabled=bool(cut.get("enabled", True)),
            )
        )

    components: list[UIIRComponent] = []
    for mount_order, comp in enumerate(components_raw):
        comp_obj = _expect_obj(comp, "component")
        attach_to_raw = comp_obj.get("attach_to")
        attach_to_norm = str(attach_to_raw).strip() if isinstance(attach_to_raw, str) else None
        legacy_kind = str(comp_obj.get("attachment_kind", "plane")).strip().lower()
        if isinstance(attach_to_norm, str) and attach_to_norm:
            if attach_to_norm in {"camera_overlay", "camera"}:
                attachment_kind = "camera_overlay"
                plane_id = None
            else:
                attachment_kind = "plane"
                plane_id = attach_to_norm
        else:
            attachment_kind = "camera_overlay" if legacy_kind == "camera_overlay" else "plane"
            plane_id = None
        plane_global_z: int | None = None
        if attachment_kind == "plane":
            if plane_id is None:
                plane_id = ordered_planes[0].plane_id
            if plane_id not in plane_map:
                raise PlanesValidationError(f"components[{mount_order}].attach_to references unknown plane `{plane_id}`")
            plane_global_z = plane_map[plane_id].plane_global_z
            default_component_frame = plane_map[plane_id].default_frame
            parent_width = float(plane_map[plane_id].resolved_bounds.width)
            parent_height = float(plane_map[plane_id].resolved_bounds.height)
        else:
            default_component_frame = default_frame
            parent_width = float(matrix_width)
            parent_height = float(matrix_height)
        component = _compile_component(
            comp_obj,
            mount_order=mount_order,
            matrix_width=matrix_width,
            matrix_height=matrix_height,
            parent_width=parent_width,
            parent_height=parent_height,
            default_frame=default_component_frame,
            plane_id=plane_id if attachment_kind == "plane" else None,
            plane_global_z=plane_global_z,
            strict=True,
            default_attachment_kind=attachment_kind,
            frame_resolver=frame_resolver,
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
        coordinate_frames=frame_resolver.specs(),
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
    parent_width: float,
    parent_height: float,
    default_frame: str,
    plane_id: str | None,
    plane_global_z: int | None,
    strict: bool,
    default_attachment_kind: str,
    frame_resolver: _InlineFrameResolver,
) -> UIIRComponent:
    pos = _expect_obj(comp_obj["position"], "component.position")
    frame = pos.get("frame")
    size_obj = _expect_obj(comp_obj["size"], "component.size")
    width, auto_width = _resolve_component_dimension(
        size_obj.get("width"),
        viewport_w=matrix_width,
        viewport_h=matrix_height,
        parent_w=parent_width,
        parent_h=parent_height,
        axis="x",
    )
    height, auto_height = _resolve_component_dimension(
        size_obj.get("height"),
        viewport_w=matrix_width,
        viewport_h=matrix_height,
        parent_w=parent_width,
        parent_h=parent_height,
        axis="y",
    )
    interactions = _compile_interactions(comp_obj.get("functions", {}))
    comp_type = str(comp_obj["type"])
    props = comp_obj.get("props", {})
    style: dict[str, Any] = dict(props) if isinstance(props, dict) else {}
    if auto_width:
        style["auto_size_width"] = True
    if auto_height:
        style["auto_size_height"] = True
    anchor = comp_obj.get("anchor")
    if isinstance(anchor, dict):
        if "x" in anchor:
            style["anchor_x"] = anchor["x"]
        if "y" in anchor:
            style["anchor_y"] = anchor["y"]
        frame_reference = anchor.get("frame_reference")
        if frame_reference is None:
            frame_reference = anchor.get("frame")
        if frame_reference is not None:
            style["anchor_frame"] = frame_reference
    asset = None
    if comp_type == "svg":
        svg_source = _require_str(style.get("svg"), "component.props.svg")
        asset = UIIRAsset(kind="svg", source=svg_source)

    attachment_kind = "camera_overlay" if default_attachment_kind == "camera_overlay" else "plane"
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
    px = _resolve_unitized_scalar(
        pos.get("x", 0.0),
        viewport_w=matrix_width,
        viewport_h=matrix_height,
        parent_w=parent_width,
        parent_h=parent_height,
        axis="x",
        name="component.position.x",
    )
    py = _resolve_unitized_scalar(
        pos.get("y", 0.0),
        viewport_w=matrix_width,
        viewport_h=matrix_height,
        parent_w=parent_width,
        parent_h=parent_height,
        axis="y",
        name="component.position.y",
    )
    comp_frame = (
        default_frame
        if frame is None
        else frame_resolver.resolve_frame_id(
            frame,
            name="component.position.frame",
            parent_w=parent_width,
            parent_h=parent_height,
        )
    )
    world_bounds = BoundingBoxSpec(x=px, y=py, width=width, height=height, frame=comp_frame)
    return UIIRComponent(
        component_id=str(comp_obj["id"]),
        component_type=comp_type,
        position=CoordinateRef(px, py, frame=comp_frame),
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
    app = _expect_obj(payload.get("app"), "app")
    _resolve_app_default_frame(app)
    plane = _expect_obj(payload.get("plane"), "plane")
    _require_str(plane.get("id"), "plane.id")
    default_frame = plane.get("default_frame")
    if default_frame is not None:
        _require_str(default_frame, "plane.default_frame")


def _validate_v2_payload(payload: dict[str, Any], *, strict: bool) -> None:
    app = _expect_obj(payload.get("app"), "app")
    app_default_frame = _resolve_app_default_frame(app)
    if not app_default_frame:
        raise PlanesValidationError("app.default_frame must be non-empty")
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
        frame = plane.get("default_frame")
        if frame is not None:
            _require_str(frame, f"planes[{i}].default_frame")
        _resolve_plane_depth(plane, f"planes[{i}]", strict=strict)
        _expect_obj(plane.get("background", {}), f"planes[{i}].background")
        position = _expect_obj(plane.get("position", {"x": 0.0, "y": 0.0}), f"planes[{i}].position")
        _validate_numeric_or_unitized(position.get("x", 0.0), f"planes[{i}].position.x")
        _validate_numeric_or_unitized(position.get("y", 0.0), f"planes[{i}].position.y")
        if "frame" in position and position.get("frame") is not None:
            _validate_frame_reference(position.get("frame"), f"planes[{i}].position.frame")
        size = _expect_obj(plane.get("size", {"width": {"unit": "px", "value": 0}, "height": {"unit": "px", "value": 0}}), f"planes[{i}].size")
        _validate_dimension_value(size.get("width"), f"planes[{i}].size.width", allow_auto=False)
        _validate_dimension_value(size.get("height"), f"planes[{i}].size.height", allow_auto=False)

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
        region = _expect_obj(cut.get("region"), f"section_cuts[{i}].region")
        _validate_numeric_or_unitized(region.get("x", 0.0), f"section_cuts[{i}].region.x")
        _validate_numeric_or_unitized(region.get("y", 0.0), f"section_cuts[{i}].region.y")
        _validate_numeric_or_unitized(region.get("width", 0.0), f"section_cuts[{i}].region.width")
        _validate_numeric_or_unitized(region.get("height", 0.0), f"section_cuts[{i}].region.height")
        if "frame" in region and region.get("frame") is not None:
            _validate_frame_reference(region.get("frame"), f"section_cuts[{i}].region.frame")

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
        position = _expect_obj(comp_obj.get("position"), f"components[{i}].position")
        _validate_numeric_or_unitized(position.get("x", 0.0), f"components[{i}].position.x")
        _validate_numeric_or_unitized(position.get("y", 0.0), f"components[{i}].position.y")
        if "frame" in position and position.get("frame") is not None:
            _validate_frame_reference(position.get("frame"), f"components[{i}].position.frame")
        size = _expect_obj(comp_obj.get("size"), f"components[{i}].size")
        _validate_dimension_value(size.get("width"), f"components[{i}].size.width", allow_auto=True)
        _validate_dimension_value(size.get("height"), f"components[{i}].size.height", allow_auto=True)
        if not isinstance(comp_obj.get("z_index", 0), int):
            raise PlanesValidationError(f"components[{i}].z_index must be int")
        anchor = comp_obj.get("anchor")
        if anchor is not None:
            anchor_obj = _expect_obj(anchor, f"components[{i}].anchor")
            if "x" in anchor_obj:
                _validate_anchor_value(anchor_obj["x"], f"components[{i}].anchor.x")
            if "y" in anchor_obj:
                _validate_anchor_value(anchor_obj["y"], f"components[{i}].anchor.y")
            frame_reference = anchor_obj.get("frame_reference")
            if frame_reference is None:
                frame_reference = anchor_obj.get("frame")
            if frame_reference is not None:
                _require_str(frame_reference, f"components[{i}].anchor.frame_reference")

        if has_v2:
            attachment_kind = comp_obj.get("attachment_kind")
            if attachment_kind is not None and attachment_kind not in {"plane", "camera_overlay"}:
                raise PlanesValidationError(f"components[{i}].attachment_kind invalid")
            attach_to = comp_obj.get("attach_to")
            attach_to_norm: str | None = None
            if attach_to is not None:
                if not isinstance(attach_to, str) or not attach_to.strip():
                    raise PlanesValidationError(f"components[{i}].attach_to must be a non-empty string")
                attach_to_norm = attach_to.strip()
                if attach_to_norm in {"camera_overlay", "camera"}:
                    if attachment_kind == "plane":
                        raise PlanesValidationError(
                            f"components[{i}] has conflicting attachment_kind `plane` with attach_to `{attach_to_norm}`"
                        )
                else:
                    if attach_to_norm not in plane_ids:
                        raise PlanesValidationError(
                            f"components[{i}].attach_to must reference an existing plane or `camera_overlay`/`camera`"
                        )
                    if attachment_kind == "camera_overlay":
                        raise PlanesValidationError(
                            f"components[{i}] has conflicting attachment_kind `camera_overlay` with plane attach_to"
                        )
            if strict and not isinstance(attachment_kind, str) and attach_to_norm is None:
                raise PlanesValidationError(
                    f"components[{i}] must define either attachment_kind or attach_to in strict v2 mode"
                )
            if isinstance(attachment_kind, str) and attachment_kind == "plane" and attach_to_norm is None:
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
            _validate_numeric_or_unitized(scroll.get("x", 0.0), f"components[{i}].props.scroll.x")
            _validate_numeric_or_unitized(scroll.get("y", 0.0), f"components[{i}].props.scroll.y")


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


def _resolve_dimension(
    raw: Any,
    viewport_w: int,
    viewport_h: int,
    *,
    parent_w: float | None = None,
    parent_h: float | None = None,
    axis: str = "x",
) -> float:
    if isinstance(raw, (int, float, str)):
        return _resolve_unitized_scalar(
            raw,
            viewport_w=viewport_w,
            viewport_h=viewport_h,
            parent_w=parent_w,
            parent_h=parent_h,
            axis=axis,
            name="dimension",
        )
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
        if axis == "y":
            reference = float(parent_h if parent_h is not None else viewport_h)
        else:
            reference = float(parent_w if parent_w is not None else viewport_w)
        return (v / 100.0) * reference
    if unit == "pt":
        return v * (96.0 / 72.0)
    if unit == "cm":
        return v * (96.0 / 2.54)
    raise PlanesValidationError(f"unsupported unit: {unit}")


def _resolve_component_dimension(
    raw: Any,
    *,
    viewport_w: int,
    viewport_h: int,
    parent_w: float,
    parent_h: float,
    axis: str,
) -> tuple[float, bool]:
    if isinstance(raw, str) and raw.strip().lower() == "auto":
        return (0.0, True)
    if isinstance(raw, (int, float, str)):
        return (
            _resolve_dimension(
                raw,
                viewport_w,
                viewport_h,
                parent_w=parent_w,
                parent_h=parent_h,
                axis=axis,
            ),
            False,
        )
    spec = _expect_obj(raw, "dimension")
    unit = _require_str(spec.get("unit"), "dimension.unit")
    if unit == "auto":
        return (0.0, True)
    return (
        _resolve_dimension(
            spec,
            viewport_w,
            viewport_h,
            parent_w=parent_w,
            parent_h=parent_h,
            axis=axis,
        ),
        False,
    )


def _resolve_plane_depth(plane: dict[str, Any], path: str, *, strict: bool) -> int:
    values: dict[str, int] = {}
    for key in ("plane_global_z", "k_hat_index", "z_index_alias"):
        if key not in plane:
            continue
        raw_value = plane.get(key)
        if not isinstance(raw_value, int):
            raise PlanesValidationError(f"{path}.{key} must be int")
        values[key] = raw_value
    if not values:
        if strict:
            raise PlanesValidationError(f"{path}.plane_global_z (or k_hat_index/z_index_alias) required in strict mode")
        return 0
    if len(set(values.values())) != 1:
        raise PlanesValidationError(f"{path} has conflicting depth aliases: {values}")
    if "k_hat_index" in values:
        return values["k_hat_index"]
    if "plane_global_z" in values:
        return values["plane_global_z"]
    return values["z_index_alias"]


def _expect_obj(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlanesValidationError(f"{name} must be an object")
    return value


def _require_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlanesValidationError(f"{name} must be a non-empty string")
    return value


_ANCHOR_UNIT_PATTERN = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*(%|px|em|vw|vh)\s*$", re.IGNORECASE)
_SCALAR_UNIT_PATTERN = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*(px|vw|vh|%|pt|cm)\s*$", re.IGNORECASE)


def _resolve_unitized_scalar(
    raw: Any,
    *,
    viewport_w: int,
    viewport_h: int,
    parent_w: float | None,
    parent_h: float | None,
    axis: str,
    name: str,
) -> float:
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        text = raw.strip().lower()
        if not text:
            raise PlanesValidationError(f"{name} must be numeric or unitized string")
        match = _SCALAR_UNIT_PATTERN.match(text)
        if match is not None:
            value = float(match.group(1))
            unit = str(match.group(2)).lower()
            if unit == "px":
                return value
            if unit == "vw":
                return (value / 100.0) * float(viewport_w)
            if unit == "vh":
                return (value / 100.0) * float(viewport_h)
            if unit == "%":
                if axis == "y":
                    reference = float(parent_h if parent_h is not None else viewport_h)
                else:
                    reference = float(parent_w if parent_w is not None else viewport_w)
                return (value / 100.0) * reference
            if unit == "pt":
                return value * (96.0 / 72.0)
            if unit == "cm":
                return value * (96.0 / 2.54)
        try:
            return float(text)
        except ValueError as exc:  # noqa: PERF203
            raise PlanesValidationError(f"{name} has unsupported unit format: `{raw}`") from exc
    raise PlanesValidationError(f"{name} must be numeric or unitized string")


def _validate_numeric_or_unitized(value: Any, name: str) -> None:
    _resolve_unitized_scalar(
        value,
        viewport_w=1,
        viewport_h=1,
        parent_w=1.0,
        parent_h=1.0,
        axis="x",
        name=name,
    )


def _validate_dimension_value(value: Any, name: str, *, allow_auto: bool) -> None:
    if isinstance(value, str) and value.strip().lower() == "auto":
        if allow_auto:
            return
        raise PlanesValidationError(f"{name} does not support `auto`")
    if isinstance(value, (int, float, str)):
        _validate_numeric_or_unitized(value, name)
        return
    spec = _expect_obj(value, name)
    unit = _require_str(spec.get("unit"), f"{name}.unit").lower()
    if unit == "auto":
        if allow_auto:
            return
        raise PlanesValidationError(f"{name} does not support unit `auto`")
    if unit not in {"px", "vw", "vh", "%", "pt", "cm"}:
        raise PlanesValidationError(f"{name}.unit unsupported: `{unit}`")
    raw_value = spec.get("value")
    if not isinstance(raw_value, (int, float)):
        raise PlanesValidationError(f"{name}.value must be numeric")


def _validate_frame_reference(value: Any, name: str) -> None:
    if isinstance(value, str):
        if value.strip():
            return
        raise PlanesValidationError(f"{name} must be non-empty when string")
    frame_obj = _expect_obj(value, name)
    origin = _parse_pair(frame_obj.get("origin"), field_name=f"{name}.origin")
    basis_x = _parse_pair(frame_obj.get("basis_x"), field_name=f"{name}.basis_x")
    basis_y = _parse_pair(frame_obj.get("basis_y"), field_name=f"{name}.basis_y")
    _validate_numeric_or_unitized(origin[0], f"{name}.origin[0]")
    _validate_numeric_or_unitized(origin[1], f"{name}.origin[1]")
    for idx, raw in enumerate(basis_x):
        if not isinstance(raw, (int, float)):
            raise PlanesValidationError(f"{name}.basis_x[{idx}] must be numeric")
    for idx, raw in enumerate(basis_y):
        if not isinstance(raw, (int, float)):
            raise PlanesValidationError(f"{name}.basis_y[{idx}] must be numeric")


def _parse_pair(value: Any, *, field_name: str) -> tuple[Any, Any]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise PlanesValidationError(f"{field_name} must be [x, y]")
    return (value[0], value[1])


def _validate_anchor_value(value: Any, name: str) -> None:
    if isinstance(value, (int, float)):
        return
    if not isinstance(value, str) or not value.strip():
        raise PlanesValidationError(f"{name} must be number or unitized string")
    raw = value.strip()
    if _ANCHOR_UNIT_PATTERN.match(raw):
        return
    try:
        float(raw)
        return
    except ValueError as exc:  # noqa: PERF203
        raise PlanesValidationError(f"{name} has unsupported unit format: `{value}`") from exc
