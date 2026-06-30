from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math
import threading
import time
from typing import Literal, TypeAlias


ShaderKind = Literal["solid", "full_suite_background"]


def _vec3(value: tuple[float, float, float], label: str) -> tuple[float, float, float]:
    if len(value) != 3:
        raise ValueError(f"{label} must have exactly 3 values")
    return (_finite(value[0], f"{label}[0]"), _finite(value[1], f"{label}[1]"), _finite(value[2], f"{label}[2]"))


def _rgba(value: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    if len(value) != 4:
        raise ValueError("RGBA color must have exactly 4 channels")
    out = tuple(max(0, min(255, int(ch))) for ch in value)
    return (out[0], out[1], out[2], out[3])


def _finite(value: float, label: str) -> float:
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{label} must be finite")
    return out


@dataclass(frozen=True)
class SceneTelemetry:
    app_loop_ms: float = 0.0
    scene_encode_ms: float = 0.0
    gpu_present_ms: float = 0.0
    cpu_upload_bytes: int = 0
    dropped_frames: int = 0
    coalesced_frames: int = 0
    adaptive_quality_tier: int = 0


@dataclass(frozen=True)
class ClearNode:
    color_rgba: tuple[int, int, int, int] = (0, 0, 0, 255)

    def __post_init__(self) -> None:
        object.__setattr__(self, "color_rgba", _rgba(self.color_rgba))


@dataclass(frozen=True)
class ShaderRectNode:
    x: float
    y: float
    width: float
    height: float
    shader: ShaderKind = "solid"
    color_rgba: tuple[int, int, int, int] = (0, 0, 0, 255)
    uniforms: tuple[float, ...] = ()
    z_index: int = 0

    def __post_init__(self) -> None:
        _validate_rect(self.x, self.y, self.width, self.height)
        object.__setattr__(self, "color_rgba", _rgba(self.color_rgba))
        object.__setattr__(self, "uniforms", tuple(_finite(v, "uniform") for v in self.uniforms))


@dataclass(frozen=True)
class RectNode:
    x: float
    y: float
    width: float
    height: float
    color_rgba: tuple[int, int, int, int]
    z_index: int = 0

    def __post_init__(self) -> None:
        _validate_rect(self.x, self.y, self.width, self.height)
        object.__setattr__(self, "color_rgba", _rgba(self.color_rgba))


@dataclass(frozen=True)
class RoundedRectNode:
    x: float
    y: float
    width: float
    height: float
    radius: float
    color_rgba: tuple[int, int, int, int]
    z_index: int = 0

    def __post_init__(self) -> None:
        _validate_rect(self.x, self.y, self.width, self.height)
        radius = _finite(self.radius, "radius")
        if radius < 0:
            raise ValueError("radius must be >= 0")
        object.__setattr__(self, "radius", radius)
        object.__setattr__(self, "color_rgba", _rgba(self.color_rgba))


@dataclass(frozen=True)
class CircleNode:
    cx: float
    cy: float
    radius: float
    fill_rgba: tuple[int, int, int, int]
    stroke_rgba: tuple[int, int, int, int] = (0, 0, 0, 0)
    stroke_width: float = 0.0
    z_index: int = 0

    def __post_init__(self) -> None:
        _finite(self.cx, "cx")
        _finite(self.cy, "cy")
        radius = _finite(self.radius, "radius")
        if radius < 0:
            raise ValueError("radius must be >= 0")
        stroke_width = _finite(self.stroke_width, "stroke_width")
        if stroke_width < 0:
            raise ValueError("stroke_width must be >= 0")
        object.__setattr__(self, "fill_rgba", _rgba(self.fill_rgba))
        object.__setattr__(self, "stroke_rgba", _rgba(self.stroke_rgba))


@dataclass(frozen=True)
class TextNode:
    text: str
    x: float
    y: float
    font_family: str = "Comic Mono"
    font_size_px: float = 14.0
    color_rgba: tuple[int, int, int, int] = (255, 255, 255, 255)
    z_index: int = 0
    max_width_px: float | None = None
    rotation_deg: float = 0.0
    cache_key: str | None = None

    def __post_init__(self) -> None:
        if self.font_size_px <= 0:
            raise ValueError("font_size_px must be > 0")
        if self.max_width_px is not None and self.max_width_px <= 0:
            raise ValueError("max_width_px must be > 0 when provided")
        _finite(self.rotation_deg, "rotation_deg")
        object.__setattr__(self, "color_rgba", _rgba(self.color_rgba))


@dataclass(frozen=True)
class Camera3DNode:
    position: tuple[float, float, float] = (0.0, 0.0, 5.0)
    target: tuple[float, float, float] = (0.0, 0.0, 0.0)
    up: tuple[float, float, float] = (0.0, 1.0, 0.0)
    fov_deg: float = 60.0
    near: float = 0.1
    far: float = 100.0
    z_index: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "position", _vec3(self.position, "position"))
        object.__setattr__(self, "target", _vec3(self.target, "target"))
        object.__setattr__(self, "up", _vec3(self.up, "up"))
        fov = _finite(self.fov_deg, "fov_deg")
        near = _finite(self.near, "near")
        far = _finite(self.far, "far")
        if fov <= 0.0 or fov >= 180.0:
            raise ValueError("fov_deg must be in (0, 180)")
        if near <= 0.0:
            raise ValueError("near must be > 0")
        if far <= near:
            raise ValueError("far must be > near")
        if self.position == self.target:
            raise ValueError("position and target must be different")
        if self.up == (0.0, 0.0, 0.0):
            raise ValueError("up must be non-zero")


