from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping


AspectMode = Literal["stretch", "preserve"]


@dataclass(frozen=True)
class MatrixSpec:
    width: int
    height: int
    pixel_format: Literal["RGBA255"] = "RGBA255"

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("matrix width/height must be > 0")


@dataclass(frozen=True)
class Insets:
    left: float = 0.0
    right: float = 0.0
    top: float = 0.0
    bottom: float = 0.0

    def __post_init__(self) -> None:
        if self.left < 0 or self.right < 0 or self.top < 0 or self.bottom < 0:
            raise ValueError("insets must be >= 0")


@dataclass(frozen=True)
class CoordinateFrameSpec:
    name: str
    origin: tuple[float, float]
    basis_x: tuple[float, float]
    basis_y: tuple[float, float]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("coordinate frame name must be non-empty")
        det = self.basis_x[0] * self.basis_y[1] - self.basis_x[1] * self.basis_y[0]
        if abs(det) < 1e-9:
            raise ValueError(f"frame `{self.name}` basis vectors are singular")


@dataclass(frozen=True)
class CoordinateRef:
    x: float
    y: float
    frame: str | None = None


@dataclass(frozen=True)
class BoundingBoxSpec:
    x: float
    y: float
    width: float
    height: float
    frame: str | None = None

    def __post_init__(self) -> None:
        if self.width < 0 or self.height < 0:
            raise ValueError("bounding box width/height must be >= 0")


@dataclass(frozen=True)
class UIIRAsset:
    kind: Literal["svg", "image", "font", "data"]
    source: str
    content_hash: str | None = None
    preload: bool = False

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("asset source must be non-empty")


@dataclass(frozen=True)
class InteractionBinding:
    event: str
    handler: str
    args: dict[str, object] = field(default_factory=dict)
    debounce_ms: int | None = None
    throttle_ms: int | None = None
    stop_propagation: bool = True

    def __post_init__(self) -> None:
        if not self.event.strip():
            raise ValueError("interaction event must be non-empty")
        if not self.handler.strip():
            raise ValueError("interaction handler must be non-empty")
        if self.debounce_ms is not None and self.debounce_ms < 0:
            raise ValueError("debounce_ms must be >= 0")
        if self.throttle_ms is not None and self.throttle_ms < 0:
            raise ValueError("throttle_ms must be >= 0")


@dataclass(frozen=True)
class ComponentTransform:
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation_deg: float = 0.0
    anchor_x: float = 0.0
    anchor_y: float = 0.0


@dataclass(frozen=True)
class ComponentSemantics:
    label: str | None = None
    role: str | None = None
    tooltip: str | None = None


@dataclass(frozen=True)
class UIIRComponent:
    component_id: str
    component_type: str
    position: CoordinateRef
    width: float
    height: float
    z_index: int = 0
    frame: str | None = None
    visible: bool = True
    enabled: bool = True
    opacity: float = 1.0
    asset: UIIRAsset | None = None
    style: dict[str, object] = field(default_factory=dict)
    interactions: tuple[InteractionBinding, ...] = ()
    visual_bounds: BoundingBoxSpec | None = None
    interaction_bounds: BoundingBoxSpec | None = None
    transform: ComponentTransform = field(default_factory=ComponentTransform)
    semantics: ComponentSemantics = field(default_factory=ComponentSemantics)
    state_bindings: dict[str, str] = field(default_factory=dict)
    diagnostics_source: str | None = None
    attachment_kind: Literal["plane", "camera_overlay"] = "plane"
    plane_id: str | None = None
    plane_global_z: int | None = None
    component_local_z: int = 0
    blend_mode: Literal["absolute_rgba", "delta_rgba"] = "absolute_rgba"
    world_bounds: BoundingBoxSpec | None = None
    world_bounds_hint: BoundingBoxSpec | None = None
    culling_hint: dict[str, object] = field(default_factory=dict)
    section_cut_refs: tuple[str, ...] = ()
    stable_order_key: tuple[int, int, int, int] | None = None

    def __post_init__(self) -> None:
        if not self.component_id.strip():
            raise ValueError("component_id must be non-empty")
        if not self.component_type.strip():
            raise ValueError("component_type must be non-empty")
        if self.width < 0 or self.height < 0:
            raise ValueError("component width/height must be >= 0")
        if self.opacity < 0.0 or self.opacity > 1.0:
            raise ValueError("component opacity must be in [0, 1]")
        if self.attachment_kind not in {"plane", "camera_overlay"}:
            raise ValueError("attachment_kind must be `plane` or `camera_overlay`")
        if self.blend_mode not in {"absolute_rgba", "delta_rgba"}:
            raise ValueError("blend_mode must be `absolute_rgba` or `delta_rgba`")

    def resolved_frame(self, default_frame: str) -> str:
        return self.frame or self.position.frame or default_frame

    def resolved_visual_bounds(self, default_frame: str) -> BoundingBoxSpec:
        if self.visual_bounds is not None:
            return self.visual_bounds
        frame = self.resolved_frame(default_frame)
        return BoundingBoxSpec(
            x=self.position.x,
            y=self.position.y,
            width=self.width,
            height=self.height,
            frame=frame,
        )

    def resolved_interaction_bounds(self, default_frame: str) -> BoundingBoxSpec:
        if self.interaction_bounds is not None:
            return self.interaction_bounds
        return self.resolved_visual_bounds(default_frame)


