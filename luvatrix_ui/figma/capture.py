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
from pathlib import Path
import re
from typing import Any

from .cdp import STYLE_PROPS
from .geometry import PathError, Segment, parse_path

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

    def build_children(self, node: int, inside_text: bool = False) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for child in self.model.children(node):
            out.extend(self.build_node(child, inside_text=inside_text))
        return out

    def build_node(self, node: int, inside_text: bool = False) -> list[dict[str, Any]]:
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
        runs = self.text_runs(node)
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
            sequence = self._text_container_sequence(node, element_children, wrapped)
            if wrapped:
                return [self.box_node(node, box, styles, sequence, paint, [])]
            if len(sequence) == 1:
                self._register_node(node, sequence[0])
            return sequence
        children = self.build_children(node, inside_text=bool(runs))
        if children or paint or has_border or has_shadow or keep_leaf:
            return [self.box_node(node, box, styles, children, paint, runs)]
        if runs:
            return [self.text_node(node, box, styles, runs)]
        self.skip("empty", node)
        return []

    def _text_container_sequence(self, node: int, element_children: list[int], wrapped: bool) -> list[dict[str, Any]]:
        """Interleave text chunks and own-node inline children in DOM order."""
        runs = self.text_runs(node)
        own: dict[int, list[dict[str, Any]]] = {}
        for child in element_children:
            if self._inline_is_own_node(child):
                own[child] = self.build_node(child, inside_text=False)
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
            result.append(self.text_node(node, box, styles, payload, node_id=node_id, register=False))
        return result

    def box_node(
        self,
        node: int,
        box: list[float],
        styles: dict[str, str],
        children: list[dict[str, Any]],
        paint: list[dict[str, Any]],
        runs: list[_Run],
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
                    self.text_node(node, box, styles, runs, node_id=f"{out['id']}:t1", register=False)
                )
            else:
                out["type"] = "FRAME"
                out["children"] = [self.text_node(node, box, styles, runs, node_id=f"{out['id']}:t1", register=False)]
        self.counts["frames" if out["type"] == "FRAME" else "rectangles"] += 1
        self._register_node(node, out)
        return out

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

    def text_runs(self, node: int, top: int = -1) -> list[_Run]:
        runs: list[_Run] = []
        for child in self.model.children(node):
            kind = self.model.node_type[child]
            if kind == 3:
                li = self.model.layout_index(child)
                text = ""
                if li is not None and li < len(self.model.layout_text):
                    text = self.model.layout_text[li]
                if not text:
                    text = self.model.node_text(child)
                if not text.strip():
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
                    runs.extend(self.text_runs(child, top if top >= 0 else child))
        return runs

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
    ) -> dict[str, Any]:
        chars: list[str] = []
        run_of: list[int] = []
        for run_index, run in enumerate(runs):
            collapsed = re.sub(r"\s+", " ", run.text)
            if collapsed == " " and (not chars or chars[-1] == " " or chars[-1] == "\n"):
                continue
            for ch in collapsed:
                chars.append(ch)
                run_of.append(run_index)
        characters = "".join(chars).strip()
        base = _text_style(styles)
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
        local = self._text_box(runs, box)
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

    def _table_key(self, table: dict[str, dict[str, Any]], override: dict[str, Any]) -> int:
        for key, value in table.items():
            if value == override:
                return int(key)
        next_key = len(table) + 1
        table[str(next_key)] = override
        return next_key

    def _text_box(self, runs: list[_Run], box: list[float]) -> dict[str, float]:
        points = [bounds for run in runs for bounds in run.boxes]
        if not points:
            return self.local_box(box)
        x0 = min(p[0] for p in points)
        y0 = min(p[1] for p in points)
        x1 = max(p[0] + p[2] for p in points)
        y1 = max(p[1] + p[3] for p in points)
        return self.local_box([x0, y0, x1 - x0, y1 - y0])

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
    ) -> tuple[int, list[dict[str, Any]]]:
        mapped, unmatched = 0, []
        for key, target_path in click_map.items():
            page, separator, selector = key.partition("->")
            if not separator:
                continue
            if page.strip() != self.path:
                continue
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
    if lowered.startswith("linear-gradient("):
        paint = _gradient_paint("GRADIENT_LINEAR", layer, box)
        return [paint] if paint else []
    if lowered.startswith("radial-gradient("):
        paint = _gradient_paint("GRADIENT_RADIAL", layer, box)
        return [paint] if paint else []
    return []


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
) -> CaptureResult:
    """Compile captured DOMSnapshot payloads into a Figma file payload."""
    clickables: list[dict[str, Any]] = []
    images: dict[str, dict[str, Any]] = {}
    page_reports: list[dict[str, Any]] = []
    compilers: list[_PageCompiler] = []
    frames: list[dict[str, Any]] = []
    offset_x = 0.0
    for page_index, (path, snapshot) in enumerate(pages):
        model = SnapshotModel(snapshot, props)
        report_page: dict[str, Any] = {"path": path, "title": model.title}
        compiler = _PageCompiler(model, page_index=page_index, path=path, fetcher=fetcher, rasterize=rasterize, images=images)
        frame = compiler.build()
        width = frame["absoluteBoundingBox"]["width"]
        frame["absoluteBoundingBox"]["x"] = offset_x
        for child in walk_all(frame):
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
            }
        )
        page_reports.append(report_page)
    mapped_total, unmatched_total = 0, []
    if click_map:
        frames_by_path = {path: frame for (path, _snapshot), frame in zip(pages, frames)}
        for compiler in compilers:
            mapped, unmatched = compiler.apply_click_map(click_map, frames_by_path)
            mapped_total += mapped
            unmatched_total.extend(unmatched)
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
        "images": {
            "downloaded": len(images),
            "failed": sorted({url for page in page_reports for url in page.get("images", {}).get("failed", ())}),
        },
        "interactions": {"mapped": mapped_total, "unmatched": unmatched_total},
    }
    svg_raster = [
        {"node": node, "box": box, "key": f"{compilers[index].path}:{node['id']}"}
        for index, compiler in enumerate(compilers)
        for node, box in compiler.svg_placeholders
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
            for path, target in _page_targets(url, pages):
                await page.navigate(target)
                await page.ready(timeout=max(wait + 10.0, 12.0), extra_delay=wait)
                if selector_ready:
                    await page.wait_for_selector(selector_ready, timeout=max(wait, 10.0))
                if full_page:
                    await _grow_viewport_to_content(page, width, scale)
                snapshots.append((path, await page.capture_snapshot()))
            result = compile_snapshots(snapshots, click_map=click_map, fetcher=_http_fetcher(url))
            await _rasterize_placeholders(page, result)
            return result
        finally:
            chrome.close()

    result = asyncio.run(run())
    write_capture(result, out_dir)
    return result