@dataclass(frozen=True)
class Cube3DNode:
    center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    size: float = 1.0
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    color_rgba: tuple[int, int, int, int] = (80, 180, 255, 255)
    edge_rgba: tuple[int, int, int, int] = (255, 255, 255, 255)
    z_index: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "center", _vec3(self.center, "center"))
        object.__setattr__(self, "rotation", _vec3(self.rotation, "rotation"))
        size = _finite(self.size, "size")
        if size <= 0.0:
            raise ValueError("size must be > 0")
        object.__setattr__(self, "color_rgba", _rgba(self.color_rgba))
        object.__setattr__(self, "edge_rgba", _rgba(self.edge_rgba))


@dataclass(frozen=True)
class Cuboid3DNode:
    center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    size: tuple[float, float, float] = (1.0, 1.0, 1.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    color_rgba: tuple[int, int, int, int] = (80, 180, 255, 255)
    edge_rgba: tuple[int, int, int, int] = (255, 255, 255, 255)
    z_index: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "center", _vec3(self.center, "center"))
        object.__setattr__(self, "size", _vec3(self.size, "size"))
        object.__setattr__(self, "rotation", _vec3(self.rotation, "rotation"))
        if any(axis <= 0.0 for axis in self.size):
            raise ValueError("size axes must be > 0")
        object.__setattr__(self, "color_rgba", _rgba(self.color_rgba))
        object.__setattr__(self, "edge_rgba", _rgba(self.edge_rgba))


@dataclass(frozen=True)
class RoundedCuboid3DNode:
    center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    size: tuple[float, float, float] = (1.0, 1.0, 1.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    radius: float = 0.25
    color_rgba: tuple[int, int, int, int] = (80, 180, 255, 255)
    edge_rgba: tuple[int, int, int, int] = (255, 255, 255, 255)
    z_index: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "center", _vec3(self.center, "center"))
        object.__setattr__(self, "size", _vec3(self.size, "size"))
        object.__setattr__(self, "rotation", _vec3(self.rotation, "rotation"))
        radius = _finite(self.radius, "radius")
        if any(axis <= 0.0 for axis in self.size):
            raise ValueError("size axes must be > 0")
        if radius <= 0.0:
            raise ValueError("radius must be > 0")
        object.__setattr__(self, "radius", radius)
        object.__setattr__(self, "color_rgba", _rgba(self.color_rgba))
        object.__setattr__(self, "edge_rgba", _rgba(self.edge_rgba))


@dataclass(frozen=True)
class Sphere3DNode:
    center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    radius: float = 1.0
    color_rgba: tuple[int, int, int, int] = (246, 208, 146, 255)
    edge_rgba: tuple[int, int, int, int] = (0, 0, 0, 0)
    z_index: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "center", _vec3(self.center, "center"))
        radius = _finite(self.radius, "radius")
        if radius <= 0.0:
            raise ValueError("radius must be > 0")
        object.__setattr__(self, "color_rgba", _rgba(self.color_rgba))
        object.__setattr__(self, "edge_rgba", _rgba(self.edge_rgba))