@dataclass(frozen=True)
class UIIRPage:
    ir_version: str
    page_id: str
    matrix: MatrixSpec
    aspect_mode: AspectMode
    default_frame: str = "cartesian_center"
    app_protocol_version: str | None = None
    revision: int = 0
    route: str | None = None
    background: str = "#000000"
    safe_insets: Insets = field(default_factory=Insets)
    coordinate_frames: tuple[CoordinateFrameSpec, ...] = ()
    components: tuple[UIIRComponent, ...] = ()
    theme_ref: str | None = None
    active_route_id: str | None = None
    active_plane_ids: tuple[str, ...] = ()
    ordering_contract_version: str | None = None
    section_cuts: tuple["UIIRSectionCut", ...] = ()
    plane_manifest: tuple["UIIRPlaneRef", ...] = ()

    def __post_init__(self) -> None:
        if not self.ir_version.strip():
            raise ValueError("ir_version must be non-empty")
        if not self.page_id.strip():
            raise ValueError("page_id must be non-empty")
        if not self.default_frame.strip():
            raise ValueError("default_frame must be non-empty")
        if self.revision < 0:
            raise ValueError("revision must be >= 0")
        _validate_hex_color(self.background)
        self._validate_component_ids_unique()

    def _validate_component_ids_unique(self) -> None:
        seen: set[str] = set()
        for component in self.components:
            if component.component_id in seen:
                raise ValueError(f"duplicate component_id: {component.component_id}")
            seen.add(component.component_id)

    def ordered_components_for_draw(self) -> list[UIIRComponent]:
        if self.ir_version == "planes-v2":
            return sorted(
                self.components,
                key=lambda component: (
                    0 if component.attachment_kind == "plane" else 1,
                    component.plane_global_z if component.plane_global_z is not None else 0,
                    int(component.component_local_z),
                    self._component_mount_order(component.component_id),
                    component.component_id,
                ),
            )
        return sorted(
            self.components,
            key=lambda component: (component.z_index, self._component_mount_order(component.component_id)),
        )

    def ordered_components_for_hit_test(self) -> list[UIIRComponent]:
        draw = self.ordered_components_for_draw()
        draw.reverse()
        return draw

    def _component_mount_order(self, component_id: str) -> int:
        for i, component in enumerate(self.components):
            if component.component_id == component_id:
                return i
        return -1

    def to_dict(self) -> dict[str, object]:
        return {
            "ir_version": self.ir_version,
            "app_protocol_version": self.app_protocol_version,
            "page_id": self.page_id,
            "route": self.route,
            "revision": self.revision,
            "matrix": {
                "width": self.matrix.width,
                "height": self.matrix.height,
                "pixel_format": self.matrix.pixel_format,
            },
            "aspect_mode": self.aspect_mode,
            "default_frame": self.default_frame,
            "background": self.background,
            "safe_insets": {
                "left": self.safe_insets.left,
                "right": self.safe_insets.right,
                "top": self.safe_insets.top,
                "bottom": self.safe_insets.bottom,
            },
            "coordinate_frames": [
                {
                    "name": frame.name,
                    "origin": [frame.origin[0], frame.origin[1]],
                    "basis_x": [frame.basis_x[0], frame.basis_x[1]],
                    "basis_y": [frame.basis_y[0], frame.basis_y[1]],
                }
                for frame in self.coordinate_frames
            ],
            "components": [
                {
                    "id": component.component_id,
                    "type": component.component_type,
                    "position": {
                        "x": component.position.x,
                        "y": component.position.y,
                        "frame": component.position.frame,
                    },
                    "width": component.width,
                    "height": component.height,
                    "z_index": component.z_index,
                    "frame": component.frame,
                    "visible": component.visible,
                    "enabled": component.enabled,
                    "opacity": component.opacity,
                    "asset": (
                        {
                            "kind": component.asset.kind,
                            "source": component.asset.source,
                            "content_hash": component.asset.content_hash,
                            "preload": component.asset.preload,
                        }
                        if component.asset is not None
                        else None
                    ),
                    "style": component.style,
                    "interactions": [
                        {
                            "event": interaction.event,
                            "handler": interaction.handler,
                            "args": interaction.args,
                            "debounce_ms": interaction.debounce_ms,
                            "throttle_ms": interaction.throttle_ms,
                            "stop_propagation": interaction.stop_propagation,
                        }
                        for interaction in component.interactions
                    ],
                    "visual_bounds": _bbox_to_dict(component.visual_bounds),
                    "interaction_bounds": _bbox_to_dict(component.interaction_bounds),
                    "transform": {
                        "scale_x": component.transform.scale_x,
                        "scale_y": component.transform.scale_y,
                        "rotation_deg": component.transform.rotation_deg,
                        "anchor_x": component.transform.anchor_x,
                        "anchor_y": component.transform.anchor_y,
                    },
                    "semantics": {
                        "label": component.semantics.label,
                        "role": component.semantics.role,
                        "tooltip": component.semantics.tooltip,
                    },
                    "state_bindings": component.state_bindings,
                    "diagnostics_source": component.diagnostics_source,
                    "attachment_kind": component.attachment_kind,
                    "plane_id": component.plane_id,
                    "plane_global_z": component.plane_global_z,
                    "component_local_z": component.component_local_z,
                    "blend_mode": component.blend_mode,
                    "world_bounds": _bbox_to_dict(component.world_bounds),
                    "world_bounds_hint": _bbox_to_dict(component.world_bounds_hint),
                    "culling_hint": component.culling_hint,
                    "section_cut_refs": list(component.section_cut_refs),
                    "stable_order_key": (
                        list(component.stable_order_key) if component.stable_order_key is not None else None
                    ),
                }
                for component in self.components
            ],
            "theme_ref": self.theme_ref,
            "active_route_id": self.active_route_id,
            "active_plane_ids": list(self.active_plane_ids),
            "ordering_contract_version": self.ordering_contract_version,
            "section_cuts": [
                {
                    "id": cut.cut_id,
                    "owner_plane_id": cut.owner_plane_id,
                    "target_plane_ids": list(cut.target_plane_ids),
                    "region_bounds": _bbox_to_dict(cut.region_bounds),
                    "enabled": cut.enabled,
                }
                for cut in self.section_cuts
            ],
            "plane_manifest": [
                {
                    "plane_id": plane.plane_id,
                    "plane_global_z": plane.plane_global_z,
                    "active": plane.active,
                    "resolved_position": {
                        "x": plane.resolved_position.x,
                        "y": plane.resolved_position.y,
                        "frame": plane.resolved_position.frame,
                    },
                    "resolved_bounds": _bbox_to_dict(plane.resolved_bounds),
                    "default_frame": plane.default_frame,
                }
                for plane in self.plane_manifest
            ],
        }

    @staticmethod
    def from_dict(payload: Mapping[str, object]) -> "UIIRPage":
        matrix_raw = _expect_mapping(payload.get("matrix"), field_name="matrix")
        insets_raw = _expect_mapping(payload.get("safe_insets", {}), field_name="safe_insets")
        frame_list = payload.get("coordinate_frames", ())
        component_list = payload.get("components", ())
        section_cut_list = payload.get("section_cuts", ())
        plane_manifest_list = payload.get("plane_manifest", ())
        if not isinstance(frame_list, list):
            raise TypeError("coordinate_frames must be a list")
        if not isinstance(component_list, list):
            raise TypeError("components must be a list")
        if not isinstance(section_cut_list, list):
            raise TypeError("section_cuts must be a list")
        if not isinstance(plane_manifest_list, list):
            raise TypeError("plane_manifest must be a list")
        return UIIRPage(
            ir_version=str(payload["ir_version"]),
            app_protocol_version=(
                None if payload.get("app_protocol_version") is None else str(payload.get("app_protocol_version"))
            ),
            page_id=str(payload["page_id"]),
            route=None if payload.get("route") is None else str(payload.get("route")),
            revision=int(payload.get("revision", 0)),
            matrix=MatrixSpec(
                width=int(matrix_raw["width"]),
                height=int(matrix_raw["height"]),
                pixel_format=str(matrix_raw.get("pixel_format", "RGBA255")),
            ),
            aspect_mode=str(payload["aspect_mode"]),
            default_frame=str(payload.get("default_frame", "cartesian_center")),
            background=str(payload.get("background", "#000000")),
            safe_insets=Insets(
                left=float(insets_raw.get("left", 0.0)),
                right=float(insets_raw.get("right", 0.0)),
                top=float(insets_raw.get("top", 0.0)),
                bottom=float(insets_raw.get("bottom", 0.0)),
            ),
            coordinate_frames=tuple(_parse_coordinate_frame(item) for item in frame_list),
            components=tuple(_parse_component(item) for item in component_list),
            theme_ref=None if payload.get("theme_ref") is None else str(payload.get("theme_ref")),
            active_route_id=None if payload.get("active_route_id") is None else str(payload.get("active_route_id")),
            active_plane_ids=tuple(str(item) for item in payload.get("active_plane_ids", ()) if isinstance(item, str)),
            ordering_contract_version=(
                None
                if payload.get("ordering_contract_version") is None
                else str(payload.get("ordering_contract_version"))
            ),
            section_cuts=tuple(_parse_section_cut(item) for item in section_cut_list),
            plane_manifest=tuple(_parse_plane_ref(item) for item in plane_manifest_list),
        )


