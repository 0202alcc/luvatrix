"""Compile CDP DOMSnapshot captures into luvatrix-renderable Figma files.

Two layers live here:

- The pure snapshot-to-Figma compiler (`compile_snapshots`), fully unit-testable
  with canned DOMSnapshot payloads in the wire format Chrome emits.
- The capture orchestrator (`capture_design`), which drives the browser through
  `cdp.py`, downloads subresources, and writes the same on-disk layout as
  `luvatrix figma pull`: `figma_file.json`, `images/`, plus `clickables.json`
  and `capture_report.json`.

Browser/CDP imports stay lazy: importing this module must not require Chrome or
the `capture` extra.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from hashlib import sha1
import json
import math
from pathlib import Path
import re
from typing import Any

from .cdp import STYLE_PROPS
from .geometry import Affine, PathError, Segment, parse_path

DEFAULT_VIEWPORT = (393, 852, 3.0)
SVG_MAX_SHAPES = 24
_SVG_SHAPE_TAGS = frozenset({"path", "rect", "circle", "ellipse", "line", "polygon", "polyline"})
_SVG_COMPLEX_TAGS = frozenset(
    {"image", "text", "filter", "foreignobject", "use", "mask", "clippath", "lineargradient", "radialgradient", "pattern"}
)
INLINE_DISPLAYS = frozenset(
    {"inline", "inline-block", "inline-flex", "inline-grid", "inline-table", "table-cell", "table-caption"}
)
TEXT_CONTAINER_TAGS = frozenset({"b", "i", "em", "strong", "span", "a", "small", "label", "code", "sub", "sup", "u", "s", "mark", "abbr", "cite", "q", "time"})
ZERO_AREA = 0.05

FetchImage = Callable[[str], bytes | None]
RasterizeSvg = Callable[[dict[str, float]], bytes | None]

# Injected into the page after each DOMSnapshot: DOMSnapshot never includes
# ::before / ::after boxes, so this walk collects their computed styles keyed
# by element-child path ("0.2.1" = ordinals among element children, "" = root).
# `parent` carries the anchor element's padding/border widths, which position
# static pseudo boxes at the content-box origin.
PSEUDO_SCAN_JS = """(() => {
  const PICK = ["content", "display", "position", "visibility", "top", "left", "right", "bottom",
    "width", "height", "background-color", "background-image", "color",
    "font-family", "font-size", "font-weight", "font-style", "line-height", "letter-spacing",
    "text-align", "text-transform", "text-decoration", "opacity", "transform", "box-shadow",
    "border-top-width", "border-top-style", "border-top-color",
    "border-right-width", "border-right-style", "border-right-color",
    "border-bottom-width", "border-bottom-style", "border-bottom-color",
    "border-left-width", "border-left-style", "border-left-color",
    "border-top-left-radius", "border-top-right-radius", "border-bottom-right-radius", "border-bottom-left-radius"];
  const PARENT_PICK = ["padding-top", "padding-right", "padding-bottom", "padding-left",
    "border-top-width", "border-right-width", "border-bottom-width", "border-left-width"];
  const root = document.documentElement;
  if (!root) return [];
  const out = [];
  const pathOf = (el) => {
    const parts = [];
    let n = el;
    while (n && n !== root) {
      let ordinal = 0;
      for (let s = n.previousElementSibling; s; s = s.previousElementSibling) ordinal += 1;
      parts.unshift(ordinal);
      n = n.parentElement;
    }
    return parts.join(".");
  };
  const pick = (cs, keys) => {
    const o = {};
    for (const key of keys) o[key] = cs.getPropertyValue(key);
    return o;
  };
  const walk = (el) => {
    const own = getComputedStyle(el);
    if (own.display !== "none" && own.visibility !== "hidden") {
      for (const name of ["::before", "::after"]) {
        const cs = getComputedStyle(el, name);
        const content = cs.content;
        if (content && content !== "none" && content !== "normal") {
          out.push({
            path: pathOf(el),
            tag: el.tagName.toLowerCase(),
            pseudo: name.slice(2),
            styles: pick(cs, PICK),
            parent: pick(own, PARENT_PICK),
          });
        }
      }
    }
    for (const child of el.children) walk(child);
  };
  walk(root);
  return out;
})()"""


class CaptureError(RuntimeError):
    pass


@dataclass
class CaptureResult:
    file: dict[str, Any]
    images: dict[str, dict[str, Any]] = field(default_factory=dict)
    clickables: list[dict[str, Any]] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)
    svg_raster: list[dict[str, Any]] = field(default_factory=list)


def _s(strings: list[str], value: Any) -> str:
    return strings[value] if isinstance(value, int) else str(value)


def _sparse_map(entry: Any) -> dict[int, str]:
    if not isinstance(entry, dict):
        return {}
    return {i: v for i, v in zip(entry.get("index", ()), entry.get("value", ()))}


class SnapshotModel:
    """Reads one DOMSnapshot document in the Chrome wire format."""

    def __init__(self, snapshot: dict[str, Any], props: Sequence[str] = STYLE_PROPS) -> None:
        documents = snapshot.get("documents") or []
        if not documents:
            raise CaptureError("DOMSnapshot payload has no documents")
        self.doc = documents[0]
        self.strings = snapshot.get("strings") or []
        raw_title = self.doc.get("title")
        self.title = _s(self.strings, raw_title) if isinstance(raw_title, int) else str(raw_title or "")
        nodes = self.doc.get("nodes") or {}
        self.parent: list[int] = list(nodes.get("parentIndex") or ())
        self.node_type: list[int] = list(nodes.get("nodeType") or ())
        self.tag: list[str] = [_s(self.strings, v) for v in nodes.get("nodeName") or ()]
        self.backend: list[int] = [int(b) for b in nodes.get("backendNodeId") or ()]
        self.attrs: list[dict[str, str]] = []
        for flat in nodes.get("attributes") or ():
            values = [_s(self.strings, v) for v in flat]
            self.attrs.append(dict(zip(values[0::2], values[1::2])))
        self.text_value = {i: _s(self.strings, v) for i, v in _sparse_map(nodes.get("textValue")).items()}
        self.input_value = {i: _s(self.strings, v) for i, v in _sparse_map(nodes.get("inputValue")).items()}
        self.clickable_nodes = set(_sparse_map(nodes.get("isClickable")))
        layout = self.doc.get("layout") or {}
        self.layout_of_node = {int(n): li for li, n in enumerate(layout.get("nodeIndex") or ())}
        self.bounds: list[list[float]] = [list(b) for b in layout.get("bounds") or ()]
        self.layout_text = [_s(self.strings, v) for v in layout.get("text") or ()]
        self.styles: dict[int, dict[str, str]] = {}
        for li, raw in enumerate(layout.get("styles") or ()):
            self.styles[li] = dict(zip(props, (_s(self.strings, v) for v in raw)))
        boxes = self.doc.get("textBoxes") or {}
        self.text_boxes: dict[int, list[dict[str, Any]]] = {}
        for li, bounds, start, length in zip(
            boxes.get("layoutIndex") or (),
            boxes.get("bounds") or (),
            boxes.get("start") or (),
            boxes.get("length") or (),
        ):
            self.text_boxes.setdefault(int(li), []).append(
                {"bounds": list(bounds), "start": int(start), "length": int(length)}
            )

    # ── node accessors ───────────────────────────────────────────────────────

    def children(self, node: int) -> list[int]:
        return [i for i, parent in enumerate(self.parent) if parent == node]

    def attr(self, node: int, name: str) -> str | None:
        return self.attrs[node].get(name) if node < len(self.attrs) else None

    def node_text(self, node: int) -> str:
        return self.text_value.get(node, "")

    def is_clickable(self, node: int) -> bool:
        return node in self.clickable_nodes

    # ── layout accessors ─────────────────────────────────────────────────────

    def layout_index(self, node: int) -> int | None:
        return self.layout_of_node.get(node)

    def box(self, node: int) -> list[float] | None:
        li = self.layout_index(node)
        return self.bounds[li] if li is not None and li < len(self.bounds) else None

    def style(self, node: int) -> dict[str, str]:
        li = self.layout_index(node)
        return self.styles.get(li, {}) if li is not None else {}


@dataclass
class _Run:
    """A stretch of text from one inline source element."""

    source: int
    text: str
    boxes: list[list[float]]
    top: int = -1


class _PageCompiler:
    """Compiles one captured page into a Figma frame node."""

    def __init__(
        self,
        model: SnapshotModel,
        *,
        page_index: int,
        path: str,
        fetcher: FetchImage | None,
        rasterize: RasterizeSvg | None,
        images: dict[str, dict[str, Any]] | None = None,
        pseudo_entries: Sequence[dict[str, Any]] | None = None,
    ) -> None:
        self.model = model
        self.page_index = page_index
        self.prefix = f"{page_index + 1}"
        self.path = path
        self.fetcher = fetcher
        self.rasterize = rasterize
        self.counts: dict[str, int] = {"frames": 0, "rectangles": 0, "texts": 0, "vectors": 0, "images": 0}
        self.skipped: dict[str, int] = {"hidden": 0, "zeroSize": 0, "noLayout": 0, "empty": 0}
        self.unsupported: dict[str, int] = {}
        self.selector_index: dict[str, list[int]] = {}
        self.origin = (0.0, 0.0)
        self.page_clickables: list[dict[str, Any]] = []
        self.images: dict[str, dict[str, Any]] = images if images is not None else {}
        self.image_failures: list[str] = []
        self.emitted: dict[str, dict[str, Any]] = {}
        self.svg_placeholders: list[tuple[dict[str, Any], dict[str, float]]] = []
        self.raster_queue: list[tuple[dict[str, Any], dict[str, float]]] = []
        self.pseudo_paths = self._node_paths()
        self.pseudo_by_node = self._group_pseudo_entries(pseudo_entries or ())
        self._fonts: Any = None

    def node_id(self, node: int) -> str:
        backend = self.model.backend[node] if node < len(self.model.backend) else node
        return f"{self.prefix}:{backend}"

    def skip(self, bucket: str, node: int = -1) -> None:
        self.skipped[bucket] = self.skipped.get(bucket, 0) + 1

    def unsupported_css(self, kind: str) -> None:
        self.unsupported[kind] = self.unsupported.get(kind, 0) + 1

    def register_selector(self, node: int) -> None:
        attrs = self.model.attrs[node] if node < len(self.model.attrs) else {}
        tag = self.model.tag[node].lower()
        keys = [f"[data-testid={attrs['data-testid']}]"] if attrs.get("data-testid") else []
        if attrs.get("id"):
            keys.append(f"#{attrs['id']}")
        classes = (attrs.get("class") or "").split()
        keys.extend(f"[data-test={attrs['data-test']}]" for _ in () if attrs.get("data-test"))
        keys.extend(f".{c}" for c in classes)
        if attrs.get("role"):
            keys.append(f"[role={attrs['role']}]")
        if attrs.get("onclick"):
            keys.append("[onclick]")
        if attrs.get("href"):
            keys.append(f"a[href={attrs['href']}]")
        keys.append(tag)
        for key in keys:
            self.selector_index.setdefault(key, []).append(node)

    # ── tree walk ────────────────────────────────────────────────────────────

    def build(self) -> dict[str, Any]:
        body = self._root_node()
        body_box = self.model.box(body) or [0, 0, 393, 852]
        self.origin = (body_box[0], body_box[1])
        styles = self.model.style(body)
        frame: dict[str, Any] = {
            "id": f"{self.prefix}:0",
            "type": "FRAME",
            "name": self.frame_name(),
            "absoluteBoundingBox": {
                "x": 0.0,
                "y": 0.0,
                "width": max(1.0, body_box[2]),
                "height": max(1.0, body_box[3]),
            },
            "fills": _solid_fills(styles.get("background-color"), self) or [solid_paint(1, 1, 1)],
            "clipsContent": True,
        }
        children = self.build_children(body)
        self._apply_scroll_and_fixed(frame, body, children)
        frame["children"] = children
        self.counts["frames"] += 1
        return frame

    def _root_node(self) -> int:
        for node, tag in enumerate(self.model.tag):
            if tag.upper() == "BODY" and self.model.layout_index(node) is not None:
                return node
        for node, tag in enumerate(self.model.tag):
            if tag.upper() == "HTML" and self.model.layout_index(node) is not None:
                return node
        return 0

    def frame_name(self) -> str:
        title = self.model.title.strip()
        if title:
            return title
        segment = [part for part in self.path.split("/") if part]
        if not segment:
            return "Home"
        return segment[-1].replace("-", " ").replace("_", " ").title()

    def build_children(self, node: int, inside_text: bool = False, parent_tf: Affine | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for child in self.model.children(node):
            out.extend(self.build_node(child, inside_text=inside_text, parent_tf=parent_tf))
        return out

    def build_node(self, node: int, inside_text: bool = False, parent_tf: Affine | None = None) -> list[dict[str, Any]]:
        if self.model.node_type[node] != 1:
            return []
        placement = self._resolve_placement(node, parent_tf)
        nodes = self._build_node_inner(node, inside_text, placement[2] if placement else None)
        nodes = self._with_pseudos(node, nodes, placement)
        if placement:
            self._apply_placement(placement, nodes)
        return nodes

    # ── 2D CSS transforms ────────────────────────────────────────────────────

    def _resolve_placement(
        self, node: int, parent_tf: Affine | None
    ) -> tuple[list[float], Affine, Affine, Affine | None, Affine] | None:
        """Placement for a node inside (possibly) transformed ancestor space.

        Returns (base_box, relativeTransform, page_tf, css_L, parent_tf) where
        base_box is the pre-transform border box in the parent's local space,
        relativeTransform maps node-local -> parent-local (renderer contract),
        and page_tf maps node-local -> frame-local for descendant placement.
        None when neither the node nor any ancestor carries a 2D transform.
        """
        box = self.model.box(node)
        if box is None or box[2] <= ZERO_AREA or box[3] <= ZERO_AREA:
            return None
        styles = self.model.style(node)
        if styles.get("visibility", "visible") == "hidden" or styles.get("display", "block") in {"none", "contents"}:
            return None
        raw = (styles.get("transform") or "none").strip().lower()
        css_l: Affine | None = None
        if raw not in {"", "none"}:
            if "matrix3d" in raw or "perspective" in raw:
                self.unsupported_css("transform3d")
            else:
                matrix = _parse_css_matrix(raw)
                if matrix is None:
                    self.unsupported_css("transform-parse")
                else:
                    a, b, c, d, e, f = matrix
                    if (a, b, c, d, e, f) != _IDENTITY_MATRIX:
                        ox, oy = _parse_css_origin(styles.get("transform-origin", ""), box)
                        css_l = Affine.translate(ox, oy) @ Affine(a, b, c, d, e, f) @ Affine.translate(-ox, -oy)
                        self.counts["transforms"] = self.counts.get("transforms", 0) + 1
        if css_l is None and parent_tf is None:
            return None
        sp = parent_tf if parent_tf is not None else Affine()
        fbox = [box[0] - self.origin[0], box[1] - self.origin[1], box[2], box[3]]
        linear = sp if css_l is None else sp @ css_l
        size = _solve_size_from_aabb(linear.a, linear.b, linear.c, linear.d, fbox[2], fbox[3])
        if size is None:
            # Singular system (e.g. a 45deg rotation): keep the node placed in
            # its parent's space but drop the rotation/skew rather than rendering
            # an oversized rotated AABB.
            if css_l is not None:
                self.unsupported_css("transform-aabb")
                self.counts["transforms"] = self.counts.get("transforms", 0) - 1
            css_l = None
            linear = sp
            size = _solve_size_from_aabb(linear.a, linear.b, linear.c, linear.d, fbox[2], fbox[3])
            if size is None:
                scale = linear.mean_scale
                size = (fbox[2] / scale, fbox[3] / scale)
            if parent_tf is None:
                return None
        width, height = size
        center = (fbox[0] + fbox[2] / 2.0, fbox[1] + fbox[3] / 2.0)
        local_center = css_l.apply(width / 2.0, height / 2.0) if css_l is not None else (width / 2.0, height / 2.0)
        base_x, base_y = sp.inverse().apply(*center)
        base = (base_x - local_center[0], base_y - local_center[1])
        mapping = css_l if css_l is not None else Affine()
        rel = Affine.translate(*base) @ mapping
        page_tf = sp @ Affine.translate(*base) @ mapping
        return ([base[0], base[1], width, height], rel, page_tf, css_l, sp)

    def _apply_placement(
        self, placement: tuple[list[float], Affine, Affine, Affine | None, Affine], nodes: list[dict[str, Any]]
    ) -> None:
        base_box, rel, _page_tf, css_l, sp = placement
        if len(nodes) == 1:
            self._decorate(nodes[0], base_box, rel)
            return
        # Multi-node emissions (text pieces, svg vectors): each piece keeps its
        # own captured AABB, re-based into the parent's transformed space with
        # the element's own CSS transform applied.
        for out in nodes:
            bbox = out.get("absoluteBoundingBox") or {}
            aabb = [float(bbox.get("x", 0.0)), float(bbox.get("y", 0.0)), float(bbox.get("width", 0.0)), float(bbox.get("height", 0.0))]
            linear = sp if css_l is None else sp @ css_l
            size = _solve_size_from_aabb(linear.a, linear.b, linear.c, linear.d, aabb[2], aabb[3])
            if size is None:
                scale = linear.mean_scale
                size = (aabb[2] / scale, aabb[3] / scale)
            center = (aabb[0] + aabb[2] / 2.0, aabb[1] + aabb[3] / 2.0)
            local_center = css_l.apply(size[0] / 2.0, size[1] / 2.0) if css_l is not None else (size[0] / 2.0, size[1] / 2.0)
            base_x, base_y = sp.inverse().apply(*center)
            piece_rel = Affine.translate(base_x - local_center[0], base_y - local_center[1]) @ (css_l or Affine())
            self._decorate(out, [base_x - local_center[0], base_y - local_center[1], size[0], size[1]], piece_rel)

    def _decorate(self, out: dict[str, Any], base_box: list[float], rel: Affine) -> None:
        out["size"] = {"x": base_box[2], "y": base_box[3]}
        out["relativeTransform"] = [[rel.a, rel.c, rel.tx], [rel.b, rel.d, rel.ty]]
        out["absoluteBoundingBox"] = {
            "x": base_box[0],
            "y": base_box[1],
            "width": base_box[2],
            "height": base_box[3],
        }

    def _with_pseudos(
        self,
        node: int,
        nodes: list[dict[str, Any]],
        placement: tuple[list[float], Affine, Affine, Affine | None, Affine] | None = None,
    ) -> list[dict[str, Any]]:
        """Attach ::before / ::after children around a node's own emission."""
        entries = self.pseudo_by_node.get(node)
        if not entries:
            return nodes
        box = self.model.box(node)
        styles = self.model.style(node)
        if (
            box is None
            or box[2] <= ZERO_AREA
            or box[3] <= ZERO_AREA
            or styles.get("visibility", "visible") == "hidden"
            or styles.get("display", "block") in {"none", "contents"}
        ):
            return nodes
        before: list[dict[str, Any]] = []
        after: list[dict[str, Any]] = []
        for raw in entries:
            built = self._pseudo_node(node, raw, box, placement)
            if built is not None:
                (before if raw.get("pseudo") == "before" else after).append(built)
        if not before and not after:
            return nodes
        if not nodes:
            return [self._pseudo_container(node, box, styles, before + after, placement)]
        if len(nodes) == 1 and nodes[0].get("type") == "FRAME":
            nodes[0]["children"] = before + (nodes[0].get("children") or []) + after
            return nodes
        if len(nodes) == 1 and nodes[0].get("type") == "RECTANGLE":
            nodes[0]["type"] = "FRAME"
            nodes[0]["clipsContent"] = False
            nodes[0]["children"] = before + after
            self.counts["rectangles"] -= 1
            self.counts["frames"] += 1
            return nodes
        return [self._pseudo_container(node, box, styles, before + nodes + after, placement)]

    def _pseudo_container(
        self,
        node: int,
        box: list[float],
        styles: dict[str, str],
        children: list[dict[str, Any]],
        placement: tuple[list[float], Affine, Affine, Affine | None, Affine] | None = None,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": f"{self.node_id(node)}:wrap",
            "type": "FRAME",
            "name": self.node_name(node),
            "absoluteBoundingBox": self.local_box(box),
            "clipsContent": False,
            "children": children,
        }
        if placement is not None:
            self._apply_placement(placement, [out])
        paint = _background_fills(styles, self, self.fetcher, box)
        if paint:
            out["fills"] = paint
        self._finalize_fills(out, box)
        border = _border_info(styles)
        if border:
            out.update(border)
        self.counts["frames"] += 1
        return out

    def _pseudo_node(
        self,
        node: int,
        raw: dict[str, Any],
        box: list[float],
        placement: tuple[list[float], Affine, Affine, Affine | None, Affine] | None = None,
    ) -> dict[str, Any] | None:
        st: dict[str, str] = raw.get("styles") or {}
        if st.get("display", "inline") == "none":
            return None
        if st.get("visibility", "visible") == "hidden" or _number(st.get("opacity", "1"), 1.0) <= 0.0:
            return None
        content = _pseudo_content(st.get("content", "none"))
        if content is _PSEUDO_UNSUPPORTED:
            self.unsupported_css("pseudo-counter")
            return None
        bg = _background_fills(st, self, self.fetcher, box)
        border = _border_info(st)
        font_size = _length(st.get("font-size", "16px")) or 16.0
        width, height = _pseudo_size(st, content, font_size, box)
        if content is None and not bg and border is None:
            return None
        if width <= ZERO_AREA or height <= ZERO_AREA:
            self.unsupported_css("pseudo-auto-size")
            return None
        x, y = _pseudo_origin(raw, st, box, width, height)
        pseudo_box = [x, y, width, height]
        emitted = self._pseudo_emitted_box(pseudo_box, box, placement)
        suffix = "before" if raw.get("pseudo") == "before" else "after"
        if st.get("transform", "none") != "none":
            self.unsupported_css("pseudo-transform")
        if content and not bg and border is None:
            out = self._pseudo_text_node(
                st, content, emitted, f"{self.node_id(node)}:{suffix}", f"{self.node_name(node)}::{suffix}"
            )
        elif content:
            frame: dict[str, Any] = {
                "id": f"{self.node_id(node)}:{suffix}",
                "type": "FRAME",
                "name": f"{self.node_name(node)}::{suffix}",
                "absoluteBoundingBox": emitted,
                "clipsContent": False,
                "fills": bg,
            }
            if border:
                frame.update(border)
            radius = _corner_radii(st, pseudo_box)
            if radius:
                frame.update(radius)
            effects = _effects(st, self)
            if effects:
                frame["effects"] = effects
            self._finalize_fills(frame, box)
            line_height = _length(st.get("line-height", ""), font_size) or font_size * 1.21
            text_w = min(width, max(font_size * 0.62 * len(content), 1.0))
            text_local = [(width - text_w) / 2, (height - line_height) / 2, text_w, line_height]
            if placement is None:
                text_emitted = {
                    "x": x + text_local[0] + box[0] - self.origin[0],
                    "y": y + text_local[1] + box[1] - self.origin[1],
                    "width": text_w,
                    "height": line_height,
                }
                text_rel = None
            else:
                text_emitted = {"x": text_local[0], "y": text_local[1], "width": text_w, "height": line_height}
                text_rel = Affine.translate(text_local[0], text_local[1])
            frame["children"] = [
                self._pseudo_text_node(
                    st,
                    content,
                    text_emitted,
                    f"{self.node_id(node)}:{suffix}:t1",
                    "label",
                    text_rel,
                )
            ]
            out = frame
            self.counts["frames"] += 1
        else:
            out = {
                "id": f"{self.node_id(node)}:{suffix}",
                "type": "RECTANGLE",
                "name": f"{self.node_name(node)}::{suffix}",
                "absoluteBoundingBox": emitted,
                "fills": bg,
            }
            if border:
                out.update(border)
            radius = _corner_radii(st, pseudo_box)
            if radius:
                out.update(radius)
            effects = _effects(st, self)
            if effects:
                out["effects"] = effects
            self._finalize_fills(out, box)
            self.counts["rectangles"] += 1
        if placement is not None:
            self._decorate(out, list(pseudo_box), Affine.translate(pseudo_box[0], pseudo_box[1]))
        self.counts["pseudos"] = self.counts.get("pseudos", 0) + 1
        return out

    def _pseudo_emitted_box(
        self,
        pseudo_box: list[float],
        box: list[float],
        placement: tuple[list[float], Affine, Affine, Affine | None, Affine] | None,
    ) -> dict[str, float]:
        if placement is not None:
            return {"x": pseudo_box[0], "y": pseudo_box[1], "width": pseudo_box[2], "height": pseudo_box[3]}
        return {
            "x": pseudo_box[0] + box[0] - self.origin[0],
            "y": pseudo_box[1] + box[1] - self.origin[1],
            "width": pseudo_box[2],
            "height": pseudo_box[3],
        }

    def _pseudo_text_node(
        self,
        st: dict[str, str],
        content: str,
        emitted: dict[str, float],
        node_id: str,
        name: str,
        rel: Affine | None = None,
    ) -> dict[str, Any]:
        self.counts["texts"] += 1
        out: dict[str, Any] = {
            "id": node_id,
            "type": "TEXT",
            "name": name,
            "absoluteBoundingBox": emitted,
            "characters": content,
            "style": _text_style(st),
            "fills": _solid_fills(st.get("color"), self) or [solid_paint(0, 0, 0)],
        }
        if rel is not None:
            out["size"] = {"x": emitted["width"], "y": emitted["height"]}
            out["relativeTransform"] = [[rel.a, rel.c, rel.tx], [rel.b, rel.d, rel.ty]]
        return out

    def _group_pseudo_entries(self, entries: Sequence[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
        grouped: dict[int, list[dict[str, Any]]] = {}
        for raw in entries:
            node = self.pseudo_paths.get(str(raw.get("path", "")))
            if node is None or self.model.tag[node].lower() != str(raw.get("tag", "")).lower():
                self.unsupported_css("pseudo-unmatched")
                continue
            grouped.setdefault(node, []).append(raw)
        return grouped

    def _node_paths(self) -> dict[str, int]:
        """Map element-child ordinal paths ("" = root) to snapshot node indexes."""
        paths: dict[str, int] = {}
        root = self._html_root()

        def walk(node: int, path: str) -> None:
            paths[path] = node
            ordinal = 0
            for child in self.model.children(node):
                if self.model.node_type[child] != 1:
                    continue
                walk(child, f"{path}.{ordinal}" if path else str(ordinal))
                ordinal += 1

        walk(root, "")
        return paths

    def _html_root(self) -> int:
        for node, tag in enumerate(self.model.tag):
            if tag.upper() == "HTML" and self.model.node_type[node] == 1:
                return node
        return self._root_node()

    def _build_node_inner(self, node: int, inside_text: bool = False, parent_tf: Affine | None = None) -> list[dict[str, Any]]:
        model = self.model
        if model.node_type[node] != 1:
            return []
        box = model.box(node)
        if box is None:
            self.skip("noLayout", node)
            return []
        styles = model.style(node)
        if styles.get("visibility", "visible") == "hidden":
            self.skip("hidden", node)
            return []
        if styles.get("display", "block") in {"none", "contents"}:
            self.skip("hidden", node)
            return []
        tag = model.tag[node].lower()
        if inside_text and styles.get("display", "inline") in INLINE_DISPLAYS and not self._inline_is_own_node(node):
            return []
        if box[2] <= ZERO_AREA or box[3] <= ZERO_AREA:
            self.skip("zeroSize", node)
            return []
        if tag == "svg":
            return self.svg_nodes(node, box, styles)
        allow_reflow = parent_tf is None and (styles.get("transform") or "none").strip().lower() in {"", "none"}
        runs = self.text_runs(node)
        if tag in {"input", "textarea"} and not runs:
            value = model.input_value.get(node) or model.attr(node, "value") or ""
            if value.strip():
                runs = [_Run(node, value, [])]
        paint = _image_fill_for_img(self, node) if tag == "img" else []
        if not paint:
            paint = _background_fills(styles, self, self.fetcher, box)
        has_border = _border_info(styles) is not None
        has_shadow = styles.get("box-shadow", "none") != "none"
        keep_leaf = tag == "img"
        element_children = [
            c
            for c in model.children(node)
            if model.node_type[c] == 1 and model.layout_index(c) is not None and model.style(c).get("display", "inline") not in {"none"}
        ]
        if runs and all(model.style(c).get("display", "inline") in INLINE_DISPLAYS for c in element_children):
            wrapped = paint or has_border or has_shadow or self._is_interactive(node)
            sequence = self._text_container_sequence(node, element_children, wrapped, runs, parent_tf, allow_reflow)
            if wrapped:
                return [self.box_node(node, box, styles, sequence, paint, [], allow_reflow=allow_reflow)]
            if len(sequence) == 1:
                self._register_node(node, sequence[0])
            return sequence
        children = self.build_children(node, inside_text=bool(runs), parent_tf=parent_tf)
        if children or paint or has_border or has_shadow or keep_leaf:
            return [self.box_node(node, box, styles, children, paint, runs, allow_reflow=allow_reflow)]
        if runs:
            return [self.text_node(node, box, styles, runs, allow_reflow=allow_reflow)]
        self.skip("empty", node)
        return []

    def _text_container_sequence(
        self,
        node: int,
        element_children: list[int],
        wrapped: bool,
        runs: list[_Run],
        parent_tf: Affine | None = None,
        allow_reflow: bool = True,
    ) -> list[dict[str, Any]]:
        """Interleave text chunks and own-node inline children in DOM order."""
        own: dict[int, list[dict[str, Any]]] = {}
        for child in element_children:
            if self._inline_is_own_node(child):
                own[child] = self.build_node(child, inside_text=False, parent_tf=parent_tf)
        pieces: list[tuple[str, Any]] = []
        pending: list[_Run] = []
        run_index = 0
        for child in self.model.children(node):
            while run_index < len(runs) and runs[run_index].top <= child and (runs[run_index].top < child or child in own):
                pending.append(runs[run_index])
                run_index += 1
            if child in own:
                if pending:
                    pieces.append(("text", pending))
                    pending = []
                pieces.append(("nodes", own[child]))
        pending.extend(runs[run_index:])
        if pending:
            pieces.append(("text", pending))
        box = self.model.box(node) or [0, 0, 0, 0]
        styles = self.model.style(node)
        suffix = wrapped or sum(1 for kind, _payload in pieces if kind == "text") > 1
        result: list[dict[str, Any]] = []
        chunk_index = 0
        for kind, payload in pieces:
            if kind == "nodes":
                result.extend(payload)
                continue
            chunk_index += 1
            node_id = f"{self.node_id(node)}:t{chunk_index}" if suffix else self.node_id(node)
            result.append(self.text_node(node, box, styles, payload, node_id=node_id, register=False, allow_reflow=allow_reflow))
        return result

    def box_node(
        self,
        node: int,
        box: list[float],
        styles: dict[str, str],
        children: list[dict[str, Any]],
        paint: list[dict[str, Any]],
        runs: list[_Run],
        allow_reflow: bool = True,
    ) -> dict[str, Any]:
        model = self.model
        tag = model.tag[node].lower()
        name = self.node_name(node)
        out: dict[str, Any] = {
            "id": self.node_id(node),
            "type": "FRAME" if children else "RECTANGLE",
            "name": name,
            "absoluteBoundingBox": self.local_box(box),
        }
        if paint:
            out["fills"] = paint
        border = _border_info(styles)
        if border:
            out.update(border)
        effects = _effects(styles, self)
        if effects:
            out["effects"] = effects
        radius = _corner_radii(styles, box)
        if radius:
            out.update(radius)
        opacity = _opacity(styles)
        if opacity is not None:
            out["opacity"] = opacity
        blend = _blend_mode(styles)
        if blend:
            out["blendMode"] = blend
        if children:
            out["clipsContent"] = True
            self._apply_scroll_and_fixed(out, node, children)
            out["children"] = children
        if runs:
            if children:
                out.setdefault("children", [])
                out["children"].append(
                    self.text_node(node, box, styles, runs, node_id=f"{out['id']}:t1", register=False, allow_reflow=allow_reflow)
                )
            else:
                out["type"] = "FRAME"
                out["children"] = [
                    self.text_node(node, box, styles, runs, node_id=f"{out['id']}:t1", register=False, allow_reflow=allow_reflow)
                ]
        self.counts["frames" if out["type"] == "FRAME" else "rectangles"] += 1
        self._finalize_fills(out, box)
        self._register_node(node, out)
        return out

    def _finalize_fills(self, out: dict[str, Any], box: list[float]) -> None:
        """Resolve CONIC_RASTER marker paints into image fills or placeholders."""
        fills = out.get("fills") or []
        if not any(paint.get("type") == "CONIC_RASTER" for paint in fills):
            return
        clip = {"x": box[0], "y": box[1], "width": box[2], "height": box[3]}
        resolved: list[dict[str, Any]] = []
        for paint in fills:
            if paint.get("type") != "CONIC_RASTER":
                resolved.append(paint)
                continue
            data = self.rasterize(clip) if self.rasterize is not None else None
            if data:
                ref = "conic-" + sha1(f"{self.path}:{out['id']}".encode("utf-8")).hexdigest()[:12]
                self.images[ref] = {"url": f"rasterized:{out['id']}", "data": data}
                resolved.append({"type": "IMAGE", "imageRef": ref, "scaleMode": "FILL"})
                self.counts["images"] += 1
            else:
                out["fills"] = resolved + [{"type": "SOLID", "color": {"r": 0.85, "g": 0.85, "b": 0.85, "a": 1.0}}]
                self.raster_queue.append((out, clip))
                self.counts["conicRaster"] = self.counts.get("conicRaster", 0) + 1
                return
        out["fills"] = resolved

    def _register_node(self, node: int, out: dict[str, Any]) -> None:
        if self._is_interactive(node):
            self.clickable_entry(node, out)
        attrs = self.model.attrs[node] if node < len(self.model.attrs) else {}
        if self._is_interactive(node) or attrs.get("id") or attrs.get("data-testid") or attrs.get("role") or attrs.get("onclick"):
            self.register_selector(node)
        self.emitted[self.node_id(node)] = out

    def node_name(self, node: int) -> str:
        model = self.model
        attrs = model.attrs[node] if node < len(model.attrs) else {}
        label = attrs.get("aria-label") or attrs.get("alt")
        if label:
            return label
        tag = model.tag[node].lower()
        classes = (attrs.get("class") or "").split()
        suffix = f".{classes[0]}" if classes else ""
        return f"{tag}{suffix}"

    def clickable_entry(self, node: int, figma_node: dict[str, Any]) -> None:
        attrs = self.model.attrs[node] if node < len(self.model.attrs) else {}
        name = self.text_of_subtree(node) or attrs.get("aria-label") or self.model.tag[node].lower()
        box = self.local_box(self.model.box(node) or [0, 0, 0, 0])
        self.page_clickables.append(
            {
                "nodeId": figma_node["id"],
                "name": name,
                "selector": self.best_selector(node),
                "page": self.path,
                "x": box["x"] + box["width"] / 2,
                "y": box["y"] + box["height"] / 2,
                "width": box["width"],
                "height": box["height"],
            }
        )

    def best_selector(self, node: int) -> str:
        attrs = self.model.attrs[node] if node < len(self.model.attrs) else {}
        if attrs.get("data-testid"):
            return f"[data-testid={attrs['data-testid']}]"
        if attrs.get("id"):
            return f"#{attrs['id']}"
        classes = (attrs.get("class") or "").split()
        if classes:
            return f"{self.model.tag[node].lower()}.{classes[0]}"
        if attrs.get("href"):
            return f"a[href={attrs['href']}]"
        return self.model.tag[node].lower()

    def _is_interactive(self, node: int) -> bool:
        model = self.model
        tag = model.tag[node].lower()
        attrs = model.attrs[node] if node < len(model.attrs) else {}
        return (
            tag in {"a", "button", "select", "textarea"}
            or tag == "input"
            or bool(attrs.get("onclick"))
            or attrs.get("role", "").lower() == "button"
            or model.is_clickable(node)
        )

    def text_of_subtree(self, node: int) -> str:
        return " ".join(
            part for part in (self.model.node_text(c).strip() for c in self.model.children(node)) if part
        )

    # ── text ─────────────────────────────────────────────────────────────────

    def text_runs(self, node: int, top: int = -1, following: bool = False) -> list[_Run]:
        runs: list[_Run] = []
        siblings = self.model.children(node)
        for position, child in enumerate(siblings):
            child_following = following or self._has_following_inline_content(siblings, position)
            kind = self.model.node_type[child]
            if kind == 3:
                li = self.model.layout_index(child)
                text = ""
                if li is not None and li < len(self.model.layout_text):
                    text = self.model.layout_text[li]
                if not text:
                    text = self.model.node_text(child)
                if not text.strip():
                    if text and child_following:
                        runs.append(_Run(node, " ", [], top))
                    continue
                boxes = [entry["bounds"] for entry in self.model.text_boxes.get(li, ())] if li is not None else []
                runs.append(_Run(node, text, boxes, top))
            elif kind == 1:
                styles = self.model.style(child)
                if self.model.box(child) is None:
                    continue
                if styles.get("display", "inline") not in INLINE_DISPLAYS:
                    continue
                if self.model.tag[child].lower() == "br":
                    runs.append(_Run(node, "\n", [], top))
                elif self._inline_is_own_node(child):
                    continue
                else:
                    runs.extend(self.text_runs(child, top if top >= 0 else child, child_following))
        return runs

    def _has_following_inline_content(self, siblings: list[int], position: int) -> bool:
        for sibling in siblings[position + 1 :]:
            kind = self.model.node_type[sibling]
            if kind == 3:
                text = self.model.node_text(sibling)
                if text.strip():
                    return True
                continue
            if kind != 1:
                continue
            styles = self.model.style(sibling)
            if self.model.box(sibling) is None:
                continue
            if styles.get("display", "inline") not in INLINE_DISPLAYS:
                return False
            return True
        return False

    def _inline_is_own_node(self, node: int) -> bool:
        styles = self.model.style(node)
        tag = self.model.tag[node].lower()
        return (
            styles.get("background-color", "rgba(0, 0, 0, 0)") not in {"rgba(0, 0, 0, 0)", "transparent"}
            or styles.get("background-image", "none") != "none"
            or _border_info(styles) is not None
            or tag in {"img", "svg"}
            or self._is_interactive(node)
        )

    def text_node(
        self,
        node: int,
        box: list[float],
        styles: dict[str, str],
        runs: list[_Run],
        *,
        node_id: str | None = None,
        register: bool = True,
        allow_reflow: bool = True,
    ) -> dict[str, Any]:
        font_size = _length(styles.get("font-size", "16px")) or 16.0
        chars: list[str] = []
        run_of: list[int] = []
        previous_end: float | None = None
        for run_index, run in enumerate(runs):
            # <br> runs are exactly "\n"; keep them as hard breaks. Other
            # whitespace runs collapse to single spaces as before.
            collapsed = run.text if run.text == "\n" else re.sub(r"\s+", " ", run.text)
            if collapsed == " " and (not chars or chars[-1] == " " or chars[-1] == "\n"):
                continue
            if (
                collapsed
                and not collapsed.startswith(" ")
                and chars
                and chars[-1] not in {" ", "\n"}
                and run.boxes
                and previous_end is not None
                and min(b[0] for b in run.boxes) - previous_end > font_size * 0.25
            ):
                chars.append(" ")
                run_of.append(run_index)
            for ch in collapsed:
                chars.append(ch)
                run_of.append(run_index)
            if run.boxes:
                previous_end = max(b[0] + b[2] for b in run.boxes)
        start, end = 0, len(chars)
        while start < end and chars[start] in {" ", "\n"}:
            start += 1
        while end > start and chars[end - 1] in {" ", "\n"}:
            end -= 1
        characters = "".join(chars[start:end])
        run_of = run_of[start:end]
        base = _text_style(styles)
        reflowed = self._reflow_text(node, characters, run_of, runs, base, box, styles) if allow_reflow else None
        if reflowed is not None:
            characters, run_of, local, centered, overflow = reflowed
            if overflow:
                self.counts["textOverflow"] = self.counts.get("textOverflow", 0) + 1
        else:
            local, centered = self._text_box(runs, box, str(base.get("textAlignHorizontal", "LEFT")))
        if centered:
            base = dict(base, textAlignHorizontal="CENTER")
        table: dict[str, dict[str, Any]] = {}
        overrides: list[int] = []
        for ch_index, run_index in enumerate(run_of):
            key = 0
            if characters[ch_index : ch_index + 1] not in {"", " ", "\n"}:
                source = runs[run_index].source if run_index < len(runs) else node
                if source != node:
                    override = _style_override(self.model.style(source), styles, base)
                    if override:
                        key = self._table_key(table, override)
            overrides.append(key)
        out: dict[str, Any] = {
            "id": node_id or self.node_id(node),
            "type": "TEXT",
            "name": self.node_name(node),
            "absoluteBoundingBox": local,
            "characters": characters,
            "style": base,
            "fills": _solid_fills(styles.get("color"), self) or [solid_paint(0, 0, 0)],
        }
        if any(key for key in overrides):
            out["characterStyleOverrides"] = overrides
            out["styleOverrideTable"] = {str(k): v for k, v in table.items()}
        self.counts["texts"] += 1
        if register:
            self._register_node(node, out)
        return out

    def _font_library(self) -> Any | None:
        """The renderer's FontLibrary, loaded lazily; False marks "unavailable"."""
        if self._fonts is None:
            try:
                from .text import FontLibrary

                self._fonts: Any = FontLibrary()
            except Exception:
                self._fonts = False
        return self._fonts or None

    def _reflow_text(
        self,
        node: int,
        characters: str,
        run_of: list[int],
        runs: list[_Run],
        base: dict[str, Any],
        box: list[float],
        styles: dict[str, str],
    ) -> tuple[str, list[int], dict[str, float], bool, bool] | None:
        """Re-measure text with the renderer font and wrap to the captured box.

        Returns (characters, run_of, frame-local box, centered, overflow) or
        None when the renderer font cannot be loaded (caller keeps the old
        Chrome-drawn box behavior).
        """
        lib = self._font_library()
        if lib is None or not characters.strip():
            return None
        points = [bounds for run in runs for bounds in run.boxes]
        if not points:
            return None
        ux0 = min(p[0] for p in points)
        uy0 = min(p[1] for p in points)
        ux1 = max(p[0] + p[2] for p in points)
        uy1 = max(p[1] + p[3] for p in points)
        union_w, union_h = ux1 - ux0, uy1 - uy0
        available = max(box[2], 1.0)
        font_size = float(base.get("fontSize", 16.0) or 16.0)
        line_height = float(base.get("lineHeightPx", 0.0) or 0.0) or font_size * 1.21
        align = str(base.get("textAlignHorizontal", "LEFT"))
        centered = self._is_shrink_to_fit(runs)
        if centered:
            align = "CENTER"

        cache: dict[int, tuple[Any, float]] = {}

        def font_for(run_index: int) -> tuple[Any, float]:
            if run_index not in cache:
                cache[run_index] = self._run_font(lib, base, runs, run_index, styles, node)
            return cache[run_index]

        def measure(ch: str, run_index: int) -> float:
            if ch == "\n":
                return 0.0  # PIL cannot lay out newlines; breaks are handled structurally
            font, spacing = font_for(run_index)
            return float(font.getlength(ch)) + spacing

        total_w = sum(measure(ch, run_index) for ch, run_index in zip(characters, run_of))
        fills_box = union_w >= available - 4.0
        single_line = (not fills_box and total_w <= union_w * 1.12 + 2.0) or total_w <= available
        if single_line:
            width = max(total_w, union_w)
            if align == "RIGHT":
                x0 = ux1 - width
            elif align == "CENTER":
                x0 = (ux0 + ux1) / 2.0 - width / 2.0
            else:
                x0 = ux0
            overflow = width > available * 1.10
            return characters, run_of, self.local_box([x0, uy0, width, union_h]), centered, overflow

        # Greedy word wrap to the captured box width, honoring hard breaks.
        # Words keep their trailing space so rebuilt lines read naturally.
        all_lines: list[list[tuple[str, int]]] = []
        current: list[tuple[str, int]] = []
        current_w = 0.0
        word: list[tuple[str, int]] = []

        def flush_word() -> None:
            nonlocal current, current_w
            if not word:
                return
            word_w = sum(measure(ch, run_index) for ch, run_index in word)
            if current and current_w + word_w > available:
                all_lines.append(current)
                current, current_w = [], 0.0
            current.extend(word)
            current_w += word_w
            word.clear()

        for ch, run_index in zip(characters, run_of):
            if ch == "\n":
                flush_word()
                if current:
                    all_lines.append(current)
                    current, current_w = [], 0.0
                continue
            if ch == " ":
                word.append((ch, run_index))
                flush_word()
                continue
            word.append((ch, run_index))
        flush_word()
        if current:
            all_lines.append(current)

        if len(all_lines) <= 1 and all_lines:
            single = all_lines[0]
            rebuilt = "".join(ch for ch, _run_index in single)
            new_run_of = [run_index for _ch, run_index in single]
            width = max(total_w, union_w)
            if align == "RIGHT":
                x0 = ux1 - width
            elif align == "CENTER":
                x0 = (ux0 + ux1) / 2.0 - width / 2.0
            else:
                x0 = ux0
            return rebuilt, new_run_of, self.local_box([x0, uy0, width, union_h]), centered, width > available * 1.10

        new_chars: list[str] = []
        new_run_of: list[int] = []
        max_line_w = 0.0
        for line_index, line in enumerate(all_lines):
            if line_index:
                new_chars.append("\n")
                new_run_of.append(new_run_of[-1] if new_run_of else 0)
            line_w = 0.0
            for ch, run_index in line:
                new_chars.append(ch)
                new_run_of.append(run_index)
                line_w += measure(ch, run_index)
            max_line_w = max(max_line_w, line_w)
        width = max(available, max_line_w)
        height = max(union_h, len(all_lines) * line_height)
        if align == "RIGHT":
            x0 = ux1 - width
        elif align == "CENTER":
            x0 = (ux0 + ux1) / 2.0 - width / 2.0
        else:
            x0 = ux0
        overflow = max_line_w > available * 1.10
        return "".join(new_chars), new_run_of, self.local_box([x0, uy0, width, height]), centered, overflow

    def _run_font(
        self, lib: Any, base: dict[str, Any], runs: list[_Run], run_index: int, styles: dict[str, str], node: int
    ) -> tuple[Any, float]:
        """(PIL font, letter spacing) for one run, honoring span overrides."""
        family = str(base.get("fontFamily", "Inter") or "Inter")
        weight = float(base.get("fontWeight", 400.0) or 400.0)
        italic = bool(base.get("italic", False))
        size = float(base.get("fontSize", 16.0) or 16.0)
        spacing = float(base.get("letterSpacing", 0.0) or 0.0)
        source = runs[run_index].source if 0 <= run_index < len(runs) else -1
        if source >= 0 and source != node:
            override = _style_override(self.model.style(source), styles, base)
            family = str(override.get("fontFamily", family))
            weight = float(override.get("fontWeight", weight))
            italic = bool(override.get("italic", italic))
            size = float(override.get("fontSize", size))
            spacing = float(override.get("letterSpacing", spacing))
        path = lib.resolve(family, weight, italic) or lib.resolve("Inter", weight, italic)
        return lib.font(path, size), spacing

    def _is_shrink_to_fit(self, runs: list[_Run]) -> bool:
        by_source: dict[int, list[list[float]]] = {}
        for run in runs:
            by_source.setdefault(run.source, []).extend(run.boxes)
        shrink_sources = 0
        for source, source_boxes in by_source.items():
            source_box = self.model.box(source)
            if source_box is None or not source_boxes:
                continue
            sx0 = min(b[0] for b in source_boxes)
            sx1 = max(b[0] + b[2] for b in source_boxes)
            if source_box[2] - (sx1 - sx0) < 4.0:
                shrink_sources += 1
        return bool(shrink_sources) and shrink_sources == len(by_source)

    def _table_key(self, table: dict[str, dict[str, Any]], override: dict[str, Any]) -> int:
        for key, value in table.items():
            if value == override:
                return int(key)
        next_key = len(table) + 1
        table[str(next_key)] = override
        return next_key

    def _text_box(self, runs: list[_Run], box: list[float], align: str = "LEFT") -> tuple[dict[str, float], bool]:
        """Returns (frame-local box, whether the box was widened symmetrically)."""
        points = [bounds for run in runs for bounds in run.boxes]
        if not points:
            return self.local_box(box), False
        ux0 = min(p[0] for p in points)
        uy0 = min(p[1] for p in points)
        ux1 = max(p[0] + p[2] for p in points)
        uy1 = max(p[1] + p[3] for p in points)
        # Chrome measures text with the page font; the bundled renderer font can
        # be wider, so widen the box from the alignment anchor to avoid
        # re-wrapping while keeping the text visually anchored.
        slack = max(0.0, (ux1 - ux0) * 0.12)
        centered = False
        by_source: dict[int, list[list[float]]] = {}
        for run in runs:
            by_source.setdefault(run.source, []).extend(run.boxes)
        shrink_sources = 0
        for source, source_boxes in by_source.items():
            source_box = self.model.box(source)
            if source_box is None or not source_boxes:
                continue
            sx0 = min(b[0] for b in source_boxes)
            sx1 = max(b[0] + b[2] for b in source_boxes)
            if source_box[2] - (sx1 - sx0) < 4.0:
                shrink_sources += 1
        if shrink_sources and shrink_sources == len(by_source):
            # Shrink-to-fit text (badge, flex item): widen symmetrically.
            align = "CENTER"
            centered = True
        union_width = ux1 - ux0
        if align == "RIGHT":
            x0 = min(ux0 - slack, box[0])
            width = ux1 + slack - x0
        elif align == "CENTER":
            center = (ux0 + ux1) / 2
            # Keep widening bounded so wide boxes cannot push text past the
            # page edges; the union already spans where Chrome drew the text.
            width = max(union_width * 1.08, min(max(union_width + 2 * slack, box[2]), union_width * 1.12 + 8.0))
            x0 = center - width / 2
        else:
            x0 = ux0
            width = max(ux1 + slack, box[0] + box[2]) - x0
        return self.local_box([x0, uy0, width, uy1 - uy0]), centered

    # ── geometry helpers ─────────────────────────────────────────────────────

    def local_box(self, box: list[float]) -> dict[str, float]:
        return {
            "x": box[0] - self.origin[0],
            "y": box[1] - self.origin[1],
            "width": max(0.0, box[2]),
            "height": max(0.0, box[3]),
        }

    # ── click-map interactions ───────────────────────────────────────────────

    def apply_click_map(
        self,
        click_map: dict[str, str],
        frames_by_path: dict[str, dict[str, Any]],
        consumed: set[str],
    ) -> tuple[int, list[dict[str, Any]]]:
        mapped, unmatched = 0, []
        for key, target_path in click_map.items():
            if key in consumed:
                continue
            page, separator, selector = key.partition("->")
            if not separator:
                continue
            page_key = page.strip()
            if not (page_key == self.path or (page_key == "/" and self.page_index == 0)):
                continue
            consumed.add(key)
            selector = _normalize_selector(selector)
            target = frames_by_path.get(target_path.strip())
            if target is None:
                unmatched.append({"page": self.path, "selector": selector, "target": target_path.strip(), "reason": "target page not captured"})
                continue
            node = self._match_selector(selector)
            if node is None:
                unmatched.append({"page": self.path, "selector": selector, "target": target_path.strip(), "reason": "no node matched"})
                continue
            node["interactions"] = [
                {
                    "trigger": {"type": "ON_CLICK"},
                    "actions": [{"type": "NODE", "destinationId": target["id"], "navigation": "NAVIGATE", "transition": None}],
                }
            ]
            mapped += 1
        return mapped, unmatched

    def _match_selector(self, selector: str) -> dict[str, Any] | None:
        candidates: list[int] = []
        for token, nodes in self.selector_index.items():
            if _normalize_selector(token) == selector:
                candidates.extend(nodes)
        interactive = [n for n in candidates if self._is_interactive(n)]
        pool = interactive or candidates
        if not pool:
            return None
        chosen = pool[-1]
        return self.emitted.get(self.node_id(chosen))

    # ── scroll and fixed children ────────────────────────────────────────────

    def _apply_scroll_and_fixed(self, out: dict[str, Any], node: int, children: list[dict[str, Any]]) -> None:
        styles = self.model.style(node)
        overflow_y = styles.get("overflow-y", "visible")
        overflow_x = styles.get("overflow-x", "visible")
        direction = _overflow_direction(self.model, node, overflow_x, overflow_y)
        if direction and direction != "NONE":
            out["overflowDirection"] = direction
        fixed = [i for i in self.model.children(node) if self.model.style(i).get("position") in {"sticky", "fixed"}]
        fixed = [i for i in fixed if self.model.layout_index(i) is not None]
        if fixed:
            fixed_ids = {self.node_id(i) for i in fixed}
            ordered = [c for c in children if c["id"] not in fixed_ids] + [c for c in children if c["id"] in fixed_ids]
            children[:] = ordered
            out["numberOfFixedChildren"] = len(fixed)

    # ── svg ──────────────────────────────────────────────────────────────────

    def svg_nodes(self, node: int, box: list[float], styles: dict[str, str]) -> list[dict[str, Any]]:
        shapes = self._svg_shapes(node)
        complex_svg = len(shapes) > SVG_MAX_SHAPES or self._svg_has_complex_parts(node)
        if complex_svg:
            return [self._svg_raster_node(node, box)]
        attrs = self.model.attrs[node] if node < len(self.model.attrs) else {}
        view_box = _parse_view_box(attrs.get("viewBox"))
        if view_box is None:
            view_box = (
                0.0,
                0.0,
                _number(attrs.get("width", ""), 0.0) or box[2],
                _number(attrs.get("height", ""), 0.0) or box[3],
            )
        if view_box[2] <= 0 or view_box[3] <= 0:
            self.skip("empty", node)
            return []
        scale_x = box[2] / view_box[2]
        scale_y = box[3] / view_box[3]
        out: list[dict[str, Any]] = []
        for shape_node, tag, shape_attrs in shapes:
            vector = self._svg_vector_node(shape_node, tag, shape_attrs, box, view_box, scale_x, scale_y)
            if vector is not None:
                out.append(vector)
        if not out:
            self.skip("empty", node)
        return out

    def _svg_shapes(self, node: int) -> list[tuple[int, str, dict[str, str]]]:
        shapes: list[tuple[int, str, dict[str, str]]] = []
        stack = list(reversed(self.model.children(node)))
        while stack:
            current = stack.pop()
            tag = self.model.tag[current].lower()
            if tag == "svg":
                continue
            if tag in _SVG_SHAPE_TAGS:
                shapes.append((current, tag, self.model.attrs[current] if current < len(self.model.attrs) else {}))
            stack.extend(reversed(self.model.children(current)))
        return shapes

    def _svg_has_complex_parts(self, node: int) -> bool:
        stack = list(self.model.children(node))
        while stack:
            current = stack.pop()
            tag = self.model.tag[current].lower()
            if tag in _SVG_COMPLEX_TAGS:
                return True
            stack.extend(self.model.children(current))
        return False

    def _svg_vector_node(
        self,
        node: int,
        tag: str,
        attrs: dict[str, str],
        svg_box: list[float],
        view_box: tuple[float, float, float, float],
        scale_x: float,
        scale_y: float,
    ) -> dict[str, Any] | None:
        data = _svg_shape_data(tag, attrs)
        if not data:
            return None
        try:
            subpaths = parse_path(data)
        except PathError:
            self.unsupported_css("svg-path")
            return None
        transform = _parse_svg_transform(attrs.get("transform"))
        scaled: list[list[Segment]] = []
        for subpath in subpaths:
            scaled.append([_scale_segment(seg, transform, view_box, scale_x, scale_y) for seg in subpath])
        points = [args for subpath in scaled for _cmd, args in subpath if args]
        if not points:
            return None
        xs = [v for args in points for v in args[0::2]]
        ys = [v for args in points for v in args[1::2]]
        lx0, ly0 = max(min(xs), 0.0), max(min(ys), 0.0)
        lx1, ly1 = min(max(xs), svg_box[2]), min(max(ys), svg_box[3])
        if lx1 - lx0 < 0.05 or ly1 - ly0 < 0.05:
            return None
        local_data = _segments_to_data(scaled, offset=(-lx0, -ly0))
        fill_rule = (attrs.get("fill-rule") or "nonzero").strip().lower()
        out: dict[str, Any] = {
            "id": self.node_id(node),
            "type": "VECTOR",
            "name": "svg:paths",
            "absoluteBoundingBox": self.local_box([svg_box[0] + lx0, svg_box[1] + ly0, lx1 - lx0, ly1 - ly0]),
            "vectorPaths": [{"windingRule": "EVENODD" if fill_rule == "evenodd" else "NONZERO", "data": local_data, "path": local_data}],
        }
        fill = parse_svg_paint(attrs.get("fill"))
        stroke = parse_svg_paint(attrs.get("stroke"))
        if fill is None and stroke is None:
            fill = (0.0, 0.0, 0.0, 1.0)
        if fill is not None:
            out["fills"] = [{"type": "SOLID", "color": {"r": fill[0], "g": fill[1], "b": fill[2], "a": fill[3]}}]
        if stroke is not None:
            out["strokes"] = [{"type": "SOLID", "color": {"r": stroke[0], "g": stroke[1], "b": stroke[2], "a": stroke[3]}}]
            out["strokeWeight"] = _number(attrs.get("stroke-width", "1"), 1.0)
            out["strokeAlign"] = "CENTER"
        self.counts["vectors"] += 1
        return out

    def _svg_raster_node(self, node: int, box: list[float]) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.node_id(node),
            "type": "RECTANGLE",
            "name": "svg:raster",
            "absoluteBoundingBox": self.local_box(box),
        }
        data = None
        if self.rasterize is not None:
            data = self.rasterize({"x": box[0], "y": box[1], "width": box[2], "height": box[3]})
        if data:
            ref = "svg-" + sha1(f"{self.path}:{self.node_id(node)}".encode("utf-8")).hexdigest()[:12]
            self.images[ref] = {"url": f"rasterized:{self.node_id(node)}", "data": data}
            out["fills"] = [{"type": "IMAGE", "imageRef": ref, "scaleMode": "FILL"}]
            self.counts["images"] += 1
        else:
            out["fills"] = [{"type": "SOLID", "color": {"r": 0.85, "g": 0.85, "b": 0.85, "a": 1.0}}]
            self.counts["svgPlaceholders"] = self.counts.get("svgPlaceholders", 0) + 1
            self.svg_placeholders.append(
                (out, {"x": box[0], "y": box[1], "width": box[2], "height": box[3]})
            )
        return out


def solid_paint(r: float, g: float, b: float, a: float = 1.0) -> dict[str, Any]:
    return {"type": "SOLID", "color": {"r": r, "g": g, "b": b, "a": a}}


_PSEUDO_UNSUPPORTED = object()
_PSEUDO_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'')