@dataclass(frozen=True)
class Model3DNode:
    asset: str
    center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    color_rgba: tuple[int, int, int, int] = (198, 145, 255, 255)
    edge_rgba: tuple[int, int, int, int] = (0, 0, 0, 0)
    z_index: int = 0

    def __post_init__(self) -> None:
        if not self.asset:
            raise ValueError("asset must be non-empty")
        object.__setattr__(self, "center", _vec3(self.center, "center"))
        object.__setattr__(self, "scale", _vec3(self.scale, "scale"))
        object.__setattr__(self, "rotation", _vec3(self.rotation, "rotation"))
        if any(axis <= 0.0 for axis in self.scale):
            raise ValueError("scale axes must be > 0")
        object.__setattr__(self, "color_rgba", _rgba(self.color_rgba))
        object.__setattr__(self, "edge_rgba", _rgba(self.edge_rgba))


@dataclass(frozen=True)
class Image3DNode:
    asset: str
    center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    size: tuple[float, float] = (1.0, 1.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    opacity: float = 1.0
    z_index: int = 0

    def __post_init__(self) -> None:
        if not self.asset:
            raise ValueError("asset must be non-empty")
        if len(self.size) != 2:
            raise ValueError("size must have exactly 2 values")
        object.__setattr__(self, "center", _vec3(self.center, "center"))
        size = (_finite(self.size[0], "size[0]"), _finite(self.size[1], "size[1]"))
        if any(axis <= 0.0 for axis in size):
            raise ValueError("size axes must be > 0")
        opacity = _finite(self.opacity, "opacity")
        if opacity < 0.0 or opacity > 1.0:
            raise ValueError("opacity must be in [0, 1]")
        object.__setattr__(self, "size", size)
        object.__setattr__(self, "rotation", _vec3(self.rotation, "rotation"))
        object.__setattr__(self, "opacity", opacity)


@dataclass(frozen=True)
class DotGrid3DNode:
    center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    extent: float = 8.0
    spacing: float = 0.5
    point_size: float = 2.0
    color_rgba: tuple[int, int, int, int] = (120, 170, 220, 120)
    z_index: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "center", _vec3(self.center, "center"))
        extent = _finite(self.extent, "extent")
        spacing = _finite(self.spacing, "spacing")
        point_size = _finite(self.point_size, "point_size")
        if extent <= 0.0:
            raise ValueError("extent must be > 0")
        if spacing <= 0.0:
            raise ValueError("spacing must be > 0")
        if point_size <= 0.0:
            raise ValueError("point_size must be > 0")
        object.__setattr__(self, "color_rgba", _rgba(self.color_rgba))


@dataclass(frozen=True)
class DotPlane3DNode:
    center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    width: float = 8.0
    depth: float = 8.0
    spacing: float = 0.5
    point_size: float = 2.0
    color_rgba: tuple[int, int, int, int] = (140, 190, 225, 170)
    z_index: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "center", _vec3(self.center, "center"))
        width = _finite(self.width, "width")
        depth = _finite(self.depth, "depth")
        spacing = _finite(self.spacing, "spacing")
        point_size = _finite(self.point_size, "point_size")
        if width <= 0.0:
            raise ValueError("width must be > 0")
        if depth <= 0.0:
            raise ValueError("depth must be > 0")
        if spacing <= 0.0:
            raise ValueError("spacing must be > 0")
        if point_size <= 0.0:
            raise ValueError("point_size must be > 0")
        object.__setattr__(self, "color_rgba", _rgba(self.color_rgba))


@dataclass(frozen=True)
class InfiniteGround3DNode:
    y: float = 0.0
    z_max: float = 0.0
    render_distance: float = 120.0
    color_rgba: tuple[int, int, int, int] = (26, 46, 34, 255)
    z_index: int = -20

    def __post_init__(self) -> None:
        _finite(self.y, "y")
        _finite(self.z_max, "z_max")
        render_distance = _finite(self.render_distance, "render_distance")
        if render_distance <= 0.0:
            raise ValueError("render_distance must be > 0")
        object.__setattr__(self, "color_rgba", _rgba(self.color_rgba))