@dataclass(frozen=True)
class UIIRPlaneRef:
    plane_id: str
    plane_global_z: int
    active: bool
    resolved_position: CoordinateRef
    resolved_bounds: BoundingBoxSpec
    default_frame: str


@dataclass(frozen=True)
class UIIRSectionCut:
    cut_id: str
    owner_plane_id: str
    target_plane_ids: tuple[str, ...]
    region_bounds: BoundingBoxSpec
    enabled: bool = True


def validate_ui_ir_payload(payload: Mapping[str, object]) -> UIIRPage:
    return UIIRPage.from_dict(payload)


def default_ui_ir_page_schema() -> dict[str, object]:
    return UI_IR_PAGE_JSON_SCHEMA


def _expect_mapping(raw: object, *, field_name: str) -> Mapping[str, object]:
    if not isinstance(raw, Mapping):
        raise TypeError(f"{field_name} must be an object")
    return raw


def _parse_coordinate_frame(item: object) -> CoordinateFrameSpec:
    raw = _expect_mapping(item, field_name="coordinate_frames[]")
    origin = _parse_pair(raw.get("origin"), field_name="coordinate_frames[].origin")
    basis_x = _parse_pair(raw.get("basis_x"), field_name="coordinate_frames[].basis_x")
    basis_y = _parse_pair(raw.get("basis_y"), field_name="coordinate_frames[].basis_y")
    return CoordinateFrameSpec(
        name=str(raw["name"]),
        origin=origin,
        basis_x=basis_x,
        basis_y=basis_y,
    )


