"""Layer matching for SMART_ANIMATE prototype transitions.

Layers match by name (falling back to id) when both are visible and share a
node type. Matching recurses into matched pairs, so the deepest matched
subtrees are what actually tween; a matched pair with no matched children is
emitted as one tweened unit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

from .document import TRANSPARENT_CONTAINERS, Frame, is_visible, node_size, node_transform
from .geometry import Affine
from .render import corner_radii


@dataclass(frozen=True)
class LayerPair:
    source_id: str
    target_id: str


@dataclass(frozen=True)
class LayerGeometry:
    """Rendered state of one layer: frame-local transform, size, opacity, radii."""

    matrix: tuple[float, float, float, float, float, float]
    width: float
    height: float
    opacity: float
    radii: tuple[float, float, float, float]

    def differs(self, other: "LayerGeometry", tol: float = 1e-3) -> bool:
        return (
            any(abs(s - o) > tol for s, o in zip(self.matrix, other.matrix))
            or abs(self.width - other.width) > tol
            or abs(self.height - other.height) > tol
            or abs(self.opacity - other.opacity) > tol
            or any(abs(s - o) > tol for s, o in zip(self.radii, other.radii))
        )

    def lerp(self, other: "LayerGeometry", p: float) -> "LayerGeometry":
        def mix(a: float, b: float) -> float:
            return a + (b - a) * p

        return LayerGeometry(
            matrix=tuple(mix(s, o) for s, o in zip(self.matrix, other.matrix)),  # type: ignore[arg-type]
            width=mix(self.width, other.width),
            height=mix(self.height, other.height),
            opacity=mix(self.opacity, other.opacity),
            radii=tuple(mix(s, o) for s, o in zip(self.radii, other.radii)),  # type: ignore[arg-type]
        )


def walk_with_parent(frame: Frame) -> Iterator[tuple[dict[str, Any], Affine, Affine]]:
    """Yield (node, frame-local transform, parent frame-local transform) in paint order."""

    def rec(node: dict[str, Any], container: Affine) -> Iterator[tuple[dict[str, Any], Affine, Affine]]:
        for child in node.get("children") or ():
            if not isinstance(child, dict) or not is_visible(child):
                continue
            tf = node_transform(child, container, frame)
            yield child, tf, container
            child_container = container if child.get("type") in TRANSPARENT_CONTAINERS else tf
            yield from rec(child, child_container)

    yield from rec(frame.node, Affine.identity())


def match_layers(source: Frame, target: Frame) -> list[LayerPair]:
    pairs: list[LayerPair] = []
    _match_children(source.node, target.node, pairs)
    return pairs


def _match_children(src_parent: dict[str, Any], dst_parent: dict[str, Any], out: list[LayerPair]) -> None:
    by_name: dict[str, dict[str, Any]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for child in dst_parent.get("children") or ():
        if isinstance(child, dict) and is_visible(child):
            by_name.setdefault(str(child.get("name", "")), child)
            by_id.setdefault(str(child.get("id", "")), child)
    for child in src_parent.get("children") or ():
        if not isinstance(child, dict) or not is_visible(child):
            continue
        match = by_name.get(str(child.get("name", ""))) or by_id.get(str(child.get("id", "")))
        if match is None or match.get("type") != child.get("type"):
            continue
        inner: list[LayerPair] = []
        _match_children(child, match, inner)
        if inner:
            out.extend(inner)
        else:
            out.append(LayerPair(str(child.get("id", "")), str(match.get("id", ""))))


def layer_geometry(node: dict[str, Any], tf: Affine) -> LayerGeometry:
    width, height = node_size(node)
    return LayerGeometry(
        matrix=(tf.a, tf.b, tf.c, tf.d, tf.tx, tf.ty),
        width=width,
        height=height,
        opacity=float(node.get("opacity", 1.0)),
        radii=tuple(float(r) for r in corner_radii(node)),
    )