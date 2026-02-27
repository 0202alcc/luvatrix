from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping


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

    def __post_init__(self) -> None:
        if not self.component_id.strip():
            raise ValueError("component_id must be non-empty")
        if not self.component_type.strip():
            raise ValueError("component_type must be non-empty")
        if self.width < 0 or self.height < 0:
            raise ValueError("component width/height must be >= 0")
        if self.opacity < 0.0 or self.opacity > 1.0:
            raise ValueError("component opacity must be in [0, 1]")

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
    default_frame: str = "screen_tl"
    app_protocol_version: str | None = None
    revision: int = 0
    route: str | None = None
    background: str = "#000000"
    safe_insets: Insets = field(default_factory=Insets)
    coordinate_frames: tuple[CoordinateFrameSpec, ...] = ()
    components: tuple[UIIRComponent, ...] = ()
    theme_ref: str | None = None

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
                }
                for component in self.components
            ],
            "theme_ref": self.theme_ref,
        }

    @staticmethod
    def from_dict(payload: Mapping[str, object]) -> "UIIRPage":
        matrix_raw = _expect_mapping(payload.get("matrix"), field_name="matrix")
        insets_raw = _expect_mapping(payload.get("safe_insets", {}), field_name="safe_insets")
        frame_list = payload.get("coordinate_frames", ())
        component_list = payload.get("components", ())
        if not isinstance(frame_list, list):
            raise TypeError("coordinate_frames must be a list")
        if not isinstance(component_list, list):
            raise TypeError("components must be a list")
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
            default_frame=str(payload.get("default_frame", "screen_tl")),
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
        )


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
