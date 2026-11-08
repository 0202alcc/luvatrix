"""Reference Figma-to-container importer.

Compiles a Figma REST-style document JSON into a Luvatrix app container
payload (see `luvatrix_ui.planes_container`). The importer covers a
deliberate reference subset:

1. Top-level `FRAME` nodes on each `CANVAS` page become one plane and one
   route each. Route ids are slugs of the frame names.
2. The page-level `prototypeStartNodeID` (when it matches a top-level frame)
   selects the default/entry route; otherwise the first frame is the entry.
3. `TEXT` nodes become `text` components with pixel sizes and hex colors.
4. Shape nodes (`RECTANGLE`, `ELLIPSE`, and child `FRAME` leaves) become
   `svg` components backed by generated SVG markup returned in
   `FigmaImportResult.assets` for the caller to materialize on disk.
5. Node prototype `interactions` with `NODE` actions become route
   transitions (`navigate_<target_route>` triggers) with mapped kinds and
   easings.

Figma coordinates share the screen top-left origin, so absolute bounding
boxes map directly to `screen_tl` positions relative to the parent frame.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .planes_container import (
    EASINGS,
    TRANSITION_KINDS,
    CONTAINER_PROTOCOL_VERSION,
    PLANES_PROTOCOL_VERSION_DEFAULT,
)

_FIGMA_TRANSITION_KINDS: dict[str, str] = {
    "NO_EASING": "none",
    "DISSOLVE": "fade",
    "SMART_ANIMATE": "fade",
    "SCROLL_ANIMATE": "none",
    "MOVE_IN_LEFT": "slide_left",
    "MOVE_IN_RIGHT": "slide_right",
    "MOVE_IN_TOP": "slide_up",
    "MOVE_IN_BOTTOM": "slide_down",
    "MOVE_OUT_LEFT": "slide_left",
    "MOVE_OUT_RIGHT": "slide_right",
    "MOVE_OUT_TOP": "slide_up",
    "MOVE_OUT_BOTTOM": "slide_down",
}

_FIGMA_EASINGS: dict[str, str] = {
    "LINEAR": "linear",
    "EASE_IN": "ease_in",
    "EASE_OUT": "ease_out",
    "EASE_IN_AND_OUT": "ease_in_out",
    "EASE_IN_OUT": "ease_in_out",
}

_SHAPE_NODE_TYPES = frozenset({"RECTANGLE", "ELLIPSE", "POLYGON", "STAR", "LINE", "VECTOR"})

_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class FigmaImportResult:
    container_payload: dict[str, Any]
    assets: dict[str, str]
    warnings: tuple[str, ...]


def import_figma_document(document: Mapping[str, Any]) -> FigmaImportResult:
    if not isinstance(document, Mapping):
        raise ValueError("figma document must be an object")
    root = document.get("document")
    if not isinstance(root, Mapping):
        raise ValueError("figma document must contain a `document` node")

    warnings: list[str] = []
    planes: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    components: list[dict[str, Any]] = []
    assets: dict[str, str] = {}
    frame_id_to_route: dict[str, str] = {}
    entry_route: str | None = None

    for page in _walk_pages(root):
        page_start = page.get("prototypeStartNodeID")
        frames = [child for child in _children(page) if _node_type(child) in ("FRAME", "INSTANCE")]
        for frame in frames:
            route_id = _slug(frame.get("name"))
            plane_id = f"plane_{route_id}"
            frame_id_to_route[str(frame.get("id"))] = route_id
            planes.append(
                {
                    "id": plane_id,
                    "default_frame": "screen_tl",
                    "background": {"color": _background_color(frame)},
                    "plane_global_z": 0,
                    "position": {"x": 0, "y": 0, "frame": "screen_tl"},
                    "size": _plane_size(frame),
                }
            )
            routes.append({"id": route_id, "active_planes": [plane_id]})
            if page_start is not None and str(page_start) == str(frame.get("id")):
                entry_route = route_id
            _import_frame_tree(frame, plane_id, components, assets, warnings)

    if entry_route is None and routes:
        entry_route = routes[0]["id"]
    if not routes:
        raise ValueError("figma document contains no top-level FRAME nodes")
    for route in routes:
        if route["id"] == entry_route:
            route["default"] = True
            break

    _import_interactions(_collect_interactions(_pages_frames(root)), routes, frame_id_to_route, warnings)

    app_name = document.get("name")
    payload: dict[str, Any] = {
        "container_protocol_version": CONTAINER_PROTOCOL_VERSION,
        "planes_protocol_version": PLANES_PROTOCOL_VERSION_DEFAULT,
        "app": {
            "id": _slug(app_name) or "imported_app",
            "title": str(app_name or "Imported App"),
            "icon": "assets/icon.svg",
            "web": {"tab_title": None, "tab_icon": None},
        },
        "planes": planes,
        "routes": routes,
        "scripts": [],
        "components": components,
        "animations": [],
    }
    return FigmaImportResult(
        container_payload=payload,
        assets=assets,
        warnings=tuple(warnings),
    )


def _walk_pages(root: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    pages: list[Mapping[str, Any]] = []
    for child in _children(root):
        if _node_type(child) == "CANVAS":
            pages.append(child)
    if not pages and _node_type(root) == "CANVAS":
        pages.append(root)
    return pages


def _pages_frames(root: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    frames: list[Mapping[str, Any]] = []
    for page in _walk_pages(root):
        for child in _children(page):
            if _node_type(child) in ("FRAME", "INSTANCE"):
                frames.append(child)
    return frames


def _import_frame_tree(
    frame: Mapping[str, Any],
    plane_id: str,
    components: list[dict[str, Any]],
    assets: dict[str, str],
    warnings: list[str],
    parent_origin: tuple[float, float] = (0.0, 0.0),
    *,
    is_top_level: bool = True,
    fallback_origin: tuple[float, float] | None = None,
) -> None:
    origin = _absolute_origin(frame)
    if fallback_origin is not None and not _bounds(frame):
        origin = fallback_origin
    if not is_top_level:
        relative_origin = (origin[0] - parent_origin[0], origin[1] - parent_origin[1])
        components.append(
            _shape_component(
                frame,
                plane_id,
                relative_origin,
                assets,
            )
        )
    computed_offsets = _auto_layout_child_offsets(frame, origin)
    for child in _children(frame):
        node_type = _node_type(child)
        child_fallback = computed_offsets.get(str(child.get("id")))
        if node_type == "TEXT":
            components.append(
                _text_component(child, plane_id, origin, fallback_origin=child_fallback)
            )
        elif node_type in _SHAPE_NODE_TYPES or node_type in ("FRAME", "INSTANCE"):
            _import_frame_tree(
                child,
                plane_id,
                components,
                assets,
                warnings,
                parent_origin=origin,
                is_top_level=False,
                fallback_origin=child_fallback,
            )
        else:
            warnings.append(f"skipped unsupported node type `{node_type}` ({child.get('id')})")


def _auto_layout_child_offsets(
    frame: Mapping[str, Any],
    frame_origin: tuple[float, float],
) -> dict[str, tuple[float, float]]:
    """Compute absolute origins for auto-layout children lacking bounds.

    Figma's REST API resolves auto-layout into `absoluteBoundingBox`, but
    plugin/file JSON exports may omit bounds on stacked children. When the
    frame declares `layoutMode`, stack children along the primary axis from
    the padding origin with `itemSpacing` gaps.
    """
    layout_mode = str(frame.get("layoutMode", "NONE"))
    if layout_mode not in ("HORIZONTAL", "VERTICAL"):
        return {}
    horizontal = layout_mode == "HORIZONTAL"
    spacing = float(frame.get("itemSpacing", 0) or 0)
    cursor = (
        frame_origin[0] + float(frame.get("paddingLeft", 0) or 0),
        frame_origin[1] + float(frame.get("paddingTop", 0) or 0),
    )
    offsets: dict[str, tuple[float, float]] = {}
    for child in _children(frame):
        if _bounds(child):
            continue
        offsets[str(child.get("id"))] = cursor
        size = _node_size(child)
        if horizontal:
            cursor = (cursor[0] + size[0] + spacing, cursor[1])
        else:
            cursor = (cursor[0], cursor[1] + size[1] + spacing)
    return offsets


def _node_size(node: Mapping[str, Any]) -> tuple[float, float]:
    bounds = _bounds(node)
    width = node.get("width", bounds.get("width"))
    height = node.get("height", bounds.get("height"))
    return (max(0.0, float(width or 0.0)), max(0.0, float(height or 0.0)))


def _collect_interactions(frames: list[Mapping[str, Any]]) -> list[tuple[str, Mapping[str, Any]]]:
    collected: list[tuple[str, Mapping[str, Any]]] = []
    for frame in frames:
        frame_id = str(frame.get("id"))
        _collect_interactions_recursive(frame, frame_id, collected)
    return collected


def _collect_interactions_recursive(
    node: Mapping[str, Any],
    top_frame_id: str,
    collected: list[tuple[str, Mapping[str, Any]]],
) -> None:
    interactions = node.get("interactions")
    if isinstance(interactions, list):
        for interaction in interactions:
            if isinstance(interaction, Mapping):
                collected.append((top_frame_id, interaction))
    for child in _children(node):
        _collect_interactions_recursive(child, top_frame_id, collected)


def _import_interactions(
    collected: list[tuple[str, Mapping[str, Any]]],
    routes: list[dict[str, Any]],
    frame_id_to_route: dict[str, str],
    warnings: list[str],
) -> None:
    routes_by_id = {route["id"]: route for route in routes}
    for source_frame_id, interaction in collected:
        source_route_id = frame_id_to_route.get(source_frame_id)
        source_route = routes_by_id.get(source_route_id or "")
        if source_route is None:
            continue
        actions = interaction.get("actions")
        if not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, Mapping) or action.get("type") != "NODE":
                continue
            destination = action.get("destinationId")
            target_route = frame_id_to_route.get(str(destination))
            if target_route is None:
                warnings.append(f"interaction targets unknown frame `{destination}`")
                continue
            trigger = f"navigate_{target_route}"
            transition = action.get("transition") if isinstance(action.get("transition"), Mapping) else {}
            kind = _FIGMA_TRANSITION_KINDS.get(str(transition.get("type", "NO_EASING")), "fade")
            if kind not in TRANSITION_KINDS:
                kind = "fade"
            duration_ms = int(round(float(transition.get("duration", 0.2)) * 1000)) or 200
            easing_raw = transition.get("easing")
            easing = "ease_in_out"
            if isinstance(easing_raw, Mapping):
                easing = _FIGMA_EASINGS.get(str(easing_raw.get("type", "")), "ease_in_out")
            if easing not in EASINGS:
                easing = "ease_in_out"
            source_route.setdefault("transitions", []).append(
                {
                    "trigger": trigger,
                    "to_route": target_route,
                    "kind": kind,
                    "duration_ms": duration_ms,
                    "easing": easing,
                }
            )


def _text_component(
    node: Mapping[str, Any],
    plane_id: str,
    parent_origin: tuple[float, float],
    *,
    fallback_origin: tuple[float, float] | None = None,
) -> dict[str, Any]:
    bounds = _bounds(node)
    if bounds:
        x = bounds.get("x", 0.0) - parent_origin[0]
        y = bounds.get("y", 0.0) - parent_origin[1]
    elif fallback_origin is not None:
        x = fallback_origin[0] - parent_origin[0]
        y = fallback_origin[1] - parent_origin[1]
    else:
        x, y = 0.0, 0.0
    style = node.get("style") if isinstance(node.get("style"), Mapping) else {}
    font_size = float(style.get("fontSize", 16))
    width, height = _node_size(node)
    return {
        "id": f"text_{_node_token(node)}",
        "type": "text",
        "attach_to": plane_id,
        "component_local_z": 0,
        "blend_mode": "absolute_rgba",
        "position": {"x": x, "y": y, "frame": "screen_tl"},
        "size": {
            "width": {"unit": "px", "value": width},
            "height": {"unit": "px", "value": height},
        },
        "z_index": 0,
        "props": {
            "text": str(node.get("characters", "")),
            "font": {
                "family": str(style.get("fontFamily", "Inter")),
                "file_path": None,
                "weight": int(style.get("fontWeight", 400)),
                "slant": "italic" if style.get("italic") else "regular",
            },
            "size": {"unit": "px", "value": font_size},
            "appearance": {
                "color_hex": _fill_color_hex(node, "#FFFFFF"),
                "opacity": 1.0,
                "letter_spacing_px": 0,
                "line_height_multiplier": 1.2,
                "underline": False,
                "strike": False,
            },
        },
    }


def _shape_component(
    node: Mapping[str, Any],
    plane_id: str,
    relative_origin: tuple[float, float],
    assets: dict[str, str],
) -> dict[str, Any]:
    asset_path = f"assets/svg_{_node_token(node)}.svg"
    assets[asset_path] = _shape_svg_markup(node)
    width, height = _node_size(node)
    return {
        "id": f"svg_{_node_token(node)}",
        "type": "svg",
        "attach_to": plane_id,
        "component_local_z": 0,
        "blend_mode": "absolute_rgba",
        "position": {"x": relative_origin[0], "y": relative_origin[1], "frame": "screen_tl"},
        "size": {
            "width": {"unit": "px", "value": width},
            "height": {"unit": "px", "value": height},
        },
        "z_index": 0,
        "props": {"svg": asset_path},
    }


def _shape_svg_markup(node: Mapping[str, Any]) -> str:
    width, height = _node_size(node)
    width = max(1.0, width)
    height = max(1.0, height)
    fill_attr, defs = _shape_fill(node, _node_token(node))
    radius = node.get("cornerRadius")
    rx = ""
    if isinstance(radius, (int, float)) and float(radius) > 0:
        rx = f' rx="{min(float(radius), width / 2, height / 2):.2f}"'
    if _node_type(node) == "ELLIPSE":
        shape = (
            f'<ellipse cx="{width / 2:.2f}" cy="{height / 2:.2f}" '
            f'rx="{width / 2:.2f}" ry="{height / 2:.2f}" fill="{fill_attr}"/>'
        )
    else:
        shape = f'<rect width="{width:.2f}" height="{height:.2f}"{rx} fill="{fill_attr}"/>'
    defs_markup = f"<defs>{defs}</defs>" if defs else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.2f}" height="{height:.2f}" '
        f'viewBox="0 0 {width:.2f} {height:.2f}">{defs_markup}{shape}</svg>'
    )


def _shape_fill(node: Mapping[str, Any], node_token: str) -> tuple[str, str]:
    fills = node.get("fills")
    if not isinstance(fills, list) or not fills:
        return "#CCCCCC", ""
    first = fills[0]
    if not isinstance(first, Mapping):
        return "#CCCCCC", ""
    if first.get("type") in ("GRADIENT_LINEAR", "GRADIENT_RADIAL"):
        return _gradient_fill(first, node_token)
    return _fill_color_hex(node, "#CCCCCC"), ""


def _gradient_fill(fill: Mapping[str, Any], node_token: str) -> tuple[str, str]:
    gradient_id = f"grad_{node_token}"
    stops = fill.get("gradientStops")
    stops_markup = ""
    if isinstance(stops, list):
        for stop in stops:
            if not isinstance(stop, Mapping):
                continue
            color = stop.get("color")
            if not isinstance(color, Mapping):
                continue
            r = round(float(color.get("r", 0.0)) * 255)
            g = round(float(color.get("g", 0.0)) * 255)
            b = round(float(color.get("b", 0.0)) * 255)
            alpha = float(color.get("a", 1.0))
            opacity_attr = ""
            if alpha < 1.0:
                opacity_attr = f' stop-opacity="{max(0.0, min(1.0, alpha)):.3f}"'
            stops_markup += (
                f'<stop offset="{float(stop.get("position", 0.0)):.3f}" '
                f'stop-color="#{r:02X}{g:02X}{b:02X}"{opacity_attr}/>'
            )
    if fill.get("type") == "GRADIENT_RADIAL":
        gradient = f'<radialGradient id="{gradient_id}">{stops_markup}</radialGradient>'
    else:
        handles = fill.get("gradientHandlePositions")
        x1, y1, x2, y2 = 0.0, 0.0, 1.0, 0.0
        if isinstance(handles, list) and handles:
            start = handles[0]
            # Figma handles are [start, end, width-direction]; fall back to
            # the last handle when only two are present.
            end = handles[1] if len(handles) >= 3 else handles[-1]
            if isinstance(start, Mapping) and isinstance(end, Mapping):
                x1 = float(start.get("x", 0.0))
                y1 = float(start.get("y", 0.0))
                x2 = float(end.get("x", 1.0))
                y2 = float(end.get("y", 0.0))
        gradient = (
            f'<linearGradient id="{gradient_id}" '
            f'x1="{max(0.0, min(1.0, x1)):.3f}" y1="{max(0.0, min(1.0, y1)):.3f}" '
            f'x2="{max(0.0, min(1.0, x2)):.3f}" y2="{max(0.0, min(1.0, y2)):.3f}">'
            f"{stops_markup}</linearGradient>"
        )
    return f"url(#{gradient_id})", gradient


def _background_color(frame: Mapping[str, Any]) -> str:
    return _fill_color_hex(frame, "#000000")


def _plane_size(frame: Mapping[str, Any]) -> dict[str, Any]:
    bounds = _bounds(frame)
    return {
        "width": {"unit": "px", "value": max(1.0, float(bounds.get("width", 1.0)))},
        "height": {"unit": "px", "value": max(1.0, float(bounds.get("height", 1.0)))},
    }


def _absolute_origin(node: Mapping[str, Any]) -> tuple[float, float]:
    bounds = _bounds(node)
    return (float(bounds.get("x", 0.0)), float(bounds.get("y", 0.0)))


def _bounds(node: Mapping[str, Any]) -> Mapping[str, Any]:
    bounds = node.get("absoluteBoundingBox")
    return bounds if isinstance(bounds, Mapping) else {}


def _children(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    children = node.get("children")
    if not isinstance(children, list):
        return []
    return [child for child in children if isinstance(child, Mapping)]


def _node_type(node: Mapping[str, Any]) -> str:
    return str(node.get("type", ""))


def _node_token(node: Mapping[str, Any]) -> str:
    return str(node.get("id", "node")).replace(":", "_").replace("-", "_")


def _fill_color_hex(node: Mapping[str, Any], fallback: str) -> str:
    fills = node.get("fills")
    if not isinstance(fills, list) or not fills:
        return fallback
    first = fills[0]
    if not isinstance(first, Mapping) or first.get("type") != "SOLID":
        return fallback
    color = first.get("color")
    if not isinstance(color, Mapping):
        return fallback
    opacity = first.get("opacity", 1.0)
    r = round(float(color.get("r", 0.0)) * 255)
    g = round(float(color.get("g", 0.0)) * 255)
    b = round(float(color.get("b", 0.0)) * 255)
    alpha = ""
    if isinstance(opacity, (int, float)) and float(opacity) < 1.0:
        alpha = f"{round(float(opacity) * 255):02X}"
    hex_value = f"#{r:02X}{g:02X}{b:02X}{alpha}"
    return hex_value


def _slug(raw: Any) -> str:
    slug = _SLUG_NON_ALNUM.sub("_", str(raw or "").strip().lower()).strip("_")
    return slug or "unnamed"