@dataclass(frozen=True)
class InfiniteDotPlane3DNode:
    y: float = 0.0
    z_max: float = 0.0
    spacing: float = 0.5
    point_size: float = 2.0
    render_distance: float = 80.0
    color_rgba: tuple[int, int, int, int] = (140, 190, 225, 170)
    z_index: int = 0

    def __post_init__(self) -> None:
        _finite(self.y, "y")
        _finite(self.z_max, "z_max")
        spacing = _finite(self.spacing, "spacing")
        point_size = _finite(self.point_size, "point_size")
        render_distance = _finite(self.render_distance, "render_distance")
        if spacing <= 0.0:
            raise ValueError("spacing must be > 0")
        if point_size <= 0.0:
            raise ValueError("point_size must be > 0")
        if render_distance <= 0.0:
            raise ValueError("render_distance must be > 0")
        object.__setattr__(self, "color_rgba", _rgba(self.color_rgba))


@dataclass(frozen=True)
class InfiniteGrid3DNode:
    y: float = 0.0
    minor_spacing: float = 1.0
    major_spacing: float = 5.0
    render_distance: float = 180.0
    minor_rgba: tuple[int, int, int, int] = (204, 212, 218, 95)
    major_rgba: tuple[int, int, int, int] = (58, 118, 190, 145)
    minor_width: float = 1.0
    major_width: float = 1.35
    z_index: int = -10

    def __post_init__(self) -> None:
        _finite(self.y, "y")
        minor_spacing = _finite(self.minor_spacing, "minor_spacing")
        major_spacing = _finite(self.major_spacing, "major_spacing")
        render_distance = _finite(self.render_distance, "render_distance")
        minor_width = _finite(self.minor_width, "minor_width")
        major_width = _finite(self.major_width, "major_width")
        if minor_spacing <= 0.0:
            raise ValueError("minor_spacing must be > 0")
        if major_spacing <= 0.0:
            raise ValueError("major_spacing must be > 0")
        if render_distance <= 0.0:
            raise ValueError("render_distance must be > 0")
        if minor_width <= 0.0:
            raise ValueError("minor_width must be > 0")
        if major_width <= 0.0:
            raise ValueError("major_width must be > 0")
        object.__setattr__(self, "minor_rgba", _rgba(self.minor_rgba))
        object.__setattr__(self, "major_rgba", _rgba(self.major_rgba))


@dataclass(frozen=True)
class Line3DNode:
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    color_rgba: tuple[int, int, int, int] = (255, 255, 255, 255)
    width: float = 1.0
    z_index: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _vec3(self.start, "start"))
        object.__setattr__(self, "end", _vec3(self.end, "end"))
        width = _finite(self.width, "width")
        if width <= 0.0:
            raise ValueError("width must be > 0")
        if self.start == self.end:
            raise ValueError("start and end must be different")
        object.__setattr__(self, "color_rgba", _rgba(self.color_rgba))


@dataclass(frozen=True)
class GroundPlane3DNode:
    center: tuple[float, float, float] = (0.0, 0.0, -20.0)
    width: float = 40.0
    depth: float = 40.0
    color_rgba: tuple[int, int, int, int] = (26, 46, 34, 255)
    z_index: int = -20

    def __post_init__(self) -> None:
        object.__setattr__(self, "center", _vec3(self.center, "center"))
        width = _finite(self.width, "width")
        depth = _finite(self.depth, "depth")
        if width <= 0.0:
            raise ValueError("width must be > 0")
        if depth <= 0.0:
            raise ValueError("depth must be > 0")
        object.__setattr__(self, "color_rgba", _rgba(self.color_rgba))


@dataclass(frozen=True)
class Horizon3DNode:
    sky_rgba: tuple[int, int, int, int] = (228, 238, 246, 255)
    ground_rgba: tuple[int, int, int, int] = (236, 232, 220, 255)
    horizon_rgba: tuple[int, int, int, int] = (150, 160, 168, 255)
    sky_horizon_rgba: tuple[int, int, int, int] | None = None
    horizon_width: float = 0.012
    z_index: int = -100

    def __post_init__(self) -> None:
        width = _finite(self.horizon_width, "horizon_width")
        if width <= 0.0:
            raise ValueError("horizon_width must be > 0")
        object.__setattr__(self, "sky_rgba", _rgba(self.sky_rgba))
        object.__setattr__(self, "ground_rgba", _rgba(self.ground_rgba))
        object.__setattr__(self, "horizon_rgba", _rgba(self.horizon_rgba))
        if self.sky_horizon_rgba is not None:
            object.__setattr__(self, "sky_horizon_rgba", _rgba(self.sky_horizon_rgba))


