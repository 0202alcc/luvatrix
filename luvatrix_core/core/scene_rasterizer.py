from __future__ import annotations

import hashlib
import math

from luvatrix_core import accel
from luvatrix_core.core.scene_graph import (
    CircleNode,
    ClearNode,
    CpuLayerNode,
    ImageNode,
    RectNode,
    SceneFrame,
    ShaderRectNode,
    SvgNode,
    TextNode,
)


def _numpy():
    np = getattr(accel, "_np", None)
    if np is not None:
        return np
    try:
        import numpy as np  # type: ignore
    except Exception:
        return None
    return np


def rasterize_scene_frame(frame: SceneFrame, out=None):
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
    for node in frame.nodes:
        if isinstance(node, ClearNode):
            out[:, :, 0] = node.color_rgba[0]
            out[:, :, 1] = node.color_rgba[1]
            out[:, :, 2] = node.color_rgba[2]
            out[:, :, 3] = node.color_rgba[3]
        elif isinstance(node, ShaderRectNode):
            _draw_shader_rect(out, node, sx=sx, sy=sy)
        elif isinstance(node, RectNode):
            _draw_rect(out, node.x * sx, node.y * sy, node.width * sx, node.height * sy, node.color_rgba)
        elif isinstance(node, CircleNode):
            _draw_circle(out, node, sx=sx, sy=sy)
        elif isinstance(node, TextNode):
            _draw_text(out, node, sx=sx, sy=sy)
        elif isinstance(node, CpuLayerNode):
            _draw_layer(out, node, sx=sx, sy=sy)
        elif isinstance(node, ImageNode) and node.rgba is not None:
            _draw_layer(out, CpuLayerNode(node.x, node.y, node.width, node.height, node.rgba, node.z_index), sx=sx, sy=sy)
        elif isinstance(node, SvgNode):
            # SVG scene fallback is intentionally no-op until vector CPU fallback
            # moves behind the retained scene API.
            continue
    return out


def _draw_shader_rect(out, node: ShaderRectNode, *, sx: float, sy: float) -> None:
    if node.shader != "full_suite_background":
        _draw_rect(out, node.x * sx, node.y * sy, node.width * sx, node.height * sy, node.color_rgba)
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
    _draw_rect(out, node.x * sx, node.y * sy, node.width * sx, node.height * sy, color)


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


def _draw_circle(out, node: CircleNode, *, sx: float, sy: float) -> None:
    np = _numpy()
    if np is None:
        return
    h, w, _ = out.shape
    cx = float(node.cx) * sx
    cy = float(node.cy) * sy
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

def _draw_text(out, node: TextNode, *, sx: float, sy: float) -> None:
    try:
        from PIL import Image, ImageDraw
        from luvatrix_core.core.ui_frame_renderer import _load_font, _resolve_system_font_path
    except Exception:
        _draw_debug_text(out, node.text, x=int(node.x * sx), y=int(node.y * sy), scale=max(1, int(node.font_size_px * sy // 7)), color=node.color_rgba)
        return
    
    font_size = max(1.0, node.font_size_px * sy)
    cache_key = (node.text, node.font_family, font_size)
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
            np = _numpy()
            if np is None:
                return
            mask = np.asarray(image, dtype=np.uint8)
            # Simple bounded cache
            if len(_TEXT_MASK_CACHE) > 500:
                _TEXT_MASK_CACHE.clear()
            _TEXT_MASK_CACHE[cache_key] = mask
        except Exception:
            _draw_debug_text(out, node.text, x=int(node.x * sx), y=int(node.y * sy), scale=max(1, int(node.font_size_px * sy // 7)), color=node.color_rgba)
            return
            
    _blend_alpha_mask(out, mask, x=int(round(node.x * sx)), y=int(round(node.y * sy)), color=node.color_rgba)


def _draw_layer(out, node: CpuLayerNode, *, sx: float, sy: float) -> None:
    layer = node.rgba
    if not hasattr(layer, "shape"):
        return
    x = int(round(node.x * sx))
    y = int(round(node.y * sy))
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
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12].upper()
    text = text.upper() if text else digest
    cursor = x
    for ch in text:
        glyph = _DEBUG.get(ch, ("111", "101", "101", "101", "111"))
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit == "1":
                    _draw_rect(out, cursor + gx * scale, y + gy * scale, scale, scale, color)
        cursor += 4 * scale
