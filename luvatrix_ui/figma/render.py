from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable

import numpy as np

from .document import FRAME_TYPES, TRANSPARENT_CONTAINERS, FigmaDocument, Frame, is_visible, node_size, node_transform
from .geometry import (
    Affine,
    Coverage,
    Ellipse,
    PathShape,
    Rect,
    RoundedRect,
    Shape,
    flatten,
    intersect,
    path_shape_from_geometry,
    polyline_coverage,
    union,
)
from .paint import ImageCache, paint_field, visible_paints
from .text import FontLibrary, text_coverages

BOX_TYPES = FRAME_TYPES | {"RECTANGLE", "SECTION"}
VECTOR_TYPES = frozenset({"VECTOR", "STAR", "REGULAR_POLYGON", "BOOLEAN_OPERATION", "LINE"})


@dataclass(frozen=True)
class Clip:
    rect: Rect
    mask: Coverage | None = None

    def restrict(self, cov: Coverage) -> Coverage | None:
        rect = intersect((cov.x0, cov.y0, cov.x1, cov.y1), self.rect)
        if rect is None:
            return None
        x0, y0, x1, y1 = rect
        out = cov.mask[y0 - cov.y0 : y1 - cov.y0, x0 - cov.x0 : x1 - cov.x0]
        if self.mask is not None:
            m = self.mask
            mrect = intersect(rect, (m.x0, m.y0, m.x1, m.y1))
            if mrect is None:
                return None
            x0, y0, x1, y1 = mrect
            out = cov.mask[y0 - cov.y0 : y1 - cov.y0, x0 - cov.x0 : x1 - cov.x0] * m.mask[y0 - m.y0 : y1 - m.y0, x0 - m.x0 : x1 - m.x0]
        return Coverage(x0, y0, out)

    def narrowed(self, cov: Coverage | None, *, exact: bool) -> "Clip":
        if cov is None:
            return Clip((0, 0, 0, 0))
        rect = intersect(self.rect, (cov.x0, cov.y0, cov.x1, cov.y1)) or (0, 0, 0, 0)
        if not exact and self.mask is None:
            return Clip(rect)
        restricted = self.restrict(cov)
        if restricted is None:
            return Clip((0, 0, 0, 0))
        return Clip(intersect(rect, (restricted.x0, restricted.y0, restricted.x1, restricted.y1)) or (0, 0, 0, 0), restricted)


def corner_radii(node: dict[str, Any]) -> tuple[float, float, float, float]:
    radii = node.get("rectangleCornerRadii")
    if isinstance(radii, list) and len(radii) == 4:
        return tuple(float(r) for r in radii)  # type: ignore[return-value]
    r = float(node.get("cornerRadius", 0.0) or 0.0)
    return (r, r, r, r)


def _arc_is_full(node: dict[str, Any]) -> bool:
    arc = node.get("arcData")
    if not isinstance(arc, dict):
        return True
    start = float(arc.get("startingAngle", 0.0))
    end = float(arc.get("endingAngle", 2 * math.pi))
    return float(arc.get("innerRadius", 0.0)) == 0.0 and abs(abs(end - start) - 2 * math.pi) < 1e-3