@dataclass(frozen=True)
class Text3DNode:
    text: str
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    height: float = 0.4
    depth: float = 0.12
    color_rgba: tuple[int, int, int, int] = (235, 246, 255, 255)
    side_rgba: tuple[int, int, int, int] = (48, 76, 98, 255)
    font_family: str = "Inter"
    z_index: int = 0

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("text must be non-empty")
        object.__setattr__(self, "position", _vec3(self.position, "position"))
        height = _finite(self.height, "height")
        depth = _finite(self.depth, "depth")
        if height <= 0.0:
            raise ValueError("height must be > 0")
        if depth < 0.0:
            raise ValueError("depth must be >= 0")
        object.__setattr__(self, "color_rgba", _rgba(self.color_rgba))
        object.__setattr__(self, "side_rgba", _rgba(self.side_rgba))


@dataclass(frozen=True)
class ImageNode:
    image_id: str
    x: float
    y: float
    width: float
    height: float
    rgba: object | None = None
    z_index: int = 0

    def __post_init__(self) -> None:
        if not self.image_id:
            raise ValueError("image_id must be non-empty")
        _validate_rect(self.x, self.y, self.width, self.height)


@dataclass(frozen=True)
class SvgNode:
    svg_markup: str
    x: float
    y: float
    width: float
    height: float
    opacity: float = 1.0
    z_index: int = 0

    def __post_init__(self) -> None:
        if not self.svg_markup:
            raise ValueError("svg_markup must be non-empty")
        if self.opacity < 0.0 or self.opacity > 1.0:
            raise ValueError("opacity must be in [0, 1]")
        _validate_rect(self.x, self.y, self.width, self.height)


@dataclass(frozen=True)
class CpuLayerNode:
    x: float
    y: float
    width: float
    height: float
    rgba: object
    z_index: int = 0

    def __post_init__(self) -> None:
        _validate_rect(self.x, self.y, self.width, self.height)


SceneNode: TypeAlias = (
    ClearNode
    | ShaderRectNode
    | RectNode
    | RoundedRectNode
    | CircleNode
    | TextNode
    | Camera3DNode
    | Cube3DNode
    | Cuboid3DNode
    | RoundedCuboid3DNode
    | Sphere3DNode
    | Model3DNode
    | Image3DNode
    | DotGrid3DNode
    | DotPlane3DNode
    | InfiniteGround3DNode
    | InfiniteDotPlane3DNode
    | InfiniteGrid3DNode
    | Line3DNode
    | GroundPlane3DNode
    | Horizon3DNode
    | Text3DNode
    | ImageNode
    | SvgNode
    | CpuLayerNode
)


@dataclass(frozen=True)
class SceneFrame:
    revision: int
    logical_width: int
    logical_height: int
    display_width: int
    display_height: int
    ts_ns: int
    nodes: tuple[SceneNode, ...]
    telemetry: SceneTelemetry = field(default_factory=SceneTelemetry)
    adaptive_quality_tier: int = 0
    animation_t: float = 0.0
    presentation_mode: str | None = None   # "crop_fit" | "preserve_aspect" | "stretch" | None
    content_offset_x: float = 0.0
    content_offset_y: float = 0.0
    retained: bool = False

    def __post_init__(self) -> None:
        for label, value in (
            ("revision", self.revision),
            ("logical_width", self.logical_width),
            ("logical_height", self.logical_height),
            ("display_width", self.display_width),
            ("display_height", self.display_height),
            ("ts_ns", self.ts_ns),
        ):
            if int(value) < (0 if label in ("revision", "ts_ns") else 1):
                raise ValueError(f"{label} is out of range: {value}")
        nodes = tuple(self.nodes)
        if any(
            getattr(nodes[index - 1], "z_index", 0) > getattr(nodes[index], "z_index", 0)
            for index in range(1, len(nodes))
        ):
            nodes = tuple(sorted(nodes, key=lambda node: getattr(node, "z_index", 0)))
        object.__setattr__(self, "nodes", nodes)


@dataclass(frozen=True)
class SceneBlitEvent:
    event_id: int
    revision: int
    ts_ns: int


def _scene_render_signature(frame: SceneFrame) -> tuple[object, ...]:
    return (
        int(frame.logical_width),
        int(frame.logical_height),
        int(frame.display_width),
        int(frame.display_height),
        frame.nodes,
        int(frame.adaptive_quality_tier),
        frame.presentation_mode,
        round(float(frame.content_offset_x), 4),
        round(float(frame.content_offset_y), 4),
        bool(frame.retained),
    )


