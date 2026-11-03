from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from .geometry import Affine
from .smart_animate import LayerGeometry

_FADES = frozenset({"DISSOLVE", "SMART_ANIMATE", "SCROLL_ANIMATE"})
_SLIDES = frozenset({"PUSH", "MOVE_IN", "MOVE_OUT", "SLIDE_IN", "SLIDE_OUT"})
_OPPOSITE = {"LEFT": "RIGHT", "RIGHT": "LEFT", "TOP": "BOTTOM", "BOTTOM": "TOP"}
_REVERSED_KIND = {"MOVE_IN": "MOVE_OUT", "MOVE_OUT": "MOVE_IN", "SLIDE_IN": "SLIDE_OUT", "SLIDE_OUT": "SLIDE_IN"}


def ease(name: str, t: float) -> float:
    t = min(1.0, max(0.0, t))
    if name == "LINEAR":
        return t
    if name in {"EASE_IN", "EASE_IN_BACK"}:
        return t * t * t
    if name in {"EASE_IN_AND_OUT", "EASE_IN_AND_OUT_BACK", "CUSTOM_CUBIC_BEZIER"}:
        return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2
    return 1 - (1 - t) ** 3


@dataclass
class Transition:
    kind: str
    direction: str
    duration: float
    easing: str
    source: np.ndarray
    target: np.ndarray
    elapsed: float = 0.0

    @classmethod
    def from_figma(cls, spec: dict[str, Any] | None, source: np.ndarray, target: np.ndarray, *, reverse: bool = False) -> "Transition | None":
        if not spec:
            return None
        kind = str(spec.get("type", "INSTANT"))
        duration = float(spec.get("duration", 0.0) or 0.0)
        if duration <= 0 or (kind not in _FADES and kind not in _SLIDES):
            return None
        direction = str(spec.get("direction", "LEFT"))
        if reverse:
            direction = _OPPOSITE.get(direction, direction)
            kind = _REVERSED_KIND.get(kind, kind)
        easing = str((spec.get("easing") or {}).get("type", "EASE_OUT"))
        return cls(kind, direction, duration, easing, source, target)

    def restore(self) -> None:
        """Undo any document mutations this transition made (no-op by default)."""

    @property
    def done(self) -> bool:
        return self.elapsed >= self.duration

    def advance(self, dt: float) -> None:
        self.elapsed = min(self.duration, self.elapsed + max(0.0, float(dt)))

    def frame(self) -> np.ndarray:
        p = ease(self.easing, self.elapsed / self.duration)
        if self.kind in _FADES:
            mixed = self.source.astype(np.float32) * (1 - p) + self.target.astype(np.float32) * p
            return np.rint(mixed).astype(np.uint8)
        h, w = self.target.shape[:2]
        horizontal = self.direction in {"LEFT", "RIGHT"}
        extent = w if horizontal else h
        sign = -1 if self.direction in {"LEFT", "TOP"} else 1
        travel = int(round(extent * p))
        incoming = -sign * (extent - travel)
        out = self.source.copy()
        if self.kind in {"MOVE_OUT", "SLIDE_OUT"}:
            out[...] = self.target
            _paste_shifted(out, self.source, sign * travel, horizontal)
            return out
        if self.kind == "PUSH":
            out[...] = 0
            out[..., 3] = 255
            _paste_shifted(out, self.source, sign * travel, horizontal)
        _paste_shifted(out, self.target, incoming, horizontal)
        return out


def _paste_shifted(dst: np.ndarray, src: np.ndarray, offset: int, horizontal: bool) -> None:
    n = src.shape[1] if horizontal else src.shape[0]
    lo, hi = max(0, offset), min(n, n + offset)
    if hi <= lo:
        return
    if horizontal:
        dst[:, lo:hi] = src[:, lo - offset : hi - offset]
    else:
        dst[lo:hi] = src[lo - offset : hi - offset]


_MISSING = object()


@dataclass
class TweenLayer:
    """A matched layer whose node data is rewritten to interpolated geometry each tick.

    `render` rasterizes the layer's subtree with its current (mutated) state as
    straight-alpha RGBA; `paste_x`/`paste_y` place that raster on the matrix.
    Parent clipping contexts are not reapplied, so a matched layer renders
    unclipped for the duration of the transition.
    """

    node: dict[str, Any]
    parent_inv: Affine
    src: LayerGeometry
    dst: LayerGeometry
    render: Callable[[], np.ndarray]
    paste_x: int
    paste_y: int
    _saved: dict[str, Any] | None = None

    def apply(self, p: float) -> None:
        geometry = self.src.lerp(self.dst, p)
        if self._saved is None:
            keys = ("relativeTransform", "size", "opacity", "rectangleCornerRadii")
            self._saved = {key: self.node.get(key, _MISSING) for key in keys}
        rel = self.parent_inv @ Affine(*geometry.matrix)
        self.node["relativeTransform"] = [[rel.a, rel.c, rel.tx], [rel.b, rel.d, rel.ty]]
        self.node["size"] = {"x": geometry.width, "y": geometry.height}
        self.node["opacity"] = geometry.opacity
        self.node["rectangleCornerRadii"] = list(geometry.radii)

    def restore(self) -> None:
        if self._saved is None:
            return
        for key, value in self._saved.items():
            if value is _MISSING:
                self.node.pop(key, None)
            else:
                self.node[key] = value
        self._saved = None


@dataclass
class SmartAnimateTransition:
    """SMART_ANIMATE as per-layer tweening over the matched-layer-free target."""

    duration: float
    easing: str
    base: np.ndarray
    layers: list[TweenLayer]
    elapsed: float = 0.0

    @property
    def done(self) -> bool:
        return self.elapsed >= self.duration

    def advance(self, dt: float) -> None:
        self.elapsed = min(self.duration, self.elapsed + max(0.0, float(dt)))

    def restore(self) -> None:
        for layer in self.layers:
            layer.restore()

    def frame(self) -> np.ndarray:
        p = ease(self.easing, self.elapsed / self.duration)
        out = self.base.copy()
        for layer in self.layers:
            layer.apply(p)
            _paste_layer(out, layer.render(), layer.paste_x, layer.paste_y)
        return out


def _paste_layer(out: np.ndarray, raster: np.ndarray, x: int, y: int) -> None:
    h, w = raster.shape[:2]
    height, width = out.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    src = raster[y0 - y : y1 - y, x0 - x : x1 - x].astype(np.float32)
    dst = out[y0:y1, x0:x1]
    alpha = src[..., 3:4] / 255.0
    dst[..., :3] = np.rint(src[..., :3] * alpha + dst[..., :3].astype(np.float32) * (1 - alpha)).astype(np.uint8)