class FigmaRenderer:
    def __init__(self, doc: FigmaDocument, *, font_dirs: Iterable[str] = (), fonts: FontLibrary | None = None) -> None:
        self.doc = doc
        dirs = list(font_dirs)
        if doc.base_dir is not None:
            dirs.append(str(doc.base_dir / "fonts"))
        self.fonts = fonts or FontLibrary(dirs)
        self.images = ImageCache(doc.image_path)

    def render(self, frame_id: str, scale: float = 1.0, *, background: tuple[float, float, float, float] | None = None) -> np.ndarray:
        frame = self.doc.frame(frame_id)
        width = max(1, int(round(frame.width * scale)))
        height = max(1, int(round(frame.height * scale)))
        canvas = np.zeros((height, width, 4), dtype=np.float32)
        self._root = Affine.scale(width / frame.width, height / frame.height)
        self._draw_node(frame.node, Affine(), Affine(), Clip((0, 0, width, height)), canvas, frame)
        bg = background or self.doc.background_rgba or (1.0, 1.0, 1.0, 1.0)
        bg_pre = np.array([bg[0], bg[1], bg[2], 1.0], dtype=np.float32)
        out = canvas + bg_pre * (1.0 - canvas[..., 3:4])
        return np.clip(np.rint(out * 255.0), 0, 255).astype(np.uint8)

    # ── tree walk ────────────────────────────────────────────────────────────

    def _draw_node(
        self,
        node: dict[str, Any],
        tf: Affine,
        container: Affine,
        clip: Clip,
        canvas: np.ndarray,
        frame: Frame,
    ) -> None:
        if clip.rect[2] <= clip.rect[0] or clip.rect[3] <= clip.rect[1]:
            return
        opacity = float(node.get("opacity", 1.0))
        if opacity <= 0.0:
            return
        children = [c for c in node.get("children") or () if isinstance(c, dict) and is_visible(c)]
        node_type = node.get("type")
        if node_type == "BOOLEAN_OPERATION" and node.get("fillGeometry"):
            children = []
        effects = [e for e in node.get("effects") or () if isinstance(e, dict) and e.get("visible", True) is not False]
        has_fill = bool(visible_paints(node.get("fills")))
        content_shadow = bool(children) and not has_fill and any(e.get("type") == "DROP_SHADOW" for e in effects)
        if children and (opacity < 1.0 or content_shadow):
            layer = np.zeros_like(canvas)
            self._draw_contents(node, children, tf, container, clip, layer, frame, effects, opacity=1.0, shadow_from_layer=content_shadow)
            if content_shadow:
                for effect in effects:
                    if effect.get("type") == "DROP_SHADOW":
                        self._drop_shadow(canvas, _alpha_coverage(layer, clip.rect), effect, self._root @ tf, clip)
            _composite_layer(canvas, layer, clip.rect, opacity)
            return
        self._draw_contents(node, children, tf, container, clip, canvas, frame, effects, opacity=opacity, shadow_from_layer=False)

    def _draw_contents(
        self,
        node: dict[str, Any],
        children: list[dict[str, Any]],
        tf: Affine,
        container: Affine,
        clip: Clip,
        target: np.ndarray,
        frame: Frame,
        effects: list[dict[str, Any]],
        *,
        opacity: float,
        shadow_from_layer: bool,
    ) -> None:
        local, tf = tf, self._root @ tf
        shape = self._shape(node)
        size = node_size(node)
        node_type = node.get("type")
        if node_type == "TEXT":
            self._draw_text(node, tf, size, clip, target, effects, opacity)
        elif shape is not None:
            fill_cov = shape.coverage(tf, clip.rect)
            if not shadow_from_layer:
                for effect in effects:
                    if effect.get("type") == "DROP_SHADOW":
                        self._drop_shadow(target, self._shadow_coverage(shape, tf, effect, clip), effect, tf, clip)
            for effect in effects:
                if effect.get("type") == "BACKGROUND_BLUR" and fill_cov is not None:
                    _background_blur(target, clip.restrict(fill_cov), float(effect.get("radius", 0.0)) * tf.mean_scale)
            if fill_cov is not None:
                self._fill(target, clip.restrict(fill_cov), node.get("fills"), tf, size, opacity)
                for effect in effects:
                    if effect.get("type") == "INNER_SHADOW":
                        self._inner_shadow(target, shape, fill_cov, effect, tf, clip, opacity)
        child_container = container if node_type in TRANSPARENT_CONTAINERS else local
        child_clip = clip
        if node.get("clipsContent") and shape is not None:
            exact = any(corner_radii(node)) or not tf.is_axis_aligned
            child_clip = clip.narrowed(shape.coverage(tf, clip.rect), exact=exact)
        mask_clip: Clip | None = None
        for child in children:
            child_tf = node_transform(child, child_container, frame)
            active = mask_clip or child_clip
            if child.get("isMask"):
                child_shape = self._shape(child)
                cov = child_shape.coverage(self._root @ child_tf, active.rect) if child_shape is not None else None
                mask_clip = active.narrowed(cov, exact=True)
                continue
            self._draw_node(child, child_tf, child_container, active, target, frame)
        if shape is not None and node_type != "TEXT":
            self._strokes(node, shape, tf, size, clip, target, opacity)

    # ── shapes ───────────────────────────────────────────────────────────────

    def _shape(self, node: dict[str, Any]) -> Shape | None:
        node_type = node.get("type")
        width, height = node_size(node)
        if node_type in BOX_TYPES:
            return RoundedRect(width, height, corner_radii(node))
        if node_type == "ELLIPSE":
            if _arc_is_full(node):
                return Ellipse(width, height)
            return path_shape_from_geometry(node.get("fillGeometry") or ())
        if node_type in VECTOR_TYPES:
            return path_shape_from_geometry(node.get("fillGeometry") or ()) or (
                _LineShape(width, height) if node_type == "LINE" else None
            )
        if node_type == "TEXT":
            return RoundedRect(width, height)
        return None

    def _fill(self, target: np.ndarray, cov: Coverage | None, paints: Any, tf: Affine, size: tuple[float, float], opacity: float) -> None:
        if cov is None:
            return
        rect = (cov.x0, cov.y0, cov.x1, cov.y1)
        for paint in visible_paints(paints):
            field = paint_field(paint, rect, tf, size, self.images, opacity=opacity)
            if field is not None:
                _composite(target, cov, field)

    def _strokes(
        self,
        node: dict[str, Any],
        shape: Shape,
        tf: Affine,
        size: tuple[float, float],
        clip: Clip,
        target: np.ndarray,
        opacity: float,
    ) -> None:
        paints = visible_paints(node.get("strokes"))
        weight = float(node.get("strokeWeight", 1.0) or 0.0)
        if not paints or weight <= 0:
            return
        cov: Coverage | None
        geometry = node.get("strokeGeometry")
        per_side = node.get("individualStrokeWeights")
        if geometry:
            stroke_shape = path_shape_from_geometry(geometry)
            cov = stroke_shape.coverage(tf, clip.rect) if stroke_shape is not None else None
        elif isinstance(per_side, dict) and isinstance(shape, RoundedRect):
            cov = self._side_strokes(per_side, size, tf, clip)
        elif isinstance(shape, (RoundedRect, Ellipse)):
            default = "INSIDE" if node.get("type") in BOX_TYPES | {"ELLIPSE"} else "CENTER"
            align = str(node.get("strokeAlign", default))
            w = weight * tf.mean_scale
            lo, hi = {"INSIDE": (-w, 0.0), "OUTSIDE": (0.0, w)}.get(align, (-w / 2, w / 2))
            cov = shape.coverage(tf, clip.rect, lo, hi)
        elif isinstance(shape, _LineShape):
            cov = polyline_coverage([tf.apply_points(np.array([[0.0, 0.0], [shape.width, 0.0]]))], weight * tf.mean_scale, clip.rect)
        elif isinstance(shape, PathShape):
            polys = []
            for subpaths, _rule in shape.paths:
                for sub, poly in zip(subpaths, _flatten_each(subpaths, tf)):
                    if sub and sub[-1][0] == "Z":
                        poly = np.vstack([poly, poly[:1]])
                    polys.append(poly)
            cov = polyline_coverage(polys, weight * tf.mean_scale, clip.rect)
        else:
            cov = None
        if cov is not None:
            self._fill(target, clip.restrict(cov), paints, tf, size, opacity)

    def _side_strokes(self, sides: dict[str, Any], size: tuple[float, float], tf: Affine, clip: Clip) -> Coverage | None:
        w, h = size
        top, right = float(sides.get("top", 0)), float(sides.get("right", 0))
        bottom, left = float(sides.get("bottom", 0)), float(sides.get("left", 0))
        merged: Coverage | None = None
        for x, y, sw, sh in ((0, 0, w, top), (w - right, 0, right, h), (0, h - bottom, w, bottom), (0, 0, left, h)):
            if sw > 0 and sh > 0:
                merged = union(merged, RoundedRect(sw, sh).coverage(tf @ Affine.translate(x, y), clip.rect))
        return merged

    # ── text ─────────────────────────────────────────────────────────────────

    def _draw_text(
        self,
        node: dict[str, Any],
        tf: Affine,
        size: tuple[float, float],
        clip: Clip,
        target: np.ndarray,
        effects: list[dict[str, Any]],
        opacity: float,
    ) -> None:
        pieces = text_coverages(node, tf, size, clip.rect, self.fonts)
        for effect in effects:
            if effect.get("type") == "DROP_SHADOW":
                for cov, _fills in pieces:
                    self._drop_shadow(target, cov, effect, tf, clip)
        for cov, fills in pieces:
            self._fill(target, clip.restrict(cov), list(fills), tf, size, opacity)

    # ── effects ──────────────────────────────────────────────────────────────

    def _shadow_coverage(self, shape: Shape, tf: Affine, effect: dict[str, Any], clip: Clip) -> Coverage | None:
        spread = float(effect.get("spread", 0.0) or 0.0) * tf.mean_scale
        blur = float(effect.get("radius", 0.0) or 0.0) * tf.mean_scale
        offset = effect.get("offset") or {}
        dx, dy = float(offset.get("x", 0.0)) * tf.mean_scale, float(offset.get("y", 0.0)) * tf.mean_scale
        reach = int(math.ceil(blur * 1.5 + abs(spread) + abs(dx) + abs(dy))) + 2
        h, w = clip.rect[3], clip.rect[2]
        wide = (-reach, -reach, w + reach, h + reach)
        if abs(spread) > 1e-6:
            return shape.coverage(tf, wide, -math.inf, spread)
        return shape.coverage(tf, wide)

    def _drop_shadow(self, target: np.ndarray, cov: Coverage | None, effect: dict[str, Any], tf: Affine, clip: Clip) -> None:
        if cov is None:
            return
        s = tf.mean_scale
        offset = effect.get("offset") or {}
        dx = int(round(float(offset.get("x", 0.0)) * s))
        dy = int(round(float(offset.get("y", 0.0)) * s))
        blur = float(effect.get("radius", 0.0) or 0.0) * s
        shifted = _blur(Coverage(cov.x0 + dx, cov.y0 + dy, cov.mask), blur)
        restricted = clip.restrict(shifted)
        if restricted is None:
            return
        color = effect.get("color") or {}
        rgba = (float(color.get("r", 0)), float(color.get("g", 0)), float(color.get("b", 0)), float(color.get("a", 0.25)))
        field = np.array([[[rgba[0] * rgba[3], rgba[1] * rgba[3], rgba[2] * rgba[3], rgba[3]]]], dtype=np.float32)
        _composite(target, restricted, field)

    def _inner_shadow(
        self,
        target: np.ndarray,
        shape: Shape,
        fill_cov: Coverage,
        effect: dict[str, Any],
        tf: Affine,
        clip: Clip,
        opacity: float,
    ) -> None:
        s = tf.mean_scale
        offset = effect.get("offset") or {}
        dx = int(round(float(offset.get("x", 0.0)) * s))
        dy = int(round(float(offset.get("y", 0.0)) * s))
        blur = float(effect.get("radius", 0.0) or 0.0) * s
        spread = float(effect.get("spread", 0.0) or 0.0) * s
        pad = int(math.ceil(blur * 1.5 + abs(dx) + abs(dy) + abs(spread))) + 2
        x0, y0, x1, y1 = fill_cov.x0 - pad, fill_cov.y0 - pad, fill_cov.x1 + pad, fill_cov.y1 + pad
        inner = shape.coverage(tf, (x0, y0, x1, y1), -math.inf, -spread) if spread else shape.coverage(tf, (x0, y0, x1, y1))
        if inner is None:
            return
        canvas = np.zeros((y1 - y0, x1 - x0), dtype=np.float32)
        canvas[inner.y0 - y0 : inner.y1 - y0, inner.x0 - x0 : inner.x1 - x0] = inner.mask
        outside = _blur(Coverage(x0 + dx, y0 + dy, 1.0 - canvas), blur)
        ox0, oy0 = fill_cov.x0 - outside.x0, fill_cov.y0 - outside.y0
        region = np.ones_like(fill_cov.mask)
        sub = outside.mask[max(0, oy0) : oy0 + fill_cov.mask.shape[0], max(0, ox0) : ox0 + fill_cov.mask.shape[1]]
        region[: sub.shape[0], : sub.shape[1]] = sub
        cov = clip.restrict(Coverage(fill_cov.x0, fill_cov.y0, fill_cov.mask * region))
        if cov is None:
            return
        color = effect.get("color") or {}
        a = float(color.get("a", 0.25)) * opacity
        field = np.array([[[float(color.get("r", 0)) * a, float(color.get("g", 0)) * a, float(color.get("b", 0)) * a, a]]], dtype=np.float32)
        _composite(target, cov, field)


