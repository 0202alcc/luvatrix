"""Builders for canned CDP `DOMSnapshot.captureSnapshot` fixtures.

The tests never launch a browser: these helpers produce snapshot payloads in
the exact wire format Chrome emits (top-level `strings` table, sparse
`{"index": [...], "value": [...]}` arrays, layout styles aligned to the
requested computed-style property list).
"""

from __future__ import annotations

from typing import Any

from luvatrix_ui.figma.cdp import STYLE_PROPS

# Computed-style defaults that mirror Chrome for properties a fixture does not
# set explicitly, keyed by property name.
DEFAULT_STYLES: dict[str, str] = {
    "display": "block",
    "position": "static",
    "visibility": "visible",
    "background-color": "rgba(0, 0, 0, 0)",
    "background-image": "none",
    "color": "rgb(0, 0, 0)",
    "font-family": "sans-serif",
    "font-size": "16px",
    "font-weight": "400",
    "font-style": "normal",
    "line-height": "normal",
    "letter-spacing": "normal",
    "text-transform": "none",
    "text-decoration": "none",
    "text-align": "start",
    "overflow-x": "visible",
    "overflow-y": "visible",
    "mix-blend-mode": "normal",
    "backdrop-filter": "none",
    "filter": "none",
    "z-index": "auto",
    "opacity": "1",
    "border-radius": "0px",
    "border-top-left-radius": "0px",
    "border-top-right-radius": "0px",
    "border-bottom-right-radius": "0px",
    "border-bottom-left-radius": "0px",
    "box-shadow": "none",
    "width": "0px",
    "height": "0px",
    "border-width": "0px",
    "border-style": "none",
    "border-color": "rgb(0, 0, 0)",
    "border-top-width": "0px",
    "border-top-style": "none",
    "border-top-color": "rgb(0, 0, 0)",
    "border-right-width": "0px",
    "border-right-style": "none",
    "border-right-color": "rgb(0, 0, 0)",
    "border-bottom-width": "0px",
    "border-bottom-style": "none",
    "border-bottom-color": "rgb(0, 0, 0)",
    "border-left-width": "0px",
    "border-left-style": "none",
    "border-left-color": "rgb(0, 0, 0)",
}

ELEMENT, TEXT_NODE = 1, 3


