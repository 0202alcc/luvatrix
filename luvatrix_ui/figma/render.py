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
    dashed_polyline_coverage,
    path_shape_from_geometry,
    polyline_coverage,
    union,
)
from .paint import NON_NORMAL_BLEND_MODES, ImageCache, blend_composite, paint_field, visible_paints
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
    def __init__(
        self,
        doc: FigmaDocument,
        *,
        font_dirs: Iterable[str] = (),
        fonts: FontLibrary | None = None,
        variant_overrides: dict[str, str] | None = None,
    ) -> None:
        self.doc = doc
        dirs = list(font_dirs)
        if doc.base_dir is not None:
            dirs.append(str(doc.base_dir / "fonts"))
        self.fonts = fonts or FontLibrary(dirs)
        self.images = ImageCache(doc.image_path)
        self.variant_overrides: dict[str, str] = variant_overrides if variant_overrides is not None else {}
        self._backdrops: list[tuple[Coverage, float]] | None = None

    def render(
        self,
        frame_id: str,
        scale: float = 1.0,
        *,
        background: tuple[float, float, float, float] | None = None,
        skip_ids: Iterable[str] = (),
        only_ids: Iterable[str] | None = None,
        transparent: bool = False,
        backdrops: list[tuple[Coverage, float]] | None = None,
    ) -> np.ndarray:
        """Rasterize a frame to (H, W, 4) uint8 RGBA.

        `skip_ids` drops those subtrees; `only_ids` draws just those subtrees (the
        frame's own fills included only if its id is listed). With `transparent`
        the result keeps straight alpha instead of being flattened onto a background.
        When a `backdrops` list is given, BACKGROUND_BLUR effects are appended to it
        as (coverage, radius in pixels) instead of blurring this canvas, so a caller
        compositing the result over other content can blur that content instead.
        """
        self._backdrops = backdrops
        frame = self.doc.frame(frame_id)
        width = max(1, int(round(frame.width * scale)))
        height = max(1, int(round(frame.height * scale)))
        canvas = np.zeros((height, width, 4), dtype=np.float32)
        self._root = Affine.scale(width / frame.width, height / frame.height)
        self._skip = frozenset(skip_ids)
        self._only = None if only_ids is None else frozenset(only_ids)
        included = self._only is None or str(frame.node.get("id")) in self._only
        self._draw_node(frame.node, Affine(), Affine(), Clip((0, 0, width, height)), canvas, frame, included)
        if transparent:
            alpha = canvas[..., 3:4]
            straight = np.where(alpha > 1e-6, canvas / np.maximum(alpha, 1e-6), 0.0)
            straight[..., 3:4] = alpha
            return np.clip(np.rint(straight * 255.0), 0, 255).astype(np.uint8)
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
        included: bool = True,
    ) -> None:
        if str(node.get("id")) in self._skip:
            return
        node = self._variant_node(node)
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
        blend = str(node.get("blendMode", "NORMAL")).upper()
        if blend == "PASS_THROUGH":
            blend = "NORMAL"
        layer_blur = next((e for e in effects if e.get("type") == "LAYER_BLUR"), None)
        if layer_blur is not None:
            layer = np.zeros_like(canvas)
            self._draw_contents(node, children, tf, container, clip, layer, frame, effects, included, opacity=1.0, shadow_from_layer=content_shadow, blend=blend)
            if content_shadow:
                for effect in effects:
                    if effect.get("type") == "DROP_SHADOW":
                        self._drop_shadow(layer, _alpha_coverage(layer, clip.rect), effect, self._root @ tf, clip)
            radius = float(layer_blur.get("radius", 0.0) or 0.0) * (self._root @ tf).mean_scale
            self._layer_blur(canvas, layer, clip.rect, radius, opacity, blend)
            return
        if children and (opacity < 1.0 or content_shadow or blend in NON_NORMAL_BLEND_MODES):
            layer = np.zeros_like(canvas)
            self._draw_contents(node, children, tf, container, clip, layer, frame, effects, included, opacity=1.0, shadow_from_layer=content_shadow, blend=blend)
            if content_shadow:
                for effect in effects:
                    if effect.get("type") == "DROP_SHADOW":
                        self._drop_shadow(canvas, _alpha_coverage(layer, clip.rect), effect, self._root @ tf, clip)
            _composite_layer(canvas, layer, clip.rect, opacity, blend)
            return
        self._draw_contents(node, children, tf, container, clip, canvas, frame, effects, included, opacity=opacity, shadow_from_layer=False, blend=blend)

    def _variant_node(self, node: dict[str, Any]) -> dict[str, Any]:
        """Substitute a component instance with its overridden variant, if any."""
        if node.get("type") != "INSTANCE" or not self.variant_overrides:
            return node
        variant = self.doc.node_or_none(self.variant_overrides.get(str(node.get("id")), ""))
        if variant is None:
            return node
        effective = dict(variant)
        if "opacity" not in effective and "opacity" in node:
            effective["opacity"] = node["opacity"]
        return effective

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
        included: bool,
        *,
        opacity: float,
        shadow_from_layer: bool,
        blend: str = "NORMAL",
    ) -> None:
        local, tf = tf, self._root @ tf
        shape = self._shape(node)
        size = node_size(node)
        node_type = node.get("type")
        if included:
            self._draw_self(node, shape, tf, size, clip, target, effects, opacity=opacity, shadow_from_layer=shadow_from_layer, blend=blend)
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
            child_included = included or (self._only is not None and str(child.get("id")) in self._only)
            self._draw_node(child, child_tf, child_container, active, target, frame, child_included)
        if included and shape is not None and node_type != "TEXT":
            self._strokes(node, shape, tf, size, clip, target, opacity, blend)

    def _draw_self(
        self,
        node: dict[str, Any],
        shape: Shape | None,
        tf: Affine,
        size: tuple[float, float],
        clip: Clip,
        target: np.ndarray,
        effects: list[dict[str, Any]],
        *,
        opacity: float,
        shadow_from_layer: bool,
        blend: str = "NORMAL",
    ) -> None:
        if node.get("type") == "TEXT":
            self._draw_text(node, tf, size, clip, target, effects, opacity, blend)
            return
        if shape is None:
            return
        fill_cov = shape.coverage(tf, clip.rect)
        if not shadow_from_layer:
            for effect in effects:
                if effect.get("type") == "DROP_SHADOW":
                    self._drop_shadow(target, self._shadow_coverage(shape, tf, effect, clip), effect, tf, clip)
        if fill_cov is None:
            return
        for effect in effects:
            if effect.get("type") == "BACKGROUND_BLUR":
                radius_px = float(effect.get("radius", 0.0)) * tf.mean_scale
                region = clip.restrict(fill_cov)
                if self._backdrops is None:
                    _background_blur(target, region, radius_px)
                elif region is not None and radius_px > 0.5:
                    self._backdrops.append((region, radius_px))
        self._fill(target, clip.restrict(fill_cov), node.get("fills"), tf, size, opacity, blend)
        for effect in effects:
            if effect.get("type") == "INNER_SHADOW":
                self._inner_shadow(target, shape, fill_cov, effect, tf, clip, opacity)

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
            return (
                path_shape_from_geometry(node.get("fillGeometry") or ())
                or path_shape_from_geometry(node.get("vectorPaths") or ())
                or (_LineShape(width, height) if node_type == "LINE" else None)
            )
        if node_type == "TEXT":
            return RoundedRect(width, height)
        return None

    def _fill(
        self,
        target: np.ndarray,
        cov: Coverage | None,
        paints: Any,
        tf: Affine,
        size: tuple[float, float],
        opacity: float,
        blend: str = "NORMAL",
    ) -> None:
        if cov is None:
            return
        rect = (cov.x0, cov.y0, cov.x1, cov.y1)
        for paint in visible_paints(paints):
            field = paint_field(paint, rect, tf, size, self.images, opacity=opacity)
            if field is not None:
                paint_mode = str(paint.get("blendMode", "NORMAL")).upper()
                _composite(target, cov, field, paint_mode if paint_mode in NON_NORMAL_BLEND_MODES else blend)

    def _strokes(
        self,
        node: dict[str, Any],
        shape: Shape,
        tf: Affine,
        size: tuple[float, float],
        clip: Clip,
        target: np.ndarray,
        opacity: float,
        blend: str = "NORMAL",
    ) -> None:
        paints = visible_paints(node.get("strokes"))
        weight = float(node.get("strokeWeight", 1.0) or 0.0)
        if not paints or weight <= 0:
            return
        cov: Coverage | None
        geometry = node.get("strokeGeometry")
        per_side = node.get("individualStrokeWeights")
        dashes = node.get("strokeDashes") or node.get("dashPattern")
        if dashes:
            pattern = [float(d) * tf.mean_scale for d in dashes if float(d) > 0]
            default = "INSIDE" if node.get("type") in BOX_TYPES | {"ELLIPSE"} else "CENTER"
            align = str(node.get("strokeAlign", default))
            w = weight * tf.mean_scale
            offset = {"INSIDE": -w / 2, "OUTSIDE": w / 2}.get(align, 0.0)
            cov = dashed_polyline_coverage(self._stroke_polylines(shape, tf, offset), w, pattern, clip.rect)
        elif geometry:
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
            self._fill(target, clip.restrict(cov), paints, tf, size, opacity, blend)

    def _side_strokes(self, sides: dict[str, Any], size: tuple[float, float], tf: Affine, clip: Clip) -> Coverage | None:
        w, h = size
        top, right = float(sides.get("top", 0)), float(sides.get("right", 0))
        bottom, left = float(sides.get("bottom", 0)), float(sides.get("left", 0))
        merged: Coverage | None = None
        for x, y, sw, sh in ((0, 0, w, top), (w - right, 0, right, h), (0, h - bottom, w, bottom), (0, 0, left, h)):
            if sw > 0 and sh > 0:
                merged = union(merged, RoundedRect(sw, sh).coverage(tf @ Affine.translate(x, y), clip.rect))
        return merged

    def _stroke_polylines(self, shape: Shape, tf: Affine, offset_px: float = 0.0) -> list[np.ndarray]:
        """Device-space outline polylines used for dash patterns.

        Figma dashes follow the shape's centerline; SDF bands have no arc-length
        parameterization, so dashed strokes are drawn from the flattened outline
        (closed for box/ellipse shapes, offset per strokeAlign) via polyline
        rasterization instead of the SDF band.
        """
        if isinstance(shape, (RoundedRect, Ellipse)):
            polys = shape._offset_polygons(tf, offset_px) if offset_px else shape.polygons(tf)
            return [np.vstack([poly, poly[:1]]) for poly in polys]
        if isinstance(shape, _LineShape):
            return [tf.apply_points(np.array([[0.0, 0.0], [shape.width, 0.0]]))]
        if isinstance(shape, PathShape):
            polys: list[np.ndarray] = []
            for subpaths, _rule in shape.paths:
                for sub, poly in zip(subpaths, _flatten_each(subpaths, tf)):
                    if sub and sub[-1][0] == "Z":
                        poly = np.vstack([poly, poly[:1]])
                    polys.append(poly)
            return polys
        return [poly for poly in shape.polygons(tf) if len(poly) >= 2]

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
        blend: str = "NORMAL",
    ) -> None:
        pieces = text_coverages(node, tf, size, clip.rect, self.fonts)
        for effect in effects:
            if effect.get("type") == "DROP_SHADOW":
                for cov, _fills in pieces:
                    self._drop_shadow(target, cov, effect, tf, clip)
        for cov, fills in pieces:
            self._fill(target, clip.restrict(cov), list(fills), tf, size, opacity, blend)

    # ── effects ──────────────────────────────────────────────────────────────

    def _layer_blur(
        self, target: np.ndarray, layer: np.ndarray, rect: Rect, radius_px: float, opacity: float, blend: str = "NORMAL"
    ) -> None:
        """Blur a node's own rendered layer and composite it back over the backdrop."""
        x0, y0, x1, y1 = rect
        region = layer[y0:y1, x0:x1]
        alpha = region[..., 3]
        if not alpha.any():
            return
        ys, xs = np.nonzero(alpha)
        pad = int(math.ceil(radius_px * 1.5)) + 2
        ry0, ry1 = max(0, int(ys.min()) - pad), min(region.shape[0], int(ys.max()) + 1 + pad)
        rx0, rx1 = max(0, int(xs.min()) - pad), min(region.shape[1], int(xs.max()) + 1 + pad)
        sub = _blur_region(np.ascontiguousarray(region[ry0:ry1, rx0:rx1]), radius_px)
        if opacity < 1.0:
            sub = sub * opacity
        dst = target[y0 + ry0 : y0 + ry1, x0 + rx0 : x0 + rx1]
        blend_composite(dst, sub, blend)

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