def _parse_component(item: object) -> UIIRComponent:
    raw = _expect_mapping(item, field_name="components[]")
    position_raw = _expect_mapping(raw.get("position"), field_name="components[].position")
    asset_raw = raw.get("asset")
    visual_bounds_raw = raw.get("visual_bounds")
    interaction_bounds_raw = raw.get("interaction_bounds")
    transform_raw = _expect_mapping(raw.get("transform", {}), field_name="components[].transform")
    semantics_raw = _expect_mapping(raw.get("semantics", {}), field_name="components[].semantics")
    interactions_raw = raw.get("interactions", ())
    if not isinstance(interactions_raw, list):
        raise TypeError("components[].interactions must be a list")
    state_bindings = raw.get("state_bindings", {})
    if not isinstance(state_bindings, dict):
        raise TypeError("components[].state_bindings must be an object")
    return UIIRComponent(
        component_id=str(raw["id"]),
        component_type=str(raw["type"]),
        position=CoordinateRef(
            x=float(position_raw["x"]),
            y=float(position_raw["y"]),
            frame=None if position_raw.get("frame") is None else str(position_raw.get("frame")),
        ),
        width=float(raw.get("width", 0.0)),
        height=float(raw.get("height", 0.0)),
        z_index=int(raw.get("z_index", 0)),
        frame=None if raw.get("frame") is None else str(raw.get("frame")),
        visible=bool(raw.get("visible", True)),
        enabled=bool(raw.get("enabled", True)),
        opacity=float(raw.get("opacity", 1.0)),
        asset=_parse_asset(asset_raw),
        style=dict(raw.get("style", {})) if isinstance(raw.get("style", {}), dict) else {},
        interactions=tuple(_parse_interaction(interaction) for interaction in interactions_raw),
        visual_bounds=_parse_bbox(visual_bounds_raw, field_name="components[].visual_bounds"),
        interaction_bounds=_parse_bbox(interaction_bounds_raw, field_name="components[].interaction_bounds"),
        transform=ComponentTransform(
            scale_x=float(transform_raw.get("scale_x", 1.0)),
            scale_y=float(transform_raw.get("scale_y", 1.0)),
            rotation_deg=float(transform_raw.get("rotation_deg", 0.0)),
            anchor_x=float(transform_raw.get("anchor_x", 0.0)),
            anchor_y=float(transform_raw.get("anchor_y", 0.0)),
        ),
        semantics=ComponentSemantics(
            label=None if semantics_raw.get("label") is None else str(semantics_raw.get("label")),
            role=None if semantics_raw.get("role") is None else str(semantics_raw.get("role")),
            tooltip=None if semantics_raw.get("tooltip") is None else str(semantics_raw.get("tooltip")),
        ),
        state_bindings={str(k): str(v) for k, v in state_bindings.items()},
        diagnostics_source=None if raw.get("diagnostics_source") is None else str(raw.get("diagnostics_source")),
        attachment_kind=str(raw.get("attachment_kind", "plane")),
        plane_id=None if raw.get("plane_id") is None else str(raw.get("plane_id")),
        plane_global_z=None if raw.get("plane_global_z") is None else int(raw.get("plane_global_z")),
        component_local_z=int(raw.get("component_local_z", raw.get("z_index", 0))),
        blend_mode=str(raw.get("blend_mode", "absolute_rgba")),
        world_bounds=_parse_bbox(raw.get("world_bounds"), field_name="components[].world_bounds"),
        world_bounds_hint=_parse_bbox(raw.get("world_bounds_hint"), field_name="components[].world_bounds_hint"),
        culling_hint=dict(raw.get("culling_hint", {})) if isinstance(raw.get("culling_hint", {}), dict) else {},
        section_cut_refs=tuple(str(item) for item in raw.get("section_cut_refs", ()) if isinstance(item, str)),
        stable_order_key=_parse_stable_order_key(raw.get("stable_order_key")),
    )