class _LineShape(Shape):
    def __init__(self, width: float, height: float) -> None:
        self.width = width
        self.height = height

    def polygons(self, tf: Affine) -> list[np.ndarray]:
        return []

    def coverage(self, tf: Affine, clip: Rect, lo: float = -math.inf, hi: float = 0.0) -> Coverage | None:
        return None


def _flatten_each(subpaths: list, tf: Affine) -> list[np.ndarray]:
    out = []
    for sub in subpaths:
        polys = flatten([sub], tf)
        out.append(polys[0] if polys else np.zeros((0, 2)))
    return out


def _composite(target: np.ndarray, cov: Coverage, field: np.ndarray) -> None:
    region = target[cov.y0 : cov.y1, cov.x0 : cov.x1]
    if region.size == 0:
        return
    h, w = region.shape[:2]
    mask = cov.mask[:h, :w, None]
    if field.shape[0] != 1:
        field = field[:h, :w]
    src = field * mask
    region *= 1.0 - src[..., 3:4]
    region += src


def _composite_layer(target: np.ndarray, layer: np.ndarray, rect: Rect, opacity: float) -> None:
    x0, y0, x1, y1 = rect
    src = layer[y0:y1, x0:x1] * opacity
    dst = target[y0:y1, x0:x1]
    dst *= 1.0 - src[..., 3:4]
    dst += src


