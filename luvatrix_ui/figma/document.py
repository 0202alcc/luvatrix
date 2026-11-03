from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .geometry import Affine

FRAME_TYPES = frozenset({"FRAME", "COMPONENT", "COMPONENT_SET", "INSTANCE"})
# Groups and boolean operations do not establish a coordinate space: their
# children's relativeTransform is relative to the nearest frame-like ancestor.
TRANSPARENT_CONTAINERS = frozenset({"GROUP", "BOOLEAN_OPERATION"})
TAP_TRIGGERS = frozenset({"ON_CLICK", "ON_PRESS"})


class FigmaFormatError(ValueError):
    """The payload is not a Figma REST file or nodes response we can render."""


@dataclass(frozen=True)
class NavigateAction:
    destination_id: str


@dataclass(frozen=True)
class BackAction:
    pass


@dataclass(frozen=True)
class UrlAction:
    url: str


Action = NavigateAction | BackAction | UrlAction


@dataclass(frozen=True)
class Frame:
    id: str
    name: str
    node: dict[str, Any]
    origin_x: float
    origin_y: float
    width: float
    height: float


@dataclass(frozen=True)
class Hotspot:
    node_id: str
    node_name: str
    x: float
    y: float
    width: float
    height: float
    action: Action | None

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x <= self.x + self.width and self.y <= y <= self.y + self.height


def is_visible(node: dict[str, Any]) -> bool:
    return node.get("visible", True) is not False


def node_size(node: dict[str, Any]) -> tuple[float, float]:
    size = node.get("size")
    if isinstance(size, dict):
        return float(size.get("x", 0.0)), float(size.get("y", 0.0))
    bbox = node.get("absoluteBoundingBox") or {}
    return float(bbox.get("width", 0.0)), float(bbox.get("height", 0.0))


def node_transform(node: dict[str, Any], container: Affine, frame: Frame) -> Affine:
    """Frame-local transform of `node`, given its container's frame-local transform."""
    rel = node.get("relativeTransform")
    if isinstance(rel, list) and len(rel) == 2 and "size" in node:
        try:
            return container @ Affine.from_figma(rel)
        except (TypeError, ValueError, IndexError):
            pass
    bbox = node.get("absoluteBoundingBox") or {}
    return Affine.translate(float(bbox.get("x", 0.0)) - frame.origin_x, float(bbox.get("y", 0.0)) - frame.origin_y)


def walk(frame: Frame) -> Iterator[tuple[dict[str, Any], Affine]]:
    """Yield visible descendants of `frame` in paint order with frame-local transforms."""

    def _walk(node: dict[str, Any], container: Affine) -> Iterator[tuple[dict[str, Any], Affine]]:
        for child in node.get("children") or ():
            if not is_visible(child):
                continue
            tf = node_transform(child, container, frame)
            yield child, tf
            yield from _walk(child, container if child.get("type") in TRANSPARENT_CONTAINERS else tf)

    yield from _walk(frame.node, Affine.identity())


