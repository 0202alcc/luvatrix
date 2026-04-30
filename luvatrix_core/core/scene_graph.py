from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math
import threading
import time
from typing import Literal, TypeAlias


ShaderKind = Literal["solid", "full_suite_background"]


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
    cache_key: str | None = None

    def __post_init__(self) -> None:
        if self.font_size_px <= 0:
            raise ValueError("font_size_px must be > 0")
        if self.max_width_px is not None and self.max_width_px <= 0:
            raise ValueError("max_width_px must be > 0 when provided")
        object.__setattr__(self, "color_rgba", _rgba(self.color_rgba))


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
    | CircleNode
    | TextNode
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
        object.__setattr__(self, "nodes", tuple(sorted(self.nodes, key=lambda node: getattr(node, "z_index", 0))))


@dataclass(frozen=True)
class SceneBlitEvent:
    event_id: int
    revision: int
    ts_ns: int


class SceneGraphBuffer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._event_lock = threading.Lock()
        self._event_cv = threading.Condition(self._event_lock)
        self._events: deque[SceneBlitEvent] = deque()
        self._next_event_id = 1
        self._revision = 0
        self._frame: SceneFrame | None = None

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