def _parse_stable_order_key(raw: object) -> tuple[int, int, int, int] | None:
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        raise TypeError("components[].stable_order_key must be a [a,b,c,d] tuple/list")
    return (int(raw[0]), int(raw[1]), int(raw[2]), int(raw[3]))


def _parse_plane_ref(item: object) -> UIIRPlaneRef:
    raw = _expect_mapping(item, field_name="plane_manifest[]")
    pos_raw = _expect_mapping(raw.get("resolved_position"), field_name="plane_manifest[].resolved_position")
    bounds_raw = _expect_mapping(raw.get("resolved_bounds"), field_name="plane_manifest[].resolved_bounds")
    return UIIRPlaneRef(
        plane_id=str(raw["plane_id"]),
        plane_global_z=int(raw.get("plane_global_z", 0)),
        active=bool(raw.get("active", True)),
        resolved_position=CoordinateRef(
            x=float(pos_raw.get("x", 0.0)),
            y=float(pos_raw.get("y", 0.0)),
            frame=None if pos_raw.get("frame") is None else str(pos_raw.get("frame")),
        ),
        resolved_bounds=BoundingBoxSpec(
            x=float(bounds_raw.get("x", 0.0)),
            y=float(bounds_raw.get("y", 0.0)),
            width=float(bounds_raw.get("width", 0.0)),
            height=float(bounds_raw.get("height", 0.0)),
            frame=None if bounds_raw.get("frame") is None else str(bounds_raw.get("frame")),
        ),
        default_frame=str(raw.get("default_frame", "cartesian_center")),
    )