def _alpha_coverage(layer: np.ndarray, rect: Rect) -> Coverage | None:
    x0, y0, x1, y1 = rect
    alpha = layer[y0:y1, x0:x1, 3]
    if not alpha.any():
        return None
    return Coverage(x0, y0, alpha.copy())


def _blur(cov: Coverage, radius_px: float) -> Coverage:
    if radius_px <= 0.5:
        return cov
    sigma = radius_px / 2.0
    pad = int(math.ceil(sigma * 3))
    h, w = cov.mask.shape
    padded = np.zeros((h + 2 * pad, w + 2 * pad), dtype=np.float32)
    padded[pad : pad + h, pad : pad + w] = cov.mask
    return Coverage(cov.x0 - pad, cov.y0 - pad, gaussian_blur(padded, sigma))


def _box_blur_axis(arr: np.ndarray, radius: int, axis: int) -> np.ndarray:
    if radius <= 0:
        return arr
    pad = [(0, 0)] * arr.ndim
    pad[axis] = (radius + 1, radius)
    padded = np.pad(arr, pad, mode="edge")
    csum = np.cumsum(padded, axis=axis, dtype=np.float64)
    n = arr.shape[axis]
    hi = np.take(csum, np.arange(2 * radius + 1, 2 * radius + 1 + n), axis=axis)
    lo = np.take(csum, np.arange(0, n), axis=axis)
    return ((hi - lo) / (2 * radius + 1)).astype(np.float32)


