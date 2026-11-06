from __future__ import annotations

import hashlib
import math
import os

from luvatrix_core import accel
from luvatrix_core.core.scene_graph import (
    Camera3DNode,
    CircleNode,
    ClearNode,
    CpuLayerNode,
    Cube3DNode,
    DotGrid3DNode,
    DotPlane3DNode,
    GroundPlane3DNode,
    Horizon3DNode,
    Line3DNode,
    ImageNode,
    RectNode,
    RoundedRectNode,
    SceneFrame,
    ShaderRectNode,
    SvgNode,
    Text3DNode,
    TextNode,
)


_DEFAULT_CAMERA_3D = Camera3DNode()
_CUBE_VERTICES = (
    (-0.5, -0.5, -0.5),
    (0.5, -0.5, -0.5),
    (0.5, 0.5, -0.5),
    (-0.5, 0.5, -0.5),
    (-0.5, -0.5, 0.5),
    (0.5, -0.5, 0.5),
    (0.5, 0.5, 0.5),
    (-0.5, 0.5, 0.5),
)
_CUBE_EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))


def _numpy():
    np = getattr(accel, "_np", None)
    if np is not None:
        return np
    try:
        import numpy as np  # type: ignore
    except Exception:
        return None
    return np


try:
    # From-import of a missing extension submodule raises plain ImportError,
    # not ModuleNotFoundError; catch the broad form like window_matrix does.
    from luvatrix_core import _matrix_rs as _rs_raster  # type: ignore[import-not-found]
except ImportError:
    _rs_raster = None  # type: ignore[assignment]

_RS_DISABLE_ENV = "LUVATRIX_DISABLE_MATRIX_RS"
_LAST_RASTER_BACKEND = "python"


def _last_raster_backend() -> str:
    """Backend used by the most recent ``rasterize_scene_frame`` call."""
    return _LAST_RASTER_BACKEND


class _SceneRsFallback(Exception):
    """Internal control flow: this frame needs the Python rasterizer."""


def rasterize_scene_frame(frame: SceneFrame, out=None):
    global _LAST_RASTER_BACKEND
    if _rs_raster is not None and os.environ.get(_RS_DISABLE_ENV, "0") != "1" and _numpy() is not None:
        try:
            result = _rasterize_scene_frame_rs(frame, out=out)
        except _SceneRsFallback:
            pass
        else:
            _LAST_RASTER_BACKEND = "rust"
            return result
    _LAST_RASTER_BACKEND = "python"
    return _rasterize_scene_frame_python(frame, out=out)


def _rasterize_scene_frame_rs(frame: SceneFrame, out=None):
    """Rust fast path: encode 2D nodes as raster ops, one native pass.

    Raises ``_SceneRsFallback`` when any node needs the Python rasterizer; the
    caller's ``out`` buffer is never mutated before that decision.
    """
    np = _numpy()
    target_shape = (int(frame.display_height), int(frame.display_width), 4)
    if out is not None and tuple(out.shape) != target_shape:
        out = None
    if out is None:
        buffer = np.zeros(target_shape, dtype=np.uint8)
        view = buffer
    else:
        buffer = out
        view = _rs_writable_frame_view(out)
        if view is None:
            raise _SceneRsFallback("out buffer is not a contiguous writable uint8 array")
    sx = float(frame.display_width) / max(1.0, float(frame.logical_width))
    sy = float(frame.display_height) / max(1.0, float(frame.logical_height))
    offsets = _Offsets(float(frame.content_offset_x), float(frame.content_offset_y), sx, sy)
    encoded = []
    camera3d = _DEFAULT_CAMERA_3D
    for node in frame.nodes:
        if isinstance(node, Camera3DNode):
            camera3d = node
            continue
        ops = _encode_node_for_rs(node, sx, sy, frame, camera3d, offsets)
        if ops is None:
            raise _SceneRsFallback(f"node not lowered by the Rust rasterizer: {type(node).__name__}")
        encoded.extend(ops)
    _rs_raster.rasterize(view, int(frame.display_width), int(frame.display_height), encoded)
    return buffer


def _rs_writable_frame_view(out):
    """Contiguous writable uint8 view of a frame buffer, or ``None``."""
    np = _numpy()
    if np is not None and isinstance(out, np.ndarray):
        if out.dtype == np.uint8 and out.flags.c_contiguous and out.flags.writeable:
            return out
        return None
    torch = accel._torch
    if torch is not None and torch.is_tensor(out):
        if out.dtype == torch.uint8 and out.is_cpu and out.is_contiguous():
            return out.numpy()
        return None
    if isinstance(out, accel._PureArray):
        return out._data
    return None