def _parse_section_cut(item: object) -> UIIRSectionCut:
    raw = _expect_mapping(item, field_name="section_cuts[]")
    targets = raw.get("target_plane_ids", [])
    if not isinstance(targets, list):
        raise TypeError("section_cuts[].target_plane_ids must be a list")
    region = _parse_bbox(raw.get("region_bounds"), field_name="section_cuts[].region_bounds")
    if region is None:
        raise TypeError("section_cuts[].region_bounds must be present")
    return UIIRSectionCut(
        cut_id=str(raw["id"]),
        owner_plane_id=str(raw["owner_plane_id"]),
        target_plane_ids=tuple(str(t) for t in targets if isinstance(t, str)),
        region_bounds=region,
        enabled=bool(raw.get("enabled", True)),
    )


def _parse_asset(asset_raw: object) -> UIIRAsset | None:
    if asset_raw is None:
        return None
    raw = _expect_mapping(asset_raw, field_name="components[].asset")
    return UIIRAsset(
        kind=str(raw["kind"]),
        source=str(raw["source"]),
        content_hash=None if raw.get("content_hash") is None else str(raw.get("content_hash")),
        preload=bool(raw.get("preload", False)),
    )


def _parse_bbox(raw: object, *, field_name: str) -> BoundingBoxSpec | None:
    if raw is None:
        return None
    data = _expect_mapping(raw, field_name=field_name)
    return BoundingBoxSpec(
        x=float(data["x"]),
        y=float(data["y"]),
        width=float(data["width"]),
        height=float(data["height"]),
        frame=None if data.get("frame") is None else str(data.get("frame")),
    )


def _parse_interaction(raw: object) -> InteractionBinding:
    data = _expect_mapping(raw, field_name="components[].interactions[]")
    args = data.get("args", {})
    if not isinstance(args, dict):
        raise TypeError("components[].interactions[].args must be an object")
    return InteractionBinding(
        event=str(data["event"]),
        handler=str(data["handler"]),
        args=dict(args),
        debounce_ms=None if data.get("debounce_ms") is None else int(data.get("debounce_ms")),
        throttle_ms=None if data.get("throttle_ms") is None else int(data.get("throttle_ms")),
        stop_propagation=bool(data.get("stop_propagation", True)),
    )


def _parse_pair(raw: object, *, field_name: str) -> tuple[float, float]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise TypeError(f"{field_name} must be a [x, y] pair")
    return (float(raw[0]), float(raw[1]))


def _bbox_to_dict(bounds: BoundingBoxSpec | None) -> dict[str, object] | None:
    if bounds is None:
        return None
    return {
        "x": bounds.x,
        "y": bounds.y,
        "width": bounds.width,
        "height": bounds.height,
        "frame": bounds.frame,
    }


def _validate_hex_color(value: str) -> None:
    raw = value.strip()
    if not raw.startswith("#"):
        raise ValueError("background must use hex color format")
    hex_part = raw[1:]
    if len(hex_part) not in (6, 8):
        raise ValueError("background must be #RRGGBB or #RRGGBBAA")
    _ = int(hex_part, 16)