def _composite(target: np.ndarray, cov: Coverage, field: np.ndarray, mode: str = "NORMAL") -> None:
    region = target[cov.y0 : cov.y1, cov.x0 : cov.x1]
    if region.size == 0:
        return
    h, w = region.shape[:2]
    mask = cov.mask[:h, :w, None]
    if field.shape[0] != 1:
        field = field[:h, :w]
    src = field * mask
    blend_composite(region, src, mode)


def _composite_layer(target: np.ndarray, layer: np.ndarray, rect: Rect, opacity: float, mode: str = "NORMAL") -> None:
    x0, y0, x1, y1 = rect
    src = layer[y0:y1, x0:x1] * opacity
    blend_composite(target[y0:y1, x0:x1], src, mode)


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


def backdrop_blur(image: np.ndarray, rect: Rect, radius_px: float) -> np.ndarray:
    """Blurred RGB (float32) of `image` inside `rect`, sampling a margin around it.

    Wide blurs run on a block-averaged copy and are upsampled bilinearly: a
    Gaussian of sigma >= 3 low-res pixels has no detail the downsample loses,
    and it keeps per-frame glass blurs cheap at 3x device scale.
    """
    x0, y0, x1, y1 = rect
    sigma = radius_px / 2.0
    pad = int(math.ceil(sigma * 3))
    h, w = image.shape[:2]
    sx0, sy0, sx1, sy1 = max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)
    src = image[sy0:sy1, sx0:sx1, :3].astype(np.float32)
    factor = max(1, min(8, int(sigma // 3)))
    if factor == 1:
        blurred = np.stack([gaussian_blur(src[..., c], sigma) for c in range(3)], axis=-1)
    else:
        sh, sw = src.shape[:2]
        padded = np.pad(src, ((0, (-sh) % factor), (0, (-sw) % factor), (0, 0)), mode="edge")
        small = padded.reshape(padded.shape[0] // factor, factor, padded.shape[1] // factor, factor, 3).mean(axis=(1, 3))
        small = np.stack([gaussian_blur(small[..., c], sigma / factor) for c in range(3)], axis=-1)
        blurred = _upsample_axis(_upsample_axis(small, factor, 0), factor, 1)[:sh, :sw]
    return blurred[y0 - sy0 : y1 - sy0, x0 - sx0 : x1 - sx0]


def _upsample_axis(arr: np.ndarray, factor: int, axis: int) -> np.ndarray:
    n = arr.shape[axis]
    pos = np.clip((np.arange(n * factor) + 0.5) / factor - 0.5, 0.0, n - 1)
    lo = np.floor(pos).astype(np.intp)
    hi = np.minimum(lo + 1, n - 1)
    shape = [1] * arr.ndim
    shape[axis] = -1
    frac = (pos - lo).astype(np.float32).reshape(shape)
    return np.take(arr, lo, axis=axis) * (1.0 - frac) + np.take(arr, hi, axis=axis) * frac


def _blur_region(region: np.ndarray, radius_px: float) -> np.ndarray:
    if radius_px <= 0.5:
        return region
    sigma = radius_px / 2.0
    return np.stack([gaussian_blur(np.ascontiguousarray(region[..., ch]), sigma) for ch in range(4)], axis=-1)


def render_frame(
    doc: FigmaDocument,
    frame_id: str,
    scale: float = 1.0,
    *,
    font_dirs: Iterable[str] = (),
    background: tuple[float, float, float, float] | None = None,
    skip_ids: Iterable[str] = (),
    only_ids: Iterable[str] | None = None,
    transparent: bool = False,
) -> np.ndarray:
    """Rasterize one top-level frame to an (H, W, 4) uint8 RGBA array."""
    return FigmaRenderer(doc, font_dirs=font_dirs).render(
        frame_id, scale, background=background, skip_ids=skip_ids, only_ids=only_ids, transparent=transparent
    )