def _pseudo_content(value: str) -> str | object:
    """Resolve a computed `content` value; _PSEUDO_UNSUPPORTED when not plain text."""
    text = (value or "").strip()
    if text in {"", "none", "normal"}:
        return None
    quoted = _PSEUDO_STRING.findall(text)
    residue = _PSEUDO_STRING.sub(" ", text).strip()
    if re.search(r"counter\(|counters\(|attr\(|url\(|open-quote|close-quote|no-|-quote", residue, re.IGNORECASE):
        return _PSEUDO_UNSUPPORTED
    if residue and not quoted:
        return _PSEUDO_UNSUPPORTED
    parts = [a or b for a, b in quoted]
    if residue:
        # Unquoted tokens left over are keywords we cannot resolve as text.
        return _PSEUDO_UNSUPPORTED
    return "".join(_pseudo_unescape(part) for part in parts)


def _pseudo_unescape(text: str) -> str:
    def hex_repl(match: re.Match[str]) -> str:
        return chr(int(match.group(1), 16))

    text = re.sub(r"\\([0-9a-fA-F]{1,6})\s?", hex_repl, text)
    return text.replace("\\ ", " ").replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")


def _auto_length(value: str | None) -> float | None:
    """Parse a px length, returning None for `auto` / empty values."""
    text = (value or "").strip()
    if not text or text == "auto":
        return None
    return _length(text)