class FigmaDocument:
    def __init__(self, data: dict[str, Any], *, base_dir: Path | None = None, start: str | None = None) -> None:
        if not isinstance(data, dict):
            raise FigmaFormatError("Figma payload must be a JSON object")
        self.name = str(data.get("name", "Untitled"))
        self.base_dir = Path(base_dir) if base_dir is not None else None
        self._nodes: dict[str, dict[str, Any]] = {}
        self._owner_frame: dict[str, str] = {}
        self._hotspots: dict[str, list[Hotspot]] = {}
        self.background_rgba: tuple[float, float, float, float] | None = None
        flow_ids: list[str] = []
        self.frames: list[Frame] = []
        for top in self._top_level_nodes(data, flow_ids):
            self._add_frame(top)
        if not self.frames:
            raise FigmaFormatError("Figma payload has no top-level frames to render")
        self._frames_by_id = {frame.id: frame for frame in self.frames}
        if start is not None:
            self.start_frame_id = self._resolve_frame(start).id
        else:
            flow_start = next((fid for fid in flow_ids if fid in self._frames_by_id), None)
            self.start_frame_id = flow_start or self.frames[0].id

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, base_dir: Path | None = None, start: str | None = None) -> "FigmaDocument":
        return cls(data, base_dir=base_dir, start=start)

    @classmethod
    def load(cls, path: str | Path, *, start: str | None = None) -> "FigmaDocument":
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise FigmaFormatError(f"{path} is not valid JSON: {exc}") from exc
        return cls(data, base_dir=path.parent, start=start)

    def _top_level_nodes(self, data: dict[str, Any], flow_ids: list[str]) -> Iterator[dict[str, Any]]:
        if isinstance(data.get("nodes"), dict):
            for entry in data["nodes"].values():
                root = (entry or {}).get("document")
                if isinstance(root, dict):
                    yield from self._frames_under(root, flow_ids)
            return
        root = data.get("document", data)
        if not isinstance(root, dict):
            raise FigmaFormatError("Figma payload has no document node")
        yield from self._frames_under(root, flow_ids)

    def _frames_under(self, root: dict[str, Any], flow_ids: list[str]) -> Iterator[dict[str, Any]]:
        node_type = root.get("type")
        if node_type in FRAME_TYPES:
            yield root
            return
        if node_type == "CANVAS":
            if self.background_rgba is None and isinstance(root.get("backgroundColor"), dict):
                color = root["backgroundColor"]
                self.background_rgba = tuple(float(color.get(k, 1.0 if k == "a" else 0.0)) for k in "rgba")  # type: ignore[assignment]
            for point in root.get("flowStartingPoints") or ():
                if isinstance(point, dict) and point.get("nodeId"):
                    flow_ids.append(str(point["nodeId"]))
        for child in root.get("children") or ():
            if not isinstance(child, dict) or not is_visible(child):
                continue
            if child.get("type") in FRAME_TYPES:
                yield child
            elif child.get("type") in {"CANVAS", "DOCUMENT", "SECTION"}:
                yield from self._frames_under(child, flow_ids)

    def _add_frame(self, node: dict[str, Any]) -> None:
        bbox = node.get("absoluteBoundingBox") or {}
        width, height = node_size(node)
        frame = Frame(
            id=str(node.get("id", f"frame-{len(self.frames)}")),
            name=str(node.get("name", "")),
            node=node,
            origin_x=float(bbox.get("x", 0.0)),
            origin_y=float(bbox.get("y", 0.0)),
            width=max(1.0, width),
            height=max(1.0, height),
        )
        self.frames.append(frame)
        stack = [node]
        while stack:
            current = stack.pop()
            node_id = current.get("id")
            if node_id is not None:
                self._nodes[str(node_id)] = current
                self._owner_frame[str(node_id)] = frame.id
            stack.extend(child for child in current.get("children") or () if isinstance(child, dict))

    def _resolve_frame(self, key: str) -> Frame:
        if key in self._frames_by_id:
            return self._frames_by_id[key]
        for frame in self.frames:
            if frame.name == key:
                return frame
        names = ", ".join(repr(frame.name) for frame in self.frames)
        raise FigmaFormatError(f"unknown frame {key!r}; available frames: {names}")

    def frame(self, frame_id: str) -> Frame:
        return self._frames_by_id[frame_id]

    def frame_by_name(self, name: str) -> Frame:
        for frame in self.frames:
            if frame.name == name:
                return frame
        raise KeyError(name)

    def find_frame(self, key: str) -> Frame:
        """Look up a frame by id or name."""
        if key in self._frames_by_id:
            return self._frames_by_id[key]
        return self.frame_by_name(key)

    def node(self, node_id: str) -> dict[str, Any]:
        return self._nodes[node_id]

    def owner_frame_id(self, node_id: str) -> str | None:
        return self._owner_frame.get(node_id)

    def image_path(self, image_ref: str) -> Path | None:
        if self.base_dir is None:
            return None
        images = self.base_dir / "images"
        for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            candidate = images / f"{image_ref}{ext}"
            if candidate.exists():
                return candidate
        return None

    def hotspots(self, frame_id: str) -> list[Hotspot]:
        cached = self._hotspots.get(frame_id)
        if cached is not None:
            return cached
        frame = self.frame(frame_id)
        spots: list[Hotspot] = []
        for node, tf in walk(frame):
            action = self._tap_action(node)
            if action is None:
                continue
            width, height = node_size(node)
            x0, y0, x1, y1 = tf.bounds(0.0, 0.0, width, height)
            spots.append(
                Hotspot(
                    node_id=str(node.get("id", "")),
                    node_name=str(node.get("name", "")),
                    x=x0,
                    y=y0,
                    width=x1 - x0,
                    height=y1 - y0,
                    action=action,
                )
            )
        self._hotspots[frame_id] = spots
        return spots

    def hit_test(self, frame_id: str, x: float, y: float) -> Hotspot | None:
        for spot in reversed(self.hotspots(frame_id)):
            if spot.contains(x, y):
                return spot
        return None

    def _tap_action(self, node: dict[str, Any]) -> Action | None:
        for interaction in node.get("interactions") or ():
            trigger = (interaction or {}).get("trigger") or {}
            if trigger.get("type") not in TAP_TRIGGERS:
                continue
            for action in interaction.get("actions") or ():
                resolved = self._resolve_action(action or {})
                if resolved is not None:
                    return resolved
        legacy = node.get("transitionNodeID")
        if legacy:
            return self._navigate_to(str(legacy))
        return None

    def _resolve_action(self, action: dict[str, Any]) -> Action | None:
        kind = action.get("type")
        if kind in {"BACK", "CLOSE"}:
            return BackAction()
        if kind == "URL" and action.get("url"):
            return UrlAction(str(action["url"]))
        if kind == "NODE" and action.get("destinationId"):
            if action.get("navigation", "NAVIGATE") in {"NAVIGATE", "SWAP", "OVERLAY"}:
                return self._navigate_to(str(action["destinationId"]))
        return None

    def _navigate_to(self, node_id: str) -> NavigateAction | None:
        frame_id = self._owner_frame.get(node_id)
        return NavigateAction(frame_id) if frame_id is not None else None