class SnapshotBuilder:
    """Builds a DOMSnapshot payload from a compact node/layout description."""

    def __init__(self, *, title: str = "Test Page", url: str = "https://test.example/", content_size: tuple[float, float] = (393, 852)) -> None:
        self.title = title
        self.url = url
        self.content_size = content_size
        self._strings: list[str] = []
        self._string_ids: dict[str, int] = {}
        self._nodes: list[dict[str, Any]] = []
        self._layout: list[dict[str, Any]] = []
        self._text_boxes: list[tuple[int, float, float, float, float, int, int]] = []
        self._clickable: list[int] = []
        self._backend = 9000

    # ── node construction ────────────────────────────────────────────────────

    def element(
        self,
        tag: str,
        *,
        parent: int | None = None,
        attrs: dict[str, str] | None = None,
        text: str | None = None,
        clickable: bool = False,
    ) -> int:
        """Add an element (nodeType 1); `text` adds a child #text node."""
        node = self._add_node(tag, ELEMENT, parent, attrs or {}, clickable)
        if text is not None:
            self._add_text_node(text, parent=node)
        return node

    def text(self, value: str, *, parent: int) -> int:
        return self._add_text_node(value, parent)

    def _add_node(self, tag: str, node_type: int, parent: int | None, attrs: dict[str, str], clickable: bool) -> int:
        index = len(self._nodes)
        self._nodes.append(
            {
                "tag": tag,
                "nodeType": node_type,
                "parent": -1 if parent is None else parent,
                "attrs": attrs,
                "textValue": None,
                "backend": self._backend + index,
                "clickable": clickable,
            }
        )
        if clickable:
            self._clickable.append(index)
        return index

    def _add_text_node(self, value: str, parent: int) -> int:
        return self._add_node("#text", TEXT_NODE, parent, {}, False, text_value=value)

    # ── layout construction ──────────────────────────────────────────────────

    def layout(self, node_index: int, x: float, y: float, w: float, h: float, **styles: str) -> int:
        """Give `node_index` a layout box and computed styles (prop names with dashes)."""
        li = len(self._layout)
        self._layout.append({"node": node_index, "bounds": [x, y, w, h], "styles": {**DEFAULT_STYLES, **styles}})
        return li

    def text_box(self, layout_index: int, x: float, y: float, w: float, h: float, *, start: int = 0, length: int | None = None) -> None:
        self._text_boxes.append((layout_index, x, y, w, h, start, -1 if length is None else length))

    # ── serialization ────────────────────────────────────────────────────────

    def _sid(self, value: str) -> int:
        if value not in self._string_ids:
            self._string_ids[value] = len(self._strings)
            self._strings.append(value)
        return self._string_ids[value]

    def build(self) -> dict[str, Any]:
        count = len(self._nodes)
        parent_index = [n["parent"] for n in self._nodes]
        node_type = [n["nodeType"] for n in self._nodes]
        node_name = [self._sid(n["tag"]) for n in self._nodes]
        node_value = [self._sid("") for _ in range(count)]
        backend = [n["backend"] for n in self._nodes]
        attributes = []
        for n in self._nodes:
            flat: list[int] = []
            for key, value in n["attrs"].items():
                flat.extend([self._sid(key), self._sid(value)])
            attributes.append(flat)
        text_value: dict[str, Any] | None = None
        if any(n["textValue"] is not None for n in self._nodes):
            idxs, values = [], []
            for i, n in enumerate(self._nodes):
                if n["textValue"] is not None:
                    idxs.append(i)
                    values.append(self._sid(n["textValue"]))
            text_value = {"index": idxs, "value": values}

        node_of_layout = [entry["node"] for entry in self._layout]
        layout_of_node = {node: li for li, node in enumerate(node_of_layout)}
        bounds = [list(entry["bounds"]) for entry in self._layout]
        styles = []
        for entry in self._layout:
            values = [self._sid(entry["styles"].get(prop, DEFAULT_STYLES[prop])) for prop in STYLE_PROPS]
            styles.append(values)
        layout_text = []
        for li, entry in enumerate(self._layout):
            node = entry["node"]
            text = self._nodes[node]["textValue"] if self._nodes[node]["nodeType"] == TEXT_NODE else ""
            layout_text.append(self._sid(text))
        text_boxes: dict[str, list[Any]] | None = None
        if self._text_boxes:
            text_boxes = {
                "layoutIndex": [tb[0] for tb in self._text_boxes],
                "bounds": [[tb[1], tb[2], tb[3], tb[4]] for tb in self._text_boxes],
                "start": [tb[5] for tb in self._text_boxes],
                "length": [tb[6] for tb in self._text_boxes],
            }
        clickable = {"index": list(self._clickable)} if self._clickable else None
        nodes_payload = self._sparse(
            parentIndex=parent_index,
            nodeType=node_type,
            nodeName=node_name,
            nodeValue=node_value,
            backendNodeId=backend,
            attributes=attributes,
        )
        if text_value:
            nodes_payload["textValue"] = text_value
        if clickable:
            nodes_payload["isClickable"] = clickable

        return {
            "strings": self._strings,
            "documents": [
                {
                    "title": self.title,
                    "documentURL": self.url,
                    "contentWidth": self.content_size[0],
                    "contentHeight": self.content_size[1],
                    "nodes": nodes_payload,
                    "layout": {
                        "nodeIndex": node_of_layout,
                        "bounds": bounds,
                        "styles": styles,
                        "text": layout_text,
                    },
                    **({"textBoxes": text_boxes} if text_boxes else {}),
                }
            ],
        }

    @staticmethod
    def _sparse(**columns: list[Any]) -> dict[str, Any]:
        return columns