def _pseudo_size(
    st: dict[str, str], content: str | object, font_size: float, parent_box: list[float]
) -> tuple[float, float]:
    width = _pseudo_dimension(st.get("width"), parent_box[2])
    height = _pseudo_dimension(st.get("height"), parent_box[3])
    line_height = _length(st.get("line-height", ""), font_size) or font_size * 1.21
    if content and width is None:
        width = max(font_size * 0.62 * len(str(content)), 1.0)
    if height is None:
        height = line_height if content else 0.0
    return width or 0.0, height or 0.0


def _pseudo_dimension(value: str | None, base: float) -> float | None:
    text = (value or "").strip()
    if not text or text == "auto":
        return None
    if text.endswith("%"):
        try:
            return base * float(text[:-1]) / 100.0
        except ValueError:
            return None
    return _length(text)


def _pseudo_origin(
    raw: dict[str, Any], st: dict[str, str], box: list[float], width: float, height: float
) -> tuple[float, float]:
    """Pseudo box origin in the anchor element's local coordinates.

    Absolute pseudos anchor to the element's padding box using computed
    top/left/right/bottom (approximation: the containing block is always the
    anchor element). Static pseudos anchor to the element's content-box origin,
    which is exact for the common `padding-left` bullet/badge case and an
    approximation whenever the pseudo flows after real content.
    """
    parent: dict[str, str] = raw.get("parent") or {}
    bl = _length(parent.get("border-left-width", "0px"))
    br = _length(parent.get("border-right-width", "0px"))
    bt = _length(parent.get("border-top-width", "0px"))
    bb = _length(parent.get("border-bottom-width", "0px"))
    position = st.get("position", "static")
    if position in {"absolute", "fixed"}:
        px0 = bl
        py0 = bt
        pw = max(box[2] - bl - br, 0.0)
        ph = max(box[3] - bt - bb, 0.0)
        left = _auto_length(st.get("left"))
        right = _auto_length(st.get("right"))
        top = _auto_length(st.get("top"))
        bottom = _auto_length(st.get("bottom"))
        resolved_w, resolved_h = width, height
        if width <= 0 and left is not None and right is not None:
            resolved_w = max(pw - left - right, 0.0)
        if height <= 0 and top is not None and bottom is not None:
            resolved_h = max(ph - top - bottom, 0.0)
        if left is not None:
            x = px0 + left
        elif right is not None:
            x = px0 + pw - right - resolved_w
        else:
            x = px0
        if top is not None:
            y = py0 + top
        elif bottom is not None:
            y = py0 + ph - bottom - resolved_h
        else:
            y = py0
        return x, y
    pl = _length(parent.get("padding-left", "0px"))
    pt = _length(parent.get("padding-top", "0px"))
    return bl + pl, bt + pt