def _rgba4(color: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    return (int(color[0]), int(color[1]), int(color[2]), int(color[3]))


def _encode_node_for_rs(node: SceneNode, sx: float, sy: float, frame: SceneFrame, camera3d: Camera3DNode, offsets: "_Offsets") -> list | None:
    """Encode one node as ``_matrix_rs.rasterize`` op tuples.

    Returns a list of op tuples (empty for nodes the Python rasterizer treats
    as no-ops), or ``None`` for nodes that need the Python rasterizer for this
    frame. 3D nodes lower to Line/Rect/DebugText/DotGrid3D/DotPlane3D ops in
    display space, mirroring the Python 3D fallbacks painter's-order exactly.
    ``offsets`` applies the frame's content offset the same way the Python
    rasterizer does: logical-unit subtraction before scaling for 2D nodes,
    display-pixel subtraction after projection for 3D nodes.
    """
    np = _numpy()
    if isinstance(node, ClearNode):
        return [(0, *_rgba4(node.color_rgba))]
    if isinstance(node, ShaderRectNode):
        if node.shader != "full_suite_background":
            return [(
                1,
                float((node.x - offsets.x) * sx),
                float((node.y - offsets.y) * sy),
                float(node.width * sx),
                float(node.height * sy),
                *_rgba4(node.color_rgba),
            )]
        t = float(node.uniforms[0]) if node.uniforms else 0.0
        rotation = float(node.uniforms[1]) if len(node.uniforms) > 1 else 0.0
        scroll_y = float(node.uniforms[2]) if len(node.uniforms) > 2 else 0.0
        return [(4, t, rotation, scroll_y, offsets.dx, offsets.dy)]
    if isinstance(node, RectNode):
        return [(
            1,
            float((node.x - offsets.x) * sx),
            float((node.y - offsets.y) * sy),
            float(node.width * sx),
            float(node.height * sy),
            *_rgba4(node.color_rgba),
        )]
    if isinstance(node, RoundedRectNode):
        return [(
            2,
            float((node.x - offsets.x) * sx),
            float((node.y - offsets.y) * sy),
            float(node.width * sx),
            float(node.height * sy),
            float(node.radius * min(sx, sy)),
            *_rgba4(node.color_rgba),
        )]
    if isinstance(node, CircleNode):
        return [(
            3,
            float((node.cx - offsets.x) * sx),
            float((node.cy - offsets.y) * sy),
            float(node.radius) * ((sx + sy) * 0.5),
            float(node.stroke_width),
            *_rgba4(node.fill_rgba),
            *_rgba4(node.stroke_rgba),
        )]
    if isinstance(node, TextNode):
        mode, mask, mask_x, mask_y = _text_mask_for_node(node, sx, sy, offsets.x, offsets.y)
        if mode == "blend":
            mask_u8 = np.ascontiguousarray(mask)
            return [(
                6,
                int(mask_x),
                int(mask_y),
                int(mask_u8.shape[1]),
                int(mask_u8.shape[0]),
                mask_u8,
                *_rgba4(node.color_rgba),
            )]
        if mode == "none":
            return []
        return None
    if isinstance(node, (CpuLayerNode, ImageNode)):
        layer = node.rgba
        if isinstance(node, ImageNode) and layer is None:
            return []
        if not hasattr(layer, "shape"):
            return []
        view = _layer_payload_for_rs(layer)
        if view is None:
            return None
        layer_h, layer_w = int(view.shape[0]), int(view.shape[1])
        return [(
            5,
            int(round((node.x - offsets.x) * sx)),
            int(round((node.y - offsets.y) * sy)),
            layer_w,
            layer_h,
            view,
        )]
    if isinstance(node, (Camera3DNode, SvgNode)):
        return []
    width = int(frame.display_width)
    height = int(frame.display_height)
    if isinstance(node, Cube3DNode):
        return _encode_cube3d_for_rs(node, camera3d, width, height, offsets)
    if isinstance(node, DotGrid3DNode):
        return [(
            10,
            float(node.center[0]),
            float(node.center[1]),
            float(node.center[2]),
            float(node.extent),
            float(node.spacing),
            float(node.point_size),
            *_rgba4(node.color_rgba),
            *_camera_rs_basis(camera3d),
            offsets.dx,
            offsets.dy,
        )]
    if isinstance(node, DotPlane3DNode):
        return [(
            11,
            float(node.center[0]),
            float(node.center[1]),
            float(node.center[2]),
            float(node.width),
            float(node.depth),
            float(node.spacing),
            float(node.point_size),
            *_rgba4(node.color_rgba),
            *_camera_rs_basis(camera3d),
            offsets.dx,
            offsets.dy,
        )]
    if isinstance(node, Line3DNode):
        start = _project_point(node.start, camera3d, width, height)
        end = _project_point(node.end, camera3d, width, height)
        if start is None or end is None:
            return []
        return [(8, start[0] - offsets.dx, start[1] - offsets.dy, end[0] - offsets.dx, end[1] - offsets.dy, *_rgba4(node.color_rgba))]
    if isinstance(node, GroundPlane3DNode):
        return _encode_ground_plane3d_for_rs(node, camera3d, width, height, offsets)
    if isinstance(node, Horizon3DNode):
        return _encode_horizon3d_for_rs(node, camera3d, width, height, offsets)
    if isinstance(node, Text3DNode):
        return _encode_text3d_for_rs(node, camera3d, width, height, offsets)
    # Node kinds the Python rasterizer's elif chain does not handle are no-ops.
    return []


def _camera_rs_basis(camera: Camera3DNode) -> tuple:
    """Flattened camera basis for the Rust 3D raster ops.

    Built with the same helpers and expression order as ``_project_point`` so
    the Rust per-point projection reproduces the Python results bit for bit.
    Layout: eye(3), right(3), up(3), forward(3), f, near.
    """
    eye = camera.position
    target = camera.target
    forward = _normalize((target[0] - eye[0], target[1] - eye[1], target[2] - eye[2]))
    right = _normalize(_cross(forward, camera.up))
    up = _cross(right, forward)
    f = 1.0 / math.tan(math.radians(camera.fov_deg) * 0.5)
    return (*eye, *right, *up, *forward, f, float(camera.near))


def _encode_cube3d_for_rs(node: Cube3DNode, camera: Camera3DNode, width: int, height: int, offsets: _Offsets) -> list:
    points = [_project_point(_transform_cube_vertex(vertex, node), camera, width, height) for vertex in _CUBE_VERTICES]
    ops = []
    for start, end in _CUBE_EDGES:
        a = points[start]
        b = points[end]
        if a is None or b is None:
            continue
        ops.append((8, a[0] - offsets.dx, a[1] - offsets.dy, b[0] - offsets.dx, b[1] - offsets.dy, *_rgba4(node.edge_rgba)))
    for point in points:
        if point is not None:
            ops.append((1, point[0] - offsets.dx - 1.0, point[1] - offsets.dy - 1.0, 3.0, 3.0, *_rgba4(node.color_rgba)))
    return ops


def _encode_ground_plane3d_for_rs(node: GroundPlane3DNode, camera: Camera3DNode, width: int, height: int, offsets: _Offsets) -> list:
    half_w = float(node.width) * 0.5
    half_d = float(node.depth) * 0.5
    x0 = node.center[0] - half_w
    x1 = node.center[0] + half_w
    z0 = node.center[2] - half_d
    z1 = node.center[2] + half_d
    y = node.center[1]
    corners = (
        (x0, y, z0),
        (x1, y, z0),
        (x1, y, z1),
        (x0, y, z1),
    )
    points = [_project_point(point, camera, width, height) for point in corners]
    ops = []
    for start, end in ((0, 1), (1, 2), (2, 3), (3, 0)):
        a = points[start]
        b = points[end]
        if a is not None and b is not None:
            ops.append((8, a[0] - offsets.dx, a[1] - offsets.dy, b[0] - offsets.dx, b[1] - offsets.dy, *_rgba4(node.color_rgba)))
    return ops


def _encode_horizon3d_for_rs(node: Horizon3DNode, camera: Camera3DNode, width: int, height: int, offsets: _Offsets) -> list:
    dy = camera.target[1] - camera.position[1]
    dx = camera.target[0] - camera.position[0]
    dz = camera.target[2] - camera.position[2]
    distance = math.hypot(dx, dz) or 1.0
    pitch = math.atan2(dy, distance)
    fov = math.radians(camera.fov_deg)
    horizon_ndc = max(-0.95, min(0.95, math.tan(pitch) / math.tan(fov * 0.5)))
    horizon_y = int(round((0.5 - horizon_ndc * 0.5) * height))
    ops = [(1, 0 - offsets.dx, 0 - offsets.dy, width, max(0, horizon_y), *_rgba4(node.sky_rgba))]
    if node.sky_horizon_rgba is not None:
        ops.append((1, 0 - offsets.dx, max(0, horizon_y - height // 12) - offsets.dy, width, height // 12, *_rgba4(node.sky_horizon_rgba)))
    ops.append((1, 0 - offsets.dx, horizon_y - offsets.dy, width, max(0, height - horizon_y), *_rgba4(node.ground_rgba)))
    line_height = max(1, int(round(node.horizon_width * height)))
    ops.append((1, 0 - offsets.dx, (horizon_y - line_height // 2) - offsets.dy, width, line_height, *_rgba4(node.horizon_rgba)))
    return ops


def _encode_text3d_for_rs(node: Text3DNode, camera: Camera3DNode, width: int, height: int, offsets: _Offsets) -> list:
    point = _project_point(node.position, camera, width, height)
    if point is None:
        return []
    scale = max(1, int(round(node.height * 18.0)))
    # Text3DNode guarantees non-empty text, so the digest branch of
    # ``_draw_debug_text`` is unreachable; upper() mirrors what it draws.
    return [(
        9,
        node.text.upper(),
        int(point[0] - offsets.dx),
        int(point[1] - offsets.dy),
        scale,
        *_rgba4(node.color_rgba),
    )]


def _layer_payload_for_rs(layer):
    """Contiguous uint8 (H, W, 4) numpy view of a CpuLayer/Image payload."""
    np = _numpy()
    if np is None:
        return None
    torch = accel._torch
    if torch is not None and torch.is_tensor(layer):
        if layer.dtype != torch.uint8 or not layer.is_cpu:
            return None
        layer = layer.contiguous().numpy()
    if not isinstance(layer, np.ndarray):
        return None
    if layer.dtype != np.uint8 or layer.ndim != 3 or int(layer.shape[2]) != 4:
        return None
    return np.ascontiguousarray(layer)


class _Offsets(tuple):
    """Content-offset in logical units (x, y) and display pixels (dx, dy).

    Mirrors the native scene backends, which subtract the offset in logical
    units before scaling (Metal quad shader, Android geometry shift), and
    subtract the display-scaled offset after 3D projection.
    """

    __slots__ = ()

    def __new__(cls, x: float, y: float, sx: float, sy: float):
        return super().__new__(cls, (x, y, x * sx, y * sy))

    @property
    def x(self) -> float:
        return self[0]

    @property
    def y(self) -> float:
        return self[1]

    @property
    def dx(self) -> float:
        return self[2]

    @property
    def dy(self) -> float:
        return self[3]


def _rasterize_scene_frame_python(frame: SceneFrame, out=None):
    np = _numpy()
    if out is not None:
        if out.shape != (frame.display_height, frame.display_width, 4):
            out = None

    if out is None:
        if np is not None:
            out = np.zeros((frame.display_height, frame.display_width, 4), dtype=np.uint8)
        else:
            out = accel.zeros((frame.display_height, frame.display_width, 4))

    out[:, :, 3] = 255
    sx = float(frame.display_width) / max(1.0, float(frame.logical_width))
    sy = float(frame.display_height) / max(1.0, float(frame.logical_height))
    offsets = _Offsets(float(frame.content_offset_x), float(frame.content_offset_y), sx, sy)
    camera3d = _DEFAULT_CAMERA_3D
    for node in frame.nodes:
        if isinstance(node, ClearNode):
            out[:, :, 0] = node.color_rgba[0]
            out[:, :, 1] = node.color_rgba[1]
            out[:, :, 2] = node.color_rgba[2]
            out[:, :, 3] = node.color_rgba[3]
        elif isinstance(node, ShaderRectNode):
            _draw_shader_rect(out, node, sx=sx, sy=sy, offsets=offsets)
        elif isinstance(node, RectNode):
            _draw_rect(out, (node.x - offsets.x) * sx, (node.y - offsets.y) * sy, node.width * sx, node.height * sy, node.color_rgba)
        elif isinstance(node, RoundedRectNode):
            _draw_rounded_rect(out, (node.x - offsets.x) * sx, (node.y - offsets.y) * sy, node.width * sx, node.height * sy, node.radius * min(sx, sy), node.color_rgba)
        elif isinstance(node, CircleNode):
            _draw_circle(out, node, sx=sx, sy=sy, offsets=offsets)
        elif isinstance(node, TextNode):
            _draw_text(out, node, sx=sx, sy=sy, offsets=offsets)
        elif isinstance(node, Camera3DNode):
            camera3d = node
        elif isinstance(node, Cube3DNode):
            _draw_cube3d_fallback(out, node, camera3d, offsets)
        elif isinstance(node, DotGrid3DNode):
            _draw_dot_grid3d_fallback(out, node, camera3d, offsets)
        elif isinstance(node, DotPlane3DNode):
            _draw_dot_plane3d_fallback(out, node, camera3d, offsets)
        elif isinstance(node, Line3DNode):
            _draw_line3d_fallback(out, node, camera3d, offsets)
        elif isinstance(node, GroundPlane3DNode):
            _draw_ground_plane3d_fallback(out, node, camera3d, offsets)
        elif isinstance(node, Horizon3DNode):
            _draw_horizon3d_fallback(out, node, camera3d, offsets)
        elif isinstance(node, Text3DNode):
            _draw_text3d_fallback(out, node, camera3d, offsets)
        elif isinstance(node, CpuLayerNode):
            _draw_layer(out, node, sx=sx, sy=sy, offsets=offsets)
        elif isinstance(node, ImageNode) and node.rgba is not None:
            _draw_layer(out, CpuLayerNode(node.x, node.y, node.width, node.height, node.rgba, node.z_index), sx=sx, sy=sy, offsets=offsets)
        elif isinstance(node, SvgNode):
            # SVG scene fallback is intentionally no-op until vector CPU fallback
            # moves behind the retained scene API.
            continue
    return out


def _draw_cube3d_fallback(out, node: Cube3DNode, camera: Camera3DNode, offsets: _Offsets) -> None:
    points = [_project_point(_transform_cube_vertex(vertex, node), camera, out.shape[1], out.shape[0]) for vertex in _CUBE_VERTICES]
    for start, end in _CUBE_EDGES:
        a = points[start]
        b = points[end]
        if a is None or b is None:
            continue
        _draw_line(out, a[0] - offsets.dx, a[1] - offsets.dy, b[0] - offsets.dx, b[1] - offsets.dy, node.edge_rgba)
    for point in points:
        if point is not None:
            _draw_rect(out, point[0] - offsets.dx - 1.0, point[1] - offsets.dy - 1.0, 3.0, 3.0, node.color_rgba)


def _draw_dot_grid3d_fallback(out, node: DotGrid3DNode, camera: Camera3DNode, offsets: _Offsets) -> None:
    half = float(node.extent) * 0.5
    count = max(1, int(math.floor(float(node.extent) / float(node.spacing))))
    start = -count * float(node.spacing) * 0.5
    radius = max(1.0, float(node.point_size))
    for ix in range(count + 1):
        for iy in range(count + 1):
            for iz in range(count + 1):
                x = start + ix * float(node.spacing)
                y = start + iy * float(node.spacing)
                z = start + iz * float(node.spacing)
                if abs(x) > half or abs(y) > half or abs(z) > half:
                    continue
                point = _project_point((node.center[0] + x, node.center[1] + y, node.center[2] + z), camera, out.shape[1], out.shape[0])
                if point is not None:
                    _draw_rect(out, point[0] - offsets.dx - radius * 0.5, point[1] - offsets.dy - radius * 0.5, radius, radius, node.color_rgba)


def _draw_dot_plane3d_fallback(out, node: DotPlane3DNode, camera: Camera3DNode, offsets: _Offsets) -> None:
    x_count = max(1, int(math.floor(float(node.width) / float(node.spacing))))
    z_count = max(1, int(math.floor(float(node.depth) / float(node.spacing))))
    x_start = -x_count * float(node.spacing) * 0.5
    z_start = -z_count * float(node.spacing) * 0.5
    radius = max(1.0, float(node.point_size))
    for ix in range(x_count + 1):
        for iz in range(z_count + 1):
            point = _project_point(
                (
                    node.center[0] + x_start + ix * float(node.spacing),
                    node.center[1],
                    node.center[2] + z_start + iz * float(node.spacing),
                ),
                camera,
                out.shape[1],
                out.shape[0],
            )
            if point is not None:
                _draw_rect(out, point[0] - offsets.dx - radius * 0.5, point[1] - offsets.dy - radius * 0.5, radius, radius, node.color_rgba)


def _draw_line3d_fallback(out, node: Line3DNode, camera: Camera3DNode, offsets: _Offsets) -> None:
    start = _project_point(node.start, camera, out.shape[1], out.shape[0])
    end = _project_point(node.end, camera, out.shape[1], out.shape[0])
    if start is None or end is None:
        return
    _draw_line(out, start[0] - offsets.dx, start[1] - offsets.dy, end[0] - offsets.dx, end[1] - offsets.dy, node.color_rgba)


def _draw_ground_plane3d_fallback(out, node: GroundPlane3DNode, camera: Camera3DNode, offsets: _Offsets) -> None:
    half_w = float(node.width) * 0.5
    half_d = float(node.depth) * 0.5
    x0 = node.center[0] - half_w
    x1 = node.center[0] + half_w
    z0 = node.center[2] - half_d
    z1 = node.center[2] + half_d
    y = node.center[1]
    corners = (
        (x0, y, z0),
        (x1, y, z0),
        (x1, y, z1),
        (x0, y, z1),
    )
    points = [_project_point(point, camera, out.shape[1], out.shape[0]) for point in corners]
    for start, end in ((0, 1), (1, 2), (2, 3), (3, 0)):
        a = points[start]
        b = points[end]
        if a is not None and b is not None:
            _draw_line(out, a[0] - offsets.dx, a[1] - offsets.dy, b[0] - offsets.dx, b[1] - offsets.dy, node.color_rgba)


def _draw_horizon3d_fallback(out, node: Horizon3DNode, camera: Camera3DNode, offsets: _Offsets) -> None:
    height, width, _ = out.shape
    dy = camera.target[1] - camera.position[1]
    dx = camera.target[0] - camera.position[0]
    dz = camera.target[2] - camera.position[2]
    distance = math.hypot(dx, dz) or 1.0
    pitch = math.atan2(dy, distance)
    fov = math.radians(camera.fov_deg)
    horizon_ndc = max(-0.95, min(0.95, math.tan(pitch) / math.tan(fov * 0.5)))
    horizon_y = int(round((0.5 - horizon_ndc * 0.5) * height))
    _draw_rect(out, 0 - offsets.dx, 0 - offsets.dy, width, max(0, horizon_y), node.sky_rgba)
    if node.sky_horizon_rgba is not None:
        _draw_rect(out, 0 - offsets.dx, max(0, horizon_y - height // 12) - offsets.dy, width, height // 12, node.sky_horizon_rgba)
    _draw_rect(out, 0 - offsets.dx, horizon_y - offsets.dy, width, max(0, height - horizon_y), node.ground_rgba)
    line_height = max(1, int(round(node.horizon_width * height)))
    _draw_rect(out, 0 - offsets.dx, (horizon_y - line_height // 2) - offsets.dy, width, line_height, node.horizon_rgba)


def _draw_text3d_fallback(out, node: Text3DNode, camera: Camera3DNode, offsets: _Offsets) -> None:
    point = _project_point(node.position, camera, out.shape[1], out.shape[0])
    if point is None:
        return
    scale = max(1, int(round(node.height * 18.0)))
    _draw_debug_text(out, node.text, x=int(point[0] - offsets.dx), y=int(point[1] - offsets.dy), scale=scale, color=node.color_rgba)


def _transform_cube_vertex(vertex: tuple[float, float, float], node: Cube3DNode) -> tuple[float, float, float]:
    x, y, z = (float(v) * float(node.size) for v in vertex)
    rx, ry, rz = node.rotation
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    y, z = (y * cx - z * sx, y * sx + z * cx)
    x, z = (x * cy + z * sy, -x * sy + z * cy)
    x, y = (x * cz - y * sz, x * sz + y * cz)
    return (x + node.center[0], y + node.center[1], z + node.center[2])


def _project_point(point: tuple[float, float, float], camera: Camera3DNode, width: int, height: int) -> tuple[float, float] | None:
    eye = camera.position
    target = camera.target
    forward = _normalize((target[0] - eye[0], target[1] - eye[1], target[2] - eye[2]))
    right = _normalize(_cross(forward, camera.up))
    up = _cross(right, forward)
    rel = (point[0] - eye[0], point[1] - eye[1], point[2] - eye[2])
    x = _dot(rel, right)
    y = _dot(rel, up)
    z = _dot(rel, forward)
    if z <= max(1e-6, camera.near):
        return None
    aspect = float(width) / max(1.0, float(height))
    f = 1.0 / math.tan(math.radians(camera.fov_deg) * 0.5)
    ndc_x = (x * f / aspect) / z
    ndc_y = (y * f) / z
    return ((ndc_x * 0.5 + 0.5) * width, (0.5 - ndc_y * 0.5) * height)


def _normalize(v: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(max(1e-12, _dot(v, v)))
    return (v[0] / length, v[1] / length, v[2] / length)


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _draw_shader_rect(out, node: ShaderRectNode, *, sx: float, sy: float, offsets: _Offsets) -> None:
    if node.shader != "full_suite_background":
        _draw_rect(out, (node.x - offsets.x) * sx, (node.y - offsets.y) * sy, node.width * sx, node.height * sy, node.color_rgba)
        return
    np = _numpy()
    if np is not None:
        _draw_rainbow_background(out, node, offset_dx=offsets.dx, offset_dy=offsets.dy)
        return
    t = int(node.uniforms[0]) if node.uniforms else 0
    rotation = float(node.uniforms[1]) if len(node.uniforms) > 1 else 0.0
    scroll_y = float(node.uniforms[2]) if len(node.uniforms) > 2 else 0.0
    base_r = int((t * 3 + 35) % 255)
    base_g = int((t * 2 + 70) % 255)
    base_b = int((t * 4 + 20) % 255)
    rotate_boost = int(max(-30.0, min(30.0, rotation * 2.0)))
    scroll_boost = int(max(-40.0, min(40.0, scroll_y * 0.5)))
    color = (
        max(0, min(255, base_r + rotate_boost)),
        max(0, min(255, base_g + scroll_boost)),
        max(0, min(255, base_b)),
        255,
    )
    _draw_rect(out, (node.x - offsets.x) * sx, (node.y - offsets.y) * sy, node.width * sx, node.height * sy, color)


def _draw_rainbow_background(out, node: ShaderRectNode, *, offset_dx: float = 0.0, offset_dy: float = 0.0) -> None:
    np = _numpy()
    if np is None:
        return
    h, w, _ = out.shape
    t = float(node.uniforms[0]) if node.uniforms else 0.0
    rotation = float(node.uniforms[1]) if len(node.uniforms) > 1 else 0.0
    scroll_y = float(node.uniforms[2]) if len(node.uniforms) > 2 else 0.0
    yy, xx = np.mgrid[0:h, 0:w]
    nx = (xx + offset_dx).astype(np.float32) / max(1.0, float(w))
    ny = (yy + offset_dy).astype(np.float32) / max(1.0, float(h))
    phase = t * 0.0025 + rotation * 0.01 + scroll_y * 0.002
    wave = np.sin((nx * 3.2 + ny * 2.4 + phase) * (2.0 * np.pi)) * 0.055
    hue = (nx * 0.58 + ny * 0.42 + phase + wave) % 1.0
    value = np.clip(0.78 + 0.16 * np.sin((nx - ny + phase * 0.7) * (2.0 * np.pi)), 0.35, 0.95)
    # Vectorized HSV conversion for the CPU scene fallback.
    i = np.floor(hue * 6.0).astype(np.int32)
    f = hue * 6.0 - i
    p = value * (1.0 - 0.82)
    q = value * (1.0 - f * 0.82)
    tv = value * (1.0 - (1.0 - f) * 0.82)
    r = np.choose(i % 6, [value, q, p, p, tv, value])
    g = np.choose(i % 6, [tv, value, value, q, p, p])
    b = np.choose(i % 6, [p, p, tv, value, value, q])
    out[:, :, 0] = np.clip(r * 255.0, 0, 255).astype(np.uint8)
    out[:, :, 1] = np.clip(g * 255.0, 0, 255).astype(np.uint8)
    out[:, :, 2] = np.clip(b * 255.0, 0, 255).astype(np.uint8)
    out[:, :, 3] = 255


def _draw_rect(out, x: float, y: float, width: float, height: float, color: tuple[int, int, int, int]) -> None:
    h, w, _ = out.shape
    x0 = max(0, int(round(x)))
    y0 = max(0, int(round(y)))
    x1 = min(w, int(round(x + width)))
    y1 = min(h, int(round(y + height)))
    if x1 <= x0 or y1 <= y0:
        return
    alpha = color[3] / 255.0
    if alpha >= 0.999:
        out[y0:y1, x0:x1, :] = color
        return
    np = _numpy()
    if np is None:
        out[y0:y1, x0:x1, :] = color
        return
    dst = out[y0:y1, x0:x1, :3].astype(np.float32)
    src = np.asarray(color[:3], dtype=np.float32).reshape(1, 1, 3)
    out[y0:y1, x0:x1, :3] = np.clip(src * alpha + dst * (1.0 - alpha), 0, 255).astype(np.uint8)
    out[y0:y1, x0:x1, 3] = 255


def _draw_rounded_rect(out, x: float, y: float, width: float, height: float, radius: float, color: tuple[int, int, int, int]) -> None:
    np = _numpy()
    if np is None:
        _draw_rect(out, x, y, width, height, color)
        return
    h, w, _ = out.shape
    x0 = max(0, int(math.floor(x)))
    y0 = max(0, int(math.floor(y)))
    x1 = min(w, int(math.ceil(x + width)))
    y1 = min(h, int(math.ceil(y + height)))
    if x1 <= x0 or y1 <= y0:
        return
    r = max(0.0, min(float(radius), float(width) * 0.5, float(height) * 0.5))
    yy, xx = np.ogrid[y0:y1, x0:x1]
    left = x + r
    right = x + width - r
    top = y + r
    bottom = y + height - r
    nearest_x = np.clip(xx.astype(np.float32), left, right)
    nearest_y = np.clip(yy.astype(np.float32), top, bottom)
    mask = (xx - nearest_x) ** 2 + (yy - nearest_y) ** 2 <= r * r
    if r <= 0.0:
        mask = np.ones((y1 - y0, x1 - x0), dtype=bool)
    patch = out[y0:y1, x0:x1]
    alpha = color[3] / 255.0
    if alpha >= 0.999:
        patch[mask] = color
        return
    dst = patch[:, :, :3].astype(np.float32)
    src = np.asarray(color[:3], dtype=np.float32).reshape(1, 1, 3)
    blended = np.clip(src * alpha + dst * (1.0 - alpha), 0, 255).astype(np.uint8)
    patch[:, :, :3] = np.where(mask[:, :, None], blended, patch[:, :, :3])
    patch[:, :, 3] = np.where(mask, 255, patch[:, :, 3])


def _draw_line(out, x0: float, y0: float, x1: float, y1: float, color: tuple[int, int, int, int]) -> None:
    steps = max(1, int(round(max(abs(x1 - x0), abs(y1 - y0)))))
    for i in range(steps + 1):
        t = float(i) / float(steps)
        x = x0 + (x1 - x0) * t
        y = y0 + (y1 - y0) * t
        _draw_rect(out, x - 0.5, y - 0.5, 2.0, 2.0, color)


def _draw_circle(out, node: CircleNode, *, sx: float, sy: float, offsets: _Offsets) -> None:
    np = _numpy()
    if np is None:
        return
    h, w, _ = out.shape
    cx = (float(node.cx) - offsets.x) * sx
    cy = (float(node.cy) - offsets.y) * sy
    radius = max(0.0, float(node.radius) * ((sx + sy) * 0.5))
    x0 = max(0, int(math.floor(cx - radius - node.stroke_width - 1)))
    y0 = max(0, int(math.floor(cy - radius - node.stroke_width - 1)))
    x1 = min(w, int(math.ceil(cx + radius + node.stroke_width + 1)))
    y1 = min(h, int(math.ceil(cy + radius + node.stroke_width + 1)))
    if x1 <= x0 or y1 <= y0:
        return
    yy, xx = np.ogrid[y0:y1, x0:x1]
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    fill = dist <= radius
    patch = out[y0:y1, x0:x1]
    patch[fill] = node.fill_rgba
    if node.stroke_width > 0 and node.stroke_rgba[3] > 0:
        stroke = (dist > radius) & (dist <= radius + node.stroke_width)
        patch[stroke] = node.stroke_rgba


_TEXT_MASK_CACHE: dict[tuple[str, str, float], object] = {}


def _text_mask_for_node(node: TextNode, sx: float, sy: float, offset_x: float = 0.0, offset_y: float = 0.0) -> tuple[str, object, int, int]:
    """Resolve the glyph mask for a text node.

    Returns ``(mode, mask, x, y)``: ``"blend"`` pastes the mask at the rounded
    position, ``"debug"`` means the caller must draw the blocky fallback (with
    the truncated position), and ``"none"`` is a no-op.
    """
    try:
        from PIL import Image, ImageDraw
        from luvatrix_core.core.ui_frame_renderer import _load_font, _resolve_system_font_path
    except Exception:
        return ("debug", None, 0, 0)

    font_size = max(1.0, node.font_size_px * sy)
    rotation_deg = float(node.rotation_deg)
    cache_key = (node.text, node.font_family, font_size, rotation_deg)
    mask = _TEXT_MASK_CACHE.get(cache_key)

    if mask is None:
        try:
            font = _load_font(_resolve_system_font_path(node.font_family), font_size)
            bbox = font.getbbox(node.text)
            left, top, right, bottom = bbox
            width = max(1, int(math.ceil(right - left)))
            height = max(1, int(math.ceil(bottom - top)))
            image = Image.new("L", (width, height), 0)
            draw = ImageDraw.Draw(image)
            draw.text((-left, -top), node.text, fill=255, font=font)
            if rotation_deg:
                image = image.rotate(rotation_deg, resample=Image.Resampling.BICUBIC, expand=True)
            np = _numpy()
            if np is None:
                return ("none", None, 0, 0)
            mask = np.asarray(image, dtype=np.uint8)
            # Simple bounded cache
            if len(_TEXT_MASK_CACHE) > 500:
                _TEXT_MASK_CACHE.clear()
            _TEXT_MASK_CACHE[cache_key] = mask
        except Exception:
            return ("debug", None, 0, 0)

    return ("blend", mask, int(round((node.x - offset_x) * sx)), int(round((node.y - offset_y) * sy)))


def _draw_text(out, node: TextNode, *, sx: float, sy: float, offsets: _Offsets) -> None:
    mode, mask, x, y = _text_mask_for_node(node, sx, sy, offsets.x, offsets.y)
    if mode == "blend":
        _blend_alpha_mask(out, mask, x=x, y=y, color=node.color_rgba)
        return
    if mode == "debug":
        _draw_debug_text(out, node.text, x=int((node.x - offsets.x) * sx), y=int((node.y - offsets.y) * sy), scale=max(1, int(node.font_size_px * sy // 7)), color=node.color_rgba)


def _draw_layer(out, node: CpuLayerNode, *, sx: float, sy: float, offsets: _Offsets) -> None:
    layer = node.rgba
    if not hasattr(layer, "shape"):
        return
    x = int(round((node.x - offsets.x) * sx))
    y = int(round((node.y - offsets.y) * sy))
    h, w, _ = layer.shape
    _paste_rgba(out, layer, x=x, y=y, width=w, height=h)


def _blend_alpha_mask(out, mask, *, x: int, y: int, color: tuple[int, int, int, int]) -> None:
    np = _numpy()
    if np is None:
        return
    mask_np = mask if hasattr(mask, "astype") else accel.to_contiguous_numpy(mask)
    h, w = mask_np.shape
    dst_h, dst_w, _ = out.shape
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(dst_w, x + w)
    y1 = min(dst_h, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    sx0 = x0 - x
    sy0 = y0 - y
    alpha = (mask_np[sy0 : sy0 + (y1 - y0), sx0 : sx0 + (x1 - x0)].astype(np.float32) / 255.0) * (color[3] / 255.0)
    if not bool(np.any(alpha > 0.0)):
        return
    dst = out[y0:y1, x0:x1, :3].astype(np.float32)
    src = np.asarray(color[:3], dtype=np.float32).reshape(1, 1, 3)
    out[y0:y1, x0:x1, :3] = np.clip(src * alpha[:, :, None] + dst * (1.0 - alpha[:, :, None]), 0, 255).astype(np.uint8)
    out[y0:y1, x0:x1, 3] = 255


def _paste_rgba(out, src, *, x: int, y: int, width: int, height: int) -> None:
    dst_h, dst_w, _ = out.shape
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(dst_w, x + width)
    y1 = min(dst_h, y + height)
    if x1 <= x0 or y1 <= y0:
        return
    out[y0:y1, x0:x1, :] = src[y0 - y : y1 - y, x0 - x : x1 - x, :]


_DEBUG = {
    " ": ("000", "000", "000", "000", "000"),
    "-": ("000", "000", "111", "000", "000"),
    ".": ("000", "000", "000", "000", "010"),
    ":": ("000", "010", "000", "010", "000"),
}


def _draw_debug_text(out, text: str, *, x: int, y: int, scale: int, color: tuple[int, int, int, int]) -> None:
    digest = hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:12].upper()
    text = text.upper() if text else digest
    cursor = x
    for ch in text:
        glyph = _DEBUG.get(ch, ("111", "101", "101", "101", "111"))
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit == "1":
                    _draw_rect(out, cursor + gx * scale, y + gy * scale, scale, scale, color)
        cursor += 4 * scale