def gaussian_blur(arr: np.ndarray, sigma: float) -> np.ndarray:
    """Approximate a Gaussian with three box blurs per axis."""
    if sigma <= 0.3:
        return arr.astype(np.float32, copy=True)
    radius = max(1, int(round((math.sqrt(4 * sigma * sigma + 1) - 1) / 2)))
    out = arr.astype(np.float32, copy=True)
    for _ in range(3):
        out = _box_blur_axis(out, radius, 0)
        out = _box_blur_axis(out, radius, 1)
    return out


def _background_blur(target: np.ndarray, cov: Coverage | None, radius_px: float) -> None:
    if cov is None or radius_px <= 0.5:
        return
    region = target[cov.y0 : cov.y1, cov.x0 : cov.x1]
    if region.size == 0:
        return
    blurred = np.stack([gaussian_blur(region[..., ch], radius_px / 2) for ch in range(4)], axis=-1)
    mask = cov.mask[: region.shape[0], : region.shape[1], None]
    region[...] = region * (1 - mask) + blurred * mask


def render_frame(
    doc: FigmaDocument,
    frame_id: str,
    scale: float = 1.0,
    *,
    font_dirs: Iterable[str] = (),
    background: tuple[float, float, float, float] | None = None,
) -> np.ndarray:
    """Rasterize one top-level frame to an opaque (H, W, 4) uint8 RGBA array."""
    return FigmaRenderer(doc, font_dirs=font_dirs).render(frame_id, scale, background=background)