def _background_fills(
    styles: dict[str, str],
    compiler: "_PageCompiler",
    fetcher: FetchImage | None,
    box: list[float],
) -> list[dict[str, Any]]:
    fills: list[dict[str, Any]] = []
    color = styles.get("background-color", "rgba(0, 0, 0, 0)")
    solid = _solid_fills(color, compiler)
    if solid:
        fills.extend(solid)
    layers = _split_top_level(styles.get("background-image", "none"), ",")
    paints: list[dict[str, Any]] = []
    for layer in reversed([layer.strip() for layer in layers if layer.strip()]):
        if not layer or layer == "none":
            continue
        paint = _background_layer_paint(layer, compiler, box)
        if paint is None:
            compiler.unsupported_css("background-image")
        elif paint:
            paints.extend(paint)
    fills.extend(paints)
    return fills


def _background_layer_paint(layer: str, compiler: "_PageCompiler", box: list[float]) -> list[dict[str, Any]]:
    lowered = layer.lower()
    url = _url_token(layer)
    if url:
        fill = _image_fill(url, compiler)
        return [fill] if fill else []
    if lowered.startswith("repeating-conic-gradient(") or lowered.startswith("conic-gradient("):
        paint = _conic_paint(layer, compiler, box)
        return [paint] if paint else []
    if lowered.startswith("linear-gradient("):
        paint = _gradient_paint("GRADIENT_LINEAR", layer, box)
        return [paint] if paint else []
    if lowered.startswith("radial-gradient("):
        paint = _gradient_paint("GRADIENT_RADIAL", layer, box)
        return [paint] if paint else []
    return []