UI_IR_PAGE_JSON_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://luvatrix.dev/schemas/ui_ir.page.schema.json",
    "title": "Luvatrix UI IR Page",
    "type": "object",
    "required": [
        "ir_version",
        "page_id",
        "matrix",
        "aspect_mode",
        "default_frame",
        "components",
    ],
    "properties": {
        "ir_version": {"type": "string", "minLength": 1},
        "app_protocol_version": {"type": ["string", "null"]},
        "page_id": {"type": "string", "minLength": 1},
        "route": {"type": ["string", "null"]},
        "revision": {"type": "integer", "minimum": 0},
        "matrix": {
            "type": "object",
            "required": ["width", "height"],
            "properties": {
                "width": {"type": "integer", "minimum": 1},
                "height": {"type": "integer", "minimum": 1},
                "pixel_format": {"type": "string", "enum": ["RGBA255"]},
            },
            "additionalProperties": False,
        },
        "aspect_mode": {"type": "string", "enum": ["stretch", "preserve"]},
        "default_frame": {"type": "string", "minLength": 1},
        "background": {
            "type": "string",
            "pattern": "^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$",
        },
        "safe_insets": {
            "type": "object",
            "properties": {
                "left": {"type": "number", "minimum": 0},
                "right": {"type": "number", "minimum": 0},
                "top": {"type": "number", "minimum": 0},
                "bottom": {"type": "number", "minimum": 0},
            },
            "additionalProperties": False,
        },
        "coordinate_frames": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "origin", "basis_x", "basis_y"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "origin": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "basis_x": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "basis_y": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                },
                "additionalProperties": False,
            },
        },
        "components": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "type", "position", "width", "height"],
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "type": {"type": "string", "minLength": 1},
                    "position": {
                        "type": "object",
                        "required": ["x", "y"],
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                            "frame": {"type": ["string", "null"]},
                        },
                        "additionalProperties": False,
                    },
                    "width": {"type": "number", "minimum": 0},
                    "height": {"type": "number", "minimum": 0},
                    "z_index": {"type": "integer"},
                    "frame": {"type": ["string", "null"]},
                    "visible": {"type": "boolean"},
                    "enabled": {"type": "boolean"},
                    "opacity": {"type": "number", "minimum": 0, "maximum": 1},
                    "asset": {
                        "type": ["object", "null"],
                        "required": ["kind", "source"],
                        "properties": {
                            "kind": {"type": "string", "enum": ["svg", "image", "font", "data"]},
                            "source": {"type": "string", "minLength": 1},
                            "content_hash": {"type": ["string", "null"]},
                            "preload": {"type": "boolean"},
                        },
                        "additionalProperties": False,
                    },
                    "style": {"type": "object"},
                    "interactions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["event", "handler"],
                            "properties": {
                                "event": {"type": "string", "minLength": 1},
                                "handler": {"type": "string", "minLength": 1},
                                "args": {"type": "object"},
                                "debounce_ms": {"type": ["integer", "null"], "minimum": 0},
                                "throttle_ms": {"type": ["integer", "null"], "minimum": 0},
                                "stop_propagation": {"type": "boolean"},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "visual_bounds": {
                        "$ref": "#/$defs/bounds",
                    },
                    "interaction_bounds": {
                        "$ref": "#/$defs/bounds",
                    },
                    "transform": {
                        "type": "object",
                        "properties": {
                            "scale_x": {"type": "number"},
                            "scale_y": {"type": "number"},
                            "rotation_deg": {"type": "number"},
                            "anchor_x": {"type": "number"},
                            "anchor_y": {"type": "number"},
                        },
                        "additionalProperties": False,
                    },
                    "semantics": {
                        "type": "object",
                        "properties": {
                            "label": {"type": ["string", "null"]},
                            "role": {"type": ["string", "null"]},
                            "tooltip": {"type": ["string", "null"]},
                        },
                        "additionalProperties": False,
                    },
                    "state_bindings": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                    "diagnostics_source": {"type": ["string", "null"]},
                },
                "additionalProperties": False,
            },
        },
        "theme_ref": {"type": ["string", "null"]},
    },
    "$defs": {
        "bounds": {
            "type": ["object", "null"],
            "required": ["x", "y", "width", "height"],
            "properties": {
                "x": {"type": "number"},
                "y": {"type": "number"},
                "width": {"type": "number", "minimum": 0},
                "height": {"type": "number", "minimum": 0},
                "frame": {"type": ["string", "null"]},
            },
            "additionalProperties": False,
        }
    },
    "additionalProperties": False,
}