def _scene_render_equal(previous: SceneFrame, incoming: SceneFrame) -> bool:
    if _scene_render_signature(previous)[:4] != _scene_render_signature(incoming)[:4]:
        return False
    if (
        int(previous.adaptive_quality_tier) != int(incoming.adaptive_quality_tier)
        or previous.presentation_mode != incoming.presentation_mode
        or abs(float(previous.content_offset_x) - float(incoming.content_offset_x)) > 1e-4
        or abs(float(previous.content_offset_y) - float(incoming.content_offset_y)) > 1e-4
        or bool(previous.retained) != bool(incoming.retained)
    ):
        return False
    try:
        result = previous.nodes == incoming.nodes
        return result if isinstance(result, bool) else bool(result)
    except (TypeError, ValueError, RuntimeError):
        return False


class SceneGraphBuffer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._event_lock = threading.Lock()
        self._event_cv = threading.Condition(self._event_lock)
        self._events: deque[SceneBlitEvent] = deque()
        self._next_event_id = 1
        self._revision = 0
        self._frame: SceneFrame | None = None
        self._deduplicated_submissions = 0

    @property
    def revision(self) -> int:
        return self._revision

    def submit(self, frame: SceneFrame) -> SceneBlitEvent:
        with self._lock:
            self._revision += 1
            frame = SceneFrame(
                revision=self._revision,
                logical_width=frame.logical_width,
                logical_height=frame.logical_height,
                display_width=frame.display_width,
                display_height=frame.display_height,
                ts_ns=frame.ts_ns,
                nodes=frame.nodes,
                telemetry=frame.telemetry,
                adaptive_quality_tier=frame.adaptive_quality_tier,
                animation_t=frame.animation_t,
                presentation_mode=frame.presentation_mode,
                content_offset_x=frame.content_offset_x,
                content_offset_y=frame.content_offset_y,
                retained=frame.retained,
            )
            self._frame = frame
            event = SceneBlitEvent(
                event_id=self._next_event_id,
                revision=self._revision,
                ts_ns=time.time_ns(),
            )
            self._next_event_id += 1
        with self._event_cv:
            self._events.append(event)
            self._event_cv.notify_all()
        return event

    def submit_if_changed(self, frame: SceneFrame) -> SceneBlitEvent:
        """Submit a frame only when its renderable scene differs from the latest revision."""
        with self._lock:
            previous = self._frame
            if previous is not None and _scene_render_equal(previous, frame):
                self._deduplicated_submissions += 1
                return SceneBlitEvent(
                    event_id=0,
                    revision=self._revision,
                    ts_ns=time.time_ns(),
                )
        return self.submit(frame)

    def submit_content_offset(self, x: float, y: float) -> SceneBlitEvent | None:
        """Publish a transform-only revision that reuses the latest scene nodes."""
        with self._lock:
            previous = self._frame
            if previous is None:
                return None
            transformed = SceneFrame(
                revision=0,
                logical_width=previous.logical_width,
                logical_height=previous.logical_height,
                display_width=previous.display_width,
                display_height=previous.display_height,
                ts_ns=time.time_ns(),
                nodes=previous.nodes,
                telemetry=previous.telemetry,
                adaptive_quality_tier=previous.adaptive_quality_tier,
                animation_t=previous.animation_t,
                presentation_mode=previous.presentation_mode,
                content_offset_x=float(x),
                content_offset_y=float(y),
                retained=previous.retained,
            )
        return self.submit_if_changed(transformed)

    @property
    def deduplicated_submissions(self) -> int:
        with self._lock:
            return int(self._deduplicated_submissions)

    def latest_frame(self, revision: int | None = None) -> SceneFrame | None:
        with self._lock:
            if self._frame is None:
                return None
            if revision is not None and int(revision) != int(self._frame.revision):
                return None
            return self._frame

    def pop_scene_blit(self, timeout: float | None = None) -> SceneBlitEvent | None:
        with self._event_cv:
            if not self._events:
                if timeout is None:
                    return None
                self._event_cv.wait(timeout=timeout)
            if not self._events:
                return None
            return self._events.popleft()


def _validate_rect(x: float, y: float, width: float, height: float) -> None:
    _finite(x, "x")
    _finite(y, "y")
    w = _finite(width, "width")
    h = _finite(height, "height")
    if w <= 0 or h <= 0:
        raise ValueError("width and height must be > 0")