_CONIC_FROM = re.compile(
    r"^from\s+(?P<angle>[-\d.]+(?:deg|grad|rad|turn))(?:\s+at\s+(?P<at>.+))?$", re.IGNORECASE
)


def _conic_paint(layer: str, compiler: "_PageCompiler", box: list[float]) -> dict[str, Any] | None:
    """Map conic-gradient(...) to GRADIENT_ANGULAR; None (counted) when exotic."""
    repeating = layer.lower().lstrip().startswith("repeating-conic-gradient(")
    open_index = layer.find("(")
    close_index = layer.rfind(")")
    if open_index < 0 or close_index <= open_index:
        return None
    tokens = [t.strip() for t in _split_top_level(layer[open_index + 1 : close_index], ",") if t.strip()]
    angle = 0.0
    center = (0.5, 0.5)
    if tokens and (tokens[0].lower().startswith("from ") or tokens[0].lower().startswith("at ")):
        head = tokens.pop(0)
        match = _CONIC_FROM.match(head)
        if match:
            angle = _css_angle_value(match.group("angle"))
            if match.group("at"):
                center = _conic_center(match.group("at"))
        elif head.lower().startswith("at "):
            center = _conic_center(head[3:])
        else:
            compiler.unsupported_css("conic-hints")
            return _conic_raster_fallback(compiler, box)
    stops: list[dict[str, Any]] = []
    for token in tokens:
        color_part, positions = _split_stop_positions(token)
        color = parse_css_color(color_part)
        if color is None:
            if _stop_position(token) is not None or not color_part.strip():
                compiler.unsupported_css("conic-hints")  # color interpolation hint
            else:
                compiler.unsupported_css("conic-color")
            return _conic_raster_fallback(compiler, box)
        for position in positions or (-1.0,):
            stops.append({"position": position, "color": {"r": color[0], "g": color[1], "b": color[2], "a": color[3]}})
    if not stops:
        return _conic_raster_fallback(compiler, box)
    stops = _distribute_stops(stops)
    if repeating:
        expanded = _expand_repeating_conic(stops)
        if expanded is None:
            compiler.unsupported_css("conic-repeat")
            return _conic_raster_fallback(compiler, box)
        stops = expanded
    if len(stops) == 1:
        stops = [dict(stops[0], position=0.0), dict(stops[0], position=1.0)]
    rad = math.radians(angle)
    direction = (math.sin(rad), -math.cos(rad))
    sweep = (-direction[1], direction[0])
    handles = [
        {"x": center[0], "y": center[1]},
        {"x": center[0] + 0.5 * direction[0], "y": center[1] + 0.5 * direction[1]},
        {"x": center[0] + 0.5 * sweep[0], "y": center[1] + 0.5 * sweep[1]},
    ]
    return {"type": "GRADIENT_ANGULAR", "gradientStops": stops, "gradientHandlePositions": handles}


def _conic_raster_fallback(compiler: "_PageCompiler", box: list[float]) -> dict[str, Any]:
    """Marker paint; the owning node resolves it to a raster IMAGE or placeholder."""
    return {"type": "CONIC_RASTER"}


def _expand_repeating_conic(stops: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Tile a repeating-conic segment across [0, 1] as explicit stops.

    Returns None when the segment does not form a simple repeatable tile.
    """
    if len(stops) < 2:
        return None
    start, end = stops[0]["position"], stops[-1]["position"]
    if abs(start) > 1e-9:
        return None
    if abs(end - 1.0) <= 1e-9:
        return stops  # the "repeat" already spans the full turn
    if not (0.0 < end < 1.0):
        return None
    segments = int(math.floor(1.0 / end + 1e-9))
    if segments < 1 or segments > 12:
        return None
    out: list[dict[str, Any]] = []
    for k in range(segments):
        for stop in stops:
            position = k * end + stop["position"]
            if position > 1.0 + 1e-9:
                continue
            out.append({"position": min(position, 1.0), "color": stop["color"]})
    if not out or out[-1]["position"] < 1.0:
        out.append({"position": 1.0, "color": stops[0]["color"]})
    return out


def _conic_center(value: str) -> tuple[float, float]:
    horizontal = {"left": 0.0, "center": 0.5, "right": 1.0}
    vertical = {"top": 0.0, "center": 0.5, "bottom": 1.0}

    def resolve(token: str, keywords: dict[str, float]) -> float | None:
        lowered = token.lower()
        if lowered in keywords:
            return keywords[lowered]
        if lowered.endswith("%"):
            try:
                return float(lowered[:-1]) / 100.0
            except ValueError:
                return None
        return None

    tokens = (value or "").split()
    x = y = 0.5
    if len(tokens) >= 1:
        rx = resolve(tokens[0], horizontal)
        if rx is not None:
            x = rx
        elif len(tokens) == 1:
            ry = resolve(tokens[0], vertical)
            if ry is not None:
                y = ry
    if len(tokens) >= 2:
        ry = resolve(tokens[1], vertical)
        if ry is not None:
            y = ry
    return x, y


def _css_angle_value(token: str) -> float:
    token = (token or "").strip().lower()
    match = re.match(r"^([-\d.]+)(deg|grad|rad|turn)$", token)
    if not match:
        return 0.0
    number = float(match.group(1))
    unit = match.group(2)
    if unit == "deg":
        return number
    if unit == "grad":
        return number * 0.9
    if unit == "rad":
        return number * 180.0 / math.pi
    return number * 360.0


def _split_stop_positions(token: str) -> tuple[str, list[float]]:
    """Split a gradient stop into (color, positions); supports % and angles."""
    parts = token.split()
    positions: list[float] = []
    while len(parts) > 1:
        last = parts[-1]
        position = _stop_position(last)
        if position is None:
            break
        positions.insert(0, position)
        parts.pop()
    return " ".join(parts), positions


def _stop_position(token: str) -> float | None:
    token = token.strip().lower()
    if token.endswith("%"):
        try:
            return float(token[:-1]) / 100.0
        except ValueError:
            return None
    match = re.match(r"^([-\d.]+)(deg|grad|rad|turn)$", token)
    if match:
        return _css_angle_value(token) / 360.0
    return None



def _url_token(layer: str) -> str | None:
    match = re.search(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)""", layer, re.IGNORECASE)
    return match.group(2) if match else None


def _image_fill(url: str, compiler: "_PageCompiler") -> dict[str, Any] | None:
    ref = "img-" + sha1(url.encode("utf-8")).hexdigest()[:12]
    if ref not in compiler.images:
        data = compiler.fetcher(url) if compiler.fetcher else None
        if data is None:
            compiler.image_failures.append(url)
            return None
        compiler.images[ref] = {"url": url, "data": data}
    return {"type": "IMAGE", "imageRef": ref, "scaleMode": "FILL"}


def _image_fill_for_img(compiler: "_PageCompiler", node: int) -> list[dict[str, Any]]:
    src = compiler.model.attr(node, "src")
    if not src:
        return []
    fill = _image_fill(src, compiler)
    return [fill] if fill else []


def _gradient_paint(figma_kind: str, layer: str, box: list[float]) -> dict[str, Any] | None:
    open_index = layer.find("(")
    close_index = layer.rfind(")")
    if open_index < 0 or close_index <= open_index:
        return None
    tokens = _split_top_level(layer[open_index + 1 : close_index], ",")
    tokens = [t.strip() for t in tokens if t.strip()]
    angle = 180.0
    if figma_kind == "GRADIENT_LINEAR" and tokens and _is_angle_token(tokens[0]):
        angle = _css_angle(tokens[0])
        tokens = tokens[1:]
    if figma_kind == "GRADIENT_RADIAL":
        tokens = _strip_radial_geometry(tokens)
    stops: list[dict[str, Any]] = []
    for token in tokens:
        color_part, position = _split_stop(token)
        color = parse_css_color(color_part)
        if color is None:
            return None
        stops.append({"position": position, "color": {"r": color[0], "g": color[1], "b": color[2], "a": color[3]}})
    if not stops:
        return None
    stops = _distribute_stops(stops)
    if len(stops) == 1:
        stops = [dict(stops[0], position=0.0), dict(stops[0], position=1.0)]
    if figma_kind == "GRADIENT_LINEAR":
        handles = _linear_handles(angle, box)
    else:
        handles = [{"x": 0.5, "y": 0.5}, {"x": 1.0, "y": 0.5}, {"x": 0.5, "y": 1.0}]
    return {"type": figma_kind, "gradientStops": stops, "gradientHandlePositions": handles}


_ANGLE_TOKEN = re.compile(r"^([-\d.]+)(deg|grad|rad|turn)$")


def _is_angle_token(token: str) -> bool:
    return bool(_ANGLE_TOKEN.match(token.strip().lower())) or token.strip().lower().startswith("to ")


_RADIAL_GEOMETRY = {"circle", "ellipse", "at", "closest-side", "farthest-side", "closest-corner", "farthest-corner", "center", "top", "bottom", "left", "right"}


def _strip_radial_geometry(tokens: list[str]) -> list[str]:
    out = list(tokens)
    at_pending = False
    while out:
        token = out[0].strip().lower()
        if token in _RADIAL_GEOMETRY or token.endswith(("-side", "-corner")) or at_pending:
            out.pop(0)
            at_pending = token == "at"
            continue
        break
    return out


def _distribute_stops(stops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if all(stop["position"] < 0 for stop in stops):
        count = len(stops)
        for index, stop in enumerate(stops):
            stop["position"] = index / (count - 1) if count > 1 else 0.0
    else:
        previous, next_index = 0.0, 0
        for index, stop in enumerate(stops):
            if stop["position"] < 0:
                lookahead = next(
                    (s["position"] for s in stops[index + 1 :] if s["position"] >= 0), 1.0
                )
                span = max(next_index + 1, index + 1)
                stop["position"] = previous + (lookahead - previous) * (index + 1 - next_index) / (span - next_index)
            else:
                previous, next_index = stop["position"], index
    for stop in stops:
        stop["position"] = max(0.0, min(1.0, stop["position"]))
    return sorted(stops, key=lambda s: s["position"])


def _split_stop(token: str) -> tuple[str, float]:
    parts = token.rsplit(None, 1)
    if len(parts) == 2 and re.match(r"^[\d.]+%$", parts[1]):
        return parts[0], float(parts[1][:-1]) / 100.0
    if len(parts) == 2 and re.match(r"^[\d.]+px$", parts[1]):
        return parts[0], 0.0
    return token, -1.0


def _css_angle(token: str) -> float:
    token = token.strip().lower()
    match = re.match(r"^([-\d.]+)deg$", token)
    if match:
        return float(match.group(1))
    if token.startswith("to "):
        words = token[3:].split()
        horizontal = {"right": 90, "left": -90}.get(words[-1] if words else "", None)
        vertical = {"top": 0, "bottom": 180}.get(words[0] if words else "", None)
        if horizontal is not None and vertical is not None:
            return (horizontal + vertical) / 2
        if horizontal is not None:
            return horizontal
        if vertical is not None:
            return vertical
    return 180.0


def _linear_handles(angle: float, box: list[float]) -> list[dict[str, float]]:
    import math

    width, height = max(box[2], 1e-6), max(box[3], 1e-6)
    rad = math.radians(angle)
    sin_v, cos_v = math.sin(rad), math.cos(rad)
    length = abs(width * sin_v) + abs(height * cos_v)
    p0x = 0.5 - sin_v * length / (2 * width)
    p0y = 0.5 + cos_v * length / (2 * height)
    p1x = 0.5 + sin_v * length / (2 * width)
    p1y = 0.5 - cos_v * length / (2 * height)
    return [
        {"x": p0x, "y": p0y},
        {"x": p1x, "y": p1y},
        {"x": p0x + cos_v, "y": p0y + sin_v},
    ]


def _split_top_level(value: str, separator: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in value:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == separator and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


def _solid_fills(value: str | None, compiler: "_PageCompiler") -> list[dict[str, Any]]:
    color = parse_css_color(value or "")
    if color is None or color[3] <= 0.0:
        return []
    if color[3] < 1.0:
        return [{"type": "SOLID", "color": {"r": color[0], "g": color[1], "b": color[2], "a": 1.0}, "opacity": color[3]}]
    return [solid_paint(color[0], color[1], color[2])]


_BORDER_SIDES = ("top", "right", "bottom", "left")


def _border_info(styles: dict[str, str]) -> dict[str, Any] | None:
    widths = [_length(styles.get(f"border-{side}-width", "0px")) for side in _BORDER_SIDES]
    if not any(width > 0 for width in widths):
        return None
    kinds = [styles.get(f"border-{side}-style", "none").strip().lower() for side in _BORDER_SIDES]
    color = None
    for side, width in zip(_BORDER_SIDES, widths):
        if width > 0:
            color = parse_css_color(styles.get(f"border-{side}-color", ""))
            if color is not None:
                break
    if color is None:
        return None
    out: dict[str, Any] = {
        "strokes": [{"type": "SOLID", "color": {"r": color[0], "g": color[1], "b": color[2], "a": color[3]}}],
        "strokeAlign": "INSIDE",
    }
    if len({round(w, 6) for w in widths}) == 1:
        out["strokeWeight"] = widths[0]
    else:
        out["individualStrokeWeights"] = {
            "strokeTopWeight": widths[0],
            "strokeRightWeight": widths[1],
            "strokeBottomWeight": widths[2],
            "strokeLeftWeight": widths[3],
        }
    if "dashed" in kinds:
        weight = max(widths)
        out["strokeDashes"] = [max(3.0, weight * 3), max(3.0, weight * 2)]
    elif "dotted" in kinds:
        weight = max(widths)
        out["strokeDashes"] = [max(1.0, weight), max(1.0, weight)]
    return out


def _effects(styles: dict[str, str], compiler: "_PageCompiler") -> list[dict[str, Any]]:
    effects: list[dict[str, Any]] = []
    for shadow in _split_top_level(styles.get("box-shadow", "none"), ","):
        effect = _shadow_effect(shadow.strip())
        if effect:
            effects.append(effect)
    backdrop = _blur_radius(styles.get("backdrop-filter", "none"))
    if backdrop is not None:
        effects.append({"type": "BACKGROUND_BLUR", "radius": backdrop, "visible": True})
    layer_blur = _blur_radius(styles.get("filter", "none"))
    if layer_blur is not None:
        effects.append({"type": "LAYER_BLUR", "radius": layer_blur, "visible": True})
    return effects


def _shadow_effect(shadow: str) -> dict[str, Any] | None:
    if not shadow or shadow == "none":
        return None
    inset = "inset" in [t.lower() for t in shadow.split()]
    color = None
    numbers: list[float] = []
    for token in _split_top_level(shadow, " "):
        token = token.strip()
        if not token:
            continue
        if token.lower() == "inset":
            continue
        parsed = parse_css_color(token)
        if parsed is not None and color is None:
            color = parsed
            continue
        length = _length(token)
        if length or re.match(r"^[-\d.]+(px|rem|em)?$", token):
            numbers.append(length)
    if color is None:
        color = (0.0, 0.0, 0.0, 0.25)
    while len(numbers) < 4:
        numbers.append(0.0)
    return {
        "type": "INNER_SHADOW" if inset else "DROP_SHADOW",
        "color": {"r": color[0], "g": color[1], "b": color[2], "a": color[3]},
        "offset": {"x": numbers[0], "y": numbers[1]},
        "radius": numbers[2],
        "spread": numbers[3],
        "visible": True,
        "blendMode": "NORMAL",
    }


def _blur_radius(value: str) -> float | None:
    match = re.search(r"blur\(\s*([\d.]+)px\s*\)", value or "", re.IGNORECASE)
    return float(match.group(1)) if match else None


def _opacity(styles: dict[str, str]) -> float | None:
    try:
        opacity = float(styles.get("opacity", "1"))
    except ValueError:
        return None
    return opacity if opacity < 1.0 else None


_BLEND_MODES = {
    "multiply": "MULTIPLY",
    "screen": "SCREEN",
    "overlay": "OVERLAY",
    "darken": "DARKEN",
    "lighten": "LIGHTEN",
    "color-dodge": "COLOR_DODGE",
    "color-burn": "COLOR_BURN",
    "hard-light": "HARD_LIGHT",
    "soft-light": "SOFT_LIGHT",
    "difference": "DIFFERENCE",
    "exclusion": "EXCLUSION",
    "hue": "HUE",
    "saturation": "SATURATION",
    "color": "COLOR",
    "luminosity": "LUMINOSITY",
}


def _blend_mode(styles: dict[str, str]) -> str:
    return _BLEND_MODES.get(styles.get("mix-blend-mode", "normal").strip().lower(), "")


def _overflow_direction(model: SnapshotModel, node: int, overflow_x: str, overflow_y: str) -> str:
    box = model.box(node)
    if box is None:
        return "NONE"
    child_boxes = [model.box(c) for c in model.children(node) if model.node_type[c] == 1 and model.box(c) is not None]
    if not child_boxes:
        return "NONE"
    reach_y = max(b[1] + b[3] for b in child_boxes)
    reach_x = max(b[0] + b[2] for b in child_boxes)
    vertical = overflow_y in {"auto", "scroll"} and reach_y > box[1] + box[3] + 1.0
    horizontal = overflow_x in {"auto", "scroll"} and reach_x > box[0] + box[2] + 1.0
    if vertical and horizontal:
        return "HORIZONTAL_AND_VERTICAL_SCROLLING"
    if vertical:
        return "VERTICAL_SCROLLING"
    if horizontal:
        return "HORIZONTAL_SCROLLING"
    return "NONE"


def _corner_radii(styles: dict[str, str], box: list[float]) -> dict[str, Any]:
    values = []
    for corner in ("border-top-left-radius", "border-top-right-radius", "border-bottom-right-radius", "border-bottom-left-radius"):
        radius = _length(styles.get(corner, "0px"), min(box[2], box[3]))
        values.append(max(0.0, radius))
    if not any(values):
        return {}
    out: dict[str, Any] = {"rectangleCornerRadii": values}
    if len({round(v, 6) for v in values}) == 1:
        out["cornerRadius"] = values[0]
    return out


def _length(value: str, base: float = 0.0) -> float:
    """Parse a CSS px length (or % of `base`) to points; 0 when not parseable."""
    value = (value or "").strip()
    match = re.match(r"^([-\d.]+)(px|%)?$", value)
    if not match:
        return 0.0
    number = float(match.group(1))
    if match.group(2) == "%":
        return base * number / 100.0
    return number


_NAMED_COLORS = {
    "black": (0, 0, 0),
    "white": (1, 1, 1),
    "red": (1, 0, 0),
    "green": (0, 0.5019607843137255, 0),
    "blue": (0, 0, 1),
    "yellow": (1, 1, 0),
    "orange": (1, 0.6470588235294118, 0),
    "purple": (0.5019607843137255, 0, 0.5019607843137255),
    "gray": (0.5019607843137255, 0.5019607843137255, 0.5019607843137255),
    "grey": (0.5019607843137255, 0.5019607843137255, 0.5019607843137255),
    "transparent": (0, 0, 0, 0),
}


def parse_css_color(value: str) -> tuple[float, float, float, float] | None:
    """Parse a computed CSS color into (r, g, b, a) in 0..1; None when transparent/unparseable."""
    value = (value or "").strip().lower()
    if not value or value in {"none", "transparent"}:
        return None
    if value in _NAMED_COLORS:
        rgb = _NAMED_COLORS[value]
        return (rgb[0], rgb[1], rgb[2], rgb[3] if len(rgb) > 3 else 1.0)
    if value.startswith("#"):
        hex_value = value[1:]
        if len(hex_value) in {3, 4}:
            hex_value = "".join(ch * 2 for ch in hex_value)
        if len(hex_value) in {6, 8}:
            channels = [int(hex_value[i : i + 2], 16) / 255.0 for i in range(0, len(hex_value), 2)]
            if len(channels) == 3:
                channels.append(1.0)
            return (channels[0], channels[1], channels[2], channels[3])
        return None
    match = re.match(r"rgba?\(([^)]+)\)", value)
    if match:
        body = match.group(1)
        alpha = 1.0
        if "/" in body:
            body, alpha_part = body.split("/", 1)
            alpha = _component(alpha_part.strip(), 1.0, alpha=True)
        channels = [part for part in re.split(r"[,\s]+", body.strip()) if part]
        if len(channels) == 4:
            alpha = _component(channels[3], 1.0, alpha=True)
            channels = channels[:3]
        if len(channels) == 3:
            rgb = tuple(_component(c, 255.0) for c in channels)
            return (rgb[0], rgb[1], rgb[2], max(0.0, min(1.0, alpha)))
    return None


def _component(value: str, scale: float, *, alpha: bool = False) -> float:
    value = value.strip()
    if value.endswith("%"):
        number = float(value[:-1]) / 100.0
        return number if alpha else max(0.0, min(1.0, number))
    number = float(value)
    if alpha:
        return max(0.0, min(1.0, number))
    return max(0.0, min(1.0, number / scale))


def _opacity(styles: dict[str, str]) -> float | None:
    try:
        opacity = float(styles.get("opacity", "1"))
    except ValueError:
        return None
    return opacity if opacity < 1.0 else None


def _text_style(styles: dict[str, str]) -> dict[str, Any]:
    font_size = _length(styles.get("font-size", "16px")) or 16.0
    style: dict[str, Any] = {
        "fontFamily": _font_family(styles.get("font-family", "")),
        "fontWeight": _number(styles.get("font-weight", "400"), 400.0),
        "italic": styles.get("font-style", "normal") == "italic",
        "fontSize": font_size,
        "letterSpacing": _length(styles.get("letter-spacing", "normal")),
        "textAutoResize": "HEIGHT",
        "textAlignHorizontal": {"center": "CENTER", "right": "RIGHT", "end": "RIGHT"}.get(
            styles.get("text-align", "start").strip(), "LEFT"
        ),
    }
    line_height = styles.get("line-height", "normal").strip()
    if line_height not in {"", "normal"}:
        style["lineHeightPx"] = _length(line_height, font_size)
        style["lineHeightUnit"] = "PIXELS"
    decoration = styles.get("text-decoration", "none")
    if "underline" in decoration:
        style["textDecoration"] = "UNDERLINE"
    elif "line-through" in decoration:
        style["textDecoration"] = "STRIKETHROUGH"
    case = styles.get("text-transform", "none").strip()
    if case in {"uppercase", "lowercase", "capitalize"}:
        style["textCase"] = {"uppercase": "UPPER", "lowercase": "LOWER", "capitalize": "TITLE"}[case]
    return style


def _font_family(value: str) -> str:
    match = re.search(r'"([^"]+)"|\'([^\']+)\'|([^,]+)', value or "")
    if not match:
        return "Inter"
    family = next(group for group in match.groups() if group is not None)
    return family.strip() or "Inter"


def _number(value: str, default: float) -> float:
    try:
        return float((value or "").strip())
    except ValueError:
        return default


_IDENTITY_MATRIX = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _parse_css_matrix(value: str) -> tuple[float, float, float, float, float, float] | None:
    """Parse a computed 2D `matrix(a, b, c, d, e, f)`; None when absent/3D."""
    text = (value or "").strip()
    if not text or text.lower() == "none":
        return None
    match = re.match(r"^matrix\(([^)]*)\)$", text, re.IGNORECASE)
    if not match:
        return None
    parts = [float(p) for p in re.split(r"[,\s]+", match.group(1).strip()) if p]
    if len(parts) != 6:
        return None
    return (parts[0], parts[1], parts[2], parts[3], parts[4], parts[5])


def _parse_css_origin(value: str, box: list[float]) -> tuple[float, float]:
    """transform-origin in px relative to the border-box top-left."""
    tokens = (value or "").split()
    if not tokens:
        return box[2] / 2.0, box[3] / 2.0

    def axis(token: str, base: float, default: float) -> float:
        token = token.strip()
        if token.endswith("%"):
            try:
                return base * float(token[:-1]) / 100.0
            except ValueError:
                return default
        return _length(token) or default

    ox = axis(tokens[0], box[2], box[2] / 2.0)
    oy = axis(tokens[1], box[3], box[3] / 2.0) if len(tokens) > 1 else box[3] / 2.0
    return ox, oy


def _solve_size_from_aabb(
    a: float, b: float, c: float, d: float, width: float, height: float
) -> tuple[float, float] | None:
    """Recover a base box size from its transformed AABB via |linear| extents.

    W = |a|w + |c|h and H = |b|w + |d|h; singular exactly at 45deg-style
    rotations where the system has no unique solution.
    """
    aa, cc, bb, dd = abs(a), abs(c), abs(b), abs(d)
    det = aa * dd - cc * bb
    if abs(det) < 1e-9:
        return None
    w = (dd * width - cc * height) / det
    h = (aa * height - bb * width) / det
    if w <= 0 or h <= 0:
        return None
    return w, h


def _style_override(source: dict[str, str], base: dict[str, str], base_style: dict[str, Any]) -> dict[str, Any]:
    source_style = _text_style(source)
    override: dict[str, Any] = {}
    for key in ("fontFamily", "fontWeight", "italic", "fontSize", "letterSpacing", "textDecoration", "textCase"):
        if key in source_style and source_style[key] != base_style.get(key):
            override[key] = source_style[key]
    source_color = parse_css_color(source.get("color", ""))
    base_color = parse_css_color(base.get("color", ""))
    if source_color is not None and source_color != base_color:
        if source_color[3] < 1.0:
            override["fills"] = [
                {
                    "type": "SOLID",
                    "color": {"r": source_color[0], "g": source_color[1], "b": source_color[2], "a": 1.0},
                    "opacity": source_color[3],
                }
            ]
        else:
            override["fills"] = [solid_paint(source_color[0], source_color[1], source_color[2])]
    return override


def compile_snapshots(
    pages: Sequence[tuple[str, dict[str, Any]]],
    *,
    fetcher: FetchImage | None = None,
    rasterize: RasterizeSvg | None = None,
    click_map: dict[str, str] | None = None,
    props: Sequence[str] = STYLE_PROPS,
    pseudos: Sequence[Sequence[dict[str, Any]]] | None = None,
) -> CaptureResult:
    """Compile captured DOMSnapshot payloads into a Figma file payload."""
    clickables: list[dict[str, Any]] = []
    images: dict[str, dict[str, Any]] = {}
    page_reports: list[dict[str, Any]] = []
    compilers: list[_PageCompiler] = []
    frames: list[dict[str, Any]] = []
    offset_x = 0.0
    pseudo_lists = list(pseudos) if pseudos is not None else []
    for page_index, (path, snapshot) in enumerate(pages):
        model = SnapshotModel(snapshot, props)
        report_page: dict[str, Any] = {"path": path, "title": model.title}
        compiler = _PageCompiler(
            model,
            page_index=page_index,
            path=path,
            fetcher=fetcher,
            rasterize=rasterize,
            images=images,
            pseudo_entries=pseudo_lists[page_index] if page_index < len(pseudo_lists) else (),
        )
        frame = compiler.build()
        width = frame["absoluteBoundingBox"]["width"]
        frame["absoluteBoundingBox"]["x"] = offset_x
        for child in walk_all(frame):
            if "relativeTransform" in child:
                continue  # transformed-subtree boxes are parent-local, not frame-local
            child["absoluteBoundingBox"]["x"] += offset_x
        offset_x += width + 200.0
        compilers.append(compiler)
        frames.append(frame)
        clickables.extend(compiler.page_clickables)
        report_page.update(
            {
                "frameId": frame["id"],
                "counts": dict(compiler.counts),
                "skipped": dict(compiler.skipped),
                "unsupported": dict(compiler.unsupported),
                "images": {"downloaded": len(compiler.images), "failed": list(compiler.image_failures)},
                "PSEUDO_COUNT": compiler.counts.get("pseudos", 0),
            }
        )
        page_reports.append(report_page)
    mapped_total, unmatched_total = 0, []
    if click_map:
        frames_by_path = {path: frame for (path, _snapshot), frame in zip(pages, frames)}
        consumed: set[str] = set()
        for compiler in compilers:
            mapped, unmatched = compiler.apply_click_map(click_map, frames_by_path, consumed)
            mapped_total += mapped
            unmatched_total.extend(unmatched)
        for key in click_map:
            if key not in consumed and "->" in key:
                page = key.split("->")[0].strip()
                unmatched_total.append({"page": page, "selector": _normalize_selector(key.split("->")[1]), "reason": "source page not captured"})
    first = frames[0]
    payload = {
        "name": str(first["name"]),
        "schemaVersion": 0,
        "document": {
            "id": "0:0",
            "type": "DOCUMENT",
            "name": "Document",
            "children": [
                {
                    "id": "0:1",
                    "type": "CANVAS",
                    "name": "Captures",
                    "backgroundColor": {"r": 1, "g": 1, "b": 1, "a": 1},
                    "flowStartingPoints": [{"nodeId": first["id"], "name": "Start"}],
                    "children": frames,
                }
            ],
        },
    }
    report = {
        "pages": page_reports,
        "PSEUDO_COUNT": sum(int(page.get("PSEUDO_COUNT", 0)) for page in page_reports),
        "images": {
            "downloaded": len(images),
            "failed": sorted({url for page in page_reports for url in page.get("images", {}).get("failed", ())}),
        },
        "interactions": {"mapped": mapped_total, "unmatched": unmatched_total},
    }
    svg_raster = [
        {"node": node, "box": box, "key": f"{compilers[index].path}:{node['id']}"}
        for index, compiler in enumerate(compilers)
        for node, box in compiler.svg_placeholders + compiler.raster_queue
    ]
    return CaptureResult(file=payload, images=images, clickables=clickables, report=report, svg_raster=svg_raster)


def _normalize_selector(selector: str) -> str:
    return re.sub(r"['\"]", "", selector.strip())


def walk_all(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for child in node.get("children") or ():
        yield child
        yield from walk_all(child)

def _parse_view_box(value: str | None) -> tuple[float, float, float, float] | None:
    if not value:
        return None
    parts = [p for p in re.split(r"[,\s]+", value.strip()) if p]
    if len(parts) != 4:
        return None
    try:
        return tuple(float(p) for p in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def _svg_shape_data(tag: str, attrs: dict[str, str]) -> str | None:
    if tag == "path":
        return attrs.get("d") or None
    if tag == "rect":
        try:
            x, y = float(attrs.get("x", 0)), float(attrs.get("y", 0))
            w, h = float(attrs.get("width", 0)), float(attrs.get("height", 0))
        except ValueError:
            return None
        if w <= 0 or h <= 0:
            return None
        return f"M {x} {y} L {x + w} {y} L {x + w} {y + h} L {x} {y + h} Z"
    if tag in {"circle", "ellipse"}:
        try:
            cx, cy = float(attrs.get("cx", 0)), float(attrs.get("cy", 0))
            if tag == "circle":
                rx = ry = float(attrs.get("r", 0))
            else:
                rx, ry = float(attrs.get("rx", 0)), float(attrs.get("ry", 0))
        except ValueError:
            return None
        if rx <= 0 or ry <= 0:
            return None
        return f"M {cx - rx} {cy} A {rx} {ry} 0 1 0 {cx + rx} {cy} A {rx} {ry} 0 1 0 {cx - rx} {cy} Z"
    if tag == "line":
        try:
            return f"M {float(attrs.get('x1', 0))} {float(attrs.get('y1', 0))} L {float(attrs.get('x2', 0))} {float(attrs.get('y2', 0))}"
        except ValueError:
            return None
    if tag in {"polygon", "polyline"}:
        raw = attrs.get("points") or ""
        numbers = [p for p in re.split(r"[,\s]+", raw.strip()) if p]
        if len(numbers) < 4 or len(numbers) % 2:
            return None
        try:
            coords = [float(n) for n in numbers]
        except ValueError:
            return None
        pairs = " ".join(f"{coords[i]} {coords[i + 1]}" for i in range(0, len(coords), 2))
        close = " Z" if tag == "polygon" else ""
        return f"M {pairs}{close}"
    return None


def _parse_svg_transform(value: str | None) -> tuple[float, float, float, float, float, float] | None:
    """Parse an SVG transform attribute into a 2x3 matrix (a, b, c, d, e, f)."""
    if not value:
        return None
    matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for name, args_text in re.findall(r"(matrix|translate|scale)\s*\(([^)]*)\)", value, re.IGNORECASE):
        parts = [float(p) for p in re.split(r"[,\s]+", args_text.strip()) if p]
        if name.lower() == "matrix" and len(parts) == 6:
            step = parts
        elif name.lower() == "translate" and parts:
            step = (1.0, 0.0, 0.0, 1.0, parts[0], parts[1] if len(parts) > 1 else 0.0)
        elif name.lower() == "scale" and parts:
            step = (parts[0], 0.0, 0.0, parts[1] if len(parts) > 1 else parts[0], 0.0, 0.0)
        else:
            continue
        matrix = (
            matrix[0] * step[0] + matrix[2] * step[1],
            matrix[1] * step[0] + matrix[3] * step[1],
            matrix[0] * step[2] + matrix[2] * step[3],
            matrix[1] * step[2] + matrix[3] * step[3],
            matrix[0] * step[4] + matrix[2] * step[5] + matrix[4],
            matrix[1] * step[4] + matrix[3] * step[5] + matrix[5],
        )
    return matrix


def _scale_segment(
    seg: Segment,
    transform: tuple[float, float, float, float, float, float] | None,
    view_box: tuple[float, float, float, float],
    scale_x: float,
    scale_y: float,
) -> Segment:
    cmd, args = seg
    if cmd == "Z" or not args:
        return seg
    shifted = [args[i] - (view_box[0] if i % 2 == 0 else view_box[1]) for i in range(len(args))]
    if transform is not None:
        a, b, c, d, e, f = transform
        mapped: list[float] = []
        for i in range(0, len(shifted), 2):
            x, y = shifted[i], shifted[i + 1]
            mapped.extend((a * x + c * y + e, b * x + d * y + f))
        shifted = mapped
    scaled = [shifted[i] * (scale_x if i % 2 == 0 else scale_y) for i in range(len(shifted))]
    return (cmd, tuple(scaled))


def _segments_to_data(subpaths: list[list[Segment]], offset: tuple[float, float]) -> str:
    parts: list[str] = []
    for subpath in subpaths:
        for cmd, args in subpath:
            if cmd == "Z" or not args:
                parts.append("Z")
                continue
            shifted = [args[i] + (offset[0] if i % 2 == 0 else offset[1]) for i in range(len(args))]
            parts.append(cmd + " " + " ".join(_fmt_number(v) for v in shifted))
    return " ".join(parts)


def _fmt_number(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text if text else "0"


def parse_svg_paint(value: str | None) -> tuple[float, float, float, float] | None:
    if not value or value.strip().lower() in {"none", "transparent"}:
        return None
    return parse_css_color(value)


# ── orchestration: drive the browser and write outputs ──────────────────────


def parse_viewport(value: str) -> tuple[int, int, float]:
    """Parse a WIDTHxHEIGHT[@SCALE] viewport spec."""
    match = re.match(r"^(\d+)x(\d+)(?:@([\d.]+))?$", (value or "").strip())
    if not match:
        raise CaptureError(f"invalid --viewport {value!r}; expected WIDTHxHEIGHT[@SCALE]")
    return int(match.group(1)), int(match.group(2)), float(match.group(3) or 3.0)


def write_capture(result: CaptureResult, out_dir: str | Path) -> Path:
    """Write figma_file.json, images/, clickables.json, and capture_report.json."""
    from .cli import _save_image

    out = Path(out_dir)
    (out / "images").mkdir(parents=True, exist_ok=True)
    for ref, entry in result.images.items():
        _save_image(entry["data"], out / "images", ref)
    design = out / "figma_file.json"
    design.write_text(json.dumps(result.file), encoding="utf-8")
    (out / "clickables.json").write_text(json.dumps(result.clickables, indent=1), encoding="utf-8")
    (out / "capture_report.json").write_text(json.dumps(result.report, indent=1), encoding="utf-8")
    return design


def _load_click_map(path: str | Path | None) -> dict[str, str]:
    if path is None:
        return {}
    import json as _json

    text = Path(path).read_text(encoding="utf-8")
    parsed = _json.loads(text)
    if not isinstance(parsed, dict):
        raise CaptureError("click map must be a JSON object of \"page -> selector\": \"target\"")
    return {str(k): str(v) for k, v in parsed.items()}


def _page_targets(base: str, pages: Sequence[str]) -> list[tuple[str, str]]:
    from urllib.parse import urlparse, urljoin

    path = urlparse(base).path or "/"
    targets = [(path, base)]
    for extra in pages:
        extra = extra.strip()
        if not extra:
            continue
        if "://" in extra:
            targets.append((urlparse(extra).path or "/", extra))
        else:
            if not extra.startswith("/"):
                extra = "/" + extra
            targets.append((extra, urljoin(base, extra)))
    return targets


def _http_fetcher(base: str) -> FetchImage:
    from urllib.parse import urljoin
    from urllib.request import Request, urlopen

    def fetch(src: str) -> bytes | None:
        target = src if "://" in src else urljoin(base, src)
        try:
            request = Request(target, headers={"User-Agent": "luvatrix-capture"})
            with urlopen(request, timeout=30) as response:
                return response.read()
        except OSError:
            return None

    return fetch


async def _grow_viewport_to_content(page: Any, width: int, scale: float) -> None:
    size = await page.evaluate(
        "[document.documentElement.scrollWidth, document.documentElement.scrollHeight]"
    )
    if isinstance(size, list) and len(size) == 2:
        content_w, content_h = int(size[0] or 0), int(size[1] or 0)
        if content_h > 0:
            await page.set_viewport(max(width, content_w), content_h, scale)
            await page.ready(timeout=5.0)


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


async def _scroll_through_page(page: Any) -> None:
    """Scroll to the bottom and back so lazy content and reveal animations fire."""
    step = await page.evaluate("window.innerHeight || 800") or 800
    height = await page.evaluate("document.documentElement.scrollHeight") or 0
    position = 0
    while position < height:
        position += int(step)
        await page.evaluate(f"window.scrollTo(0, {position})")
        await _sleep(0.15)
    await page.evaluate("window.scrollTo(0, 0)")
    await _sleep(0.3)


async def _rasterize_placeholders(page: Any, result: CaptureResult) -> None:
    for entry in result.svg_raster:
        data = await page.screenshot(clip=dict(entry["box"]), scale=2.0)
        ref = "svg-" + sha1(entry["key"].encode("utf-8")).hexdigest()[:12]
        result.images[ref] = {"url": f"rasterized:{entry['key']}", "data": data}
        entry["node"]["fills"] = [{"type": "IMAGE", "imageRef": ref, "scaleMode": "FILL"}]


def capture_design(
    url: str,
    out_dir: str | Path,
    *,
    pages: Sequence[str] = (),
    click_map_path: str | Path | None = None,
    viewport: str = "393x852@3",
    wait: float = 2.0,
    selector_ready: str | None = None,
    full_page: bool = False,
    chrome_path: str | None = None,
) -> CaptureResult:
    """Capture `url` (plus extra pages) with headless Chrome and compile to Figma."""
    import asyncio

    from . import cdp

    width, height, scale = parse_viewport(viewport)
    click_map = _load_click_map(click_map_path)

    async def run() -> CaptureResult:
        chrome = cdp.Chrome.launch(chrome_path)
        try:
            conn = await cdp.CDPConnection.connect(chrome.ws_url)
            page = await cdp.CDPPage.attach(conn)
            await page.set_viewport(width, height, scale)
            snapshots = []
            pseudos: list[list[dict[str, Any]]] = []
            for path, target in _page_targets(url, pages):
                await page.navigate(target)
                await page.ready(timeout=max(wait + 10.0, 12.0), extra_delay=wait)
                if selector_ready:
                    await page.wait_for_selector(selector_ready, timeout=max(wait, 10.0))
                if full_page:
                    await _scroll_through_page(page)
                    await _grow_viewport_to_content(page, width, scale)
                    await _sleep(wait)
                snapshots.append((path, await page.capture_snapshot()))
                try:
                    raw = await page.evaluate(PSEUDO_SCAN_JS)
                except Exception:
                    raw = None
                pseudos.append(list(raw) if isinstance(raw, list) else [])
            result = compile_snapshots(snapshots, click_map=click_map, fetcher=_http_fetcher(url), pseudos=pseudos)
            await _rasterize_placeholders(page, result)
            return result
        finally:
            chrome.close()

    result = asyncio.run(run())
    write_capture(result, out_dir)
    return result
