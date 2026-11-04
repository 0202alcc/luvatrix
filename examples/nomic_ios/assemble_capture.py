"""Assemble captured Nomic screens into an iPhone 17 (402x874) luvatrix iOS app.

Reads the per-screen `figma capture` outputs (captured with
`--viewport 402x874@3`), cleans capture artifacts (serialize-style CSS text and
compiler/clip mismatches), and composes one 402x874 screen frame per capture:
app content below the status bar, running edge to edge underneath a floating
Liquid Glass-style tab bar that is the frame's fixed child.

    python assemble_capture.py --captures assistant=/tmp/... --out design/
    python assemble_capture.py --captures assistant=/tmp/light/... \
        --dark-captures assistant=/tmp/dark/... --out design/

Light captures build `design/figma_file.json`; adding `--dark-captures` (the
same screens captured with the site in dark mode) also writes
`design/figma_file.dark.json` with a dark glass tab bar and scroll-edge fade.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any

# iPhone 17 portrait: 402x874 pt [S-LAYOUT-ARCHIVE]; safe-area insets 62 pt top
# and 34 pt bottom (third-party simulator measurement [T-SAFEAREA]). Tags refer
# to .cursor/skills/ios-app-design/references/sources.md.
FRAME_W = 402.0
VIEWPORT_H = 874.0
STATUS_CLEAR_PT = 62.0
HOME_INDICATOR_PT = 34.0

# Apple publishes no floating tab bar metrics. These are chosen, not measured:
# replace them with the iOS 27 Figma kit values [S-DESIGNKITS] when available.
TAB_BAR_HEIGHT_PT = 62.0
TAB_BAR_INSET_PT = 16.0
TAB_BAR_PADDING_PT = 4.0
TAB_BAR_Y = VIEWPORT_H - HOME_INDICATOR_PT - TAB_BAR_HEIGHT_PT
TAB_ICON_PT = 24.0
TAB_LABEL_PT = 11.0  # Caption 2, the iOS minimum text size [S-TYPOGRAPHY]

# Regular glass approximation: background blur, a translucent light tint, a
# hairline edge, a top specular highlight, and a soft float shadow.
GLASS_TINT = (250, 250, 252)
GLASS_TINT_OPACITY = 0.72
GLASS_BLUR_PT = 12.0
# Monochrome bar symbols and labels [S-COLOR]; the selection is carried by
# weight, a darker shade, and a concentric pill rather than a hue.
TAB_SELECTED = (24, 24, 24)
TAB_UNSELECTED = (102, 102, 102)
SELECTION_PILL_OPACITY = 0.07


@dataclass(frozen=True)
class BarTheme:
    """Per-appearance colors for the floating glass tab bar and canvas.

    Glass has no color of its own; symbols and labels stay monochrome, darker
    over light content and lighter over dark content [S-COLOR]. Geometry never
    changes between appearances.
    """

    tint: tuple[int, int, int]
    tint_opacity: float
    selected: tuple[int, int, int]
    unselected: tuple[int, int, int]
    pill_rgb: tuple[int, int, int]
    pill_opacity: float
    stroke_rgb: tuple[int, int, int]
    stroke_opacity: float
    highlight_alpha: float
    shadow_alpha: float
    canvas_background: tuple[float, float, float]
    scroll_edge_fallback: tuple[float, float, float]


BAR_THEMES = {
    "light": BarTheme(
        tint=GLASS_TINT,
        tint_opacity=GLASS_TINT_OPACITY,
        selected=TAB_SELECTED,
        unselected=TAB_UNSELECTED,
        pill_rgb=(0, 0, 0),
        pill_opacity=SELECTION_PILL_OPACITY,
        stroke_rgb=(0, 0, 0),
        stroke_opacity=0.08,
        highlight_alpha=0.9,
        shadow_alpha=0.1,
        canvas_background=(1.0, 1.0, 1.0),
        scroll_edge_fallback=(1.0, 1.0, 1.0),
    ),
    # Dark values are chosen, not measured, pending the iOS 27 Figma kit
    # [S-DESIGNKITS]: a dark translucent tint, light monochrome symbols, and a
    # white selection wash over the same blurred glass.
    "dark": BarTheme(
        tint=(26, 26, 28),
        tint_opacity=0.66,
        selected=(248, 248, 248),
        unselected=(170, 170, 170),
        pill_rgb=(255, 255, 255),
        pill_opacity=0.14,
        stroke_rgb=(255, 255, 255),
        stroke_opacity=0.14,
        highlight_alpha=0.22,
        shadow_alpha=0.35,
        canvas_background=(0.0, 0.0, 0.0),
        scroll_edge_fallback=(0.0, 0.0, 0.0),
    ),
}


def bar_theme(appearance: str) -> BarTheme:
    try:
        return BAR_THEMES[appearance]
    except KeyError:
        names = ", ".join(sorted(BAR_THEMES))
        raise ValueError(f"unknown appearance {appearance!r}; expected one of: {names}") from None

# Captured-layout heuristics: the top band where the web header lives, and the
# tallest block that still counts as the chat composer control.
HEADER_BAND_PT = 160.0
COMPOSER_MAX_H_PT = 160.0
SCROLL_EDGE_FADE_PT = 20.0

_CSS_DECLARATION = re.compile(r"^\s*[-a-z]+\s*:\s*[^;{}]+;\s*[-a-z]+\s*:", re.IGNORECASE)
_CSS_POSITION = re.compile(r"^\s*position\s*:\s*(absolute|fixed|relative|sticky)\b", re.IGNORECASE)
_PX_PAIR = re.compile(r"^\s*[-\d.]+px\s+[-\d.]+px\s*$")


def is_css_artifact_text(chars: str) -> bool:
    """True for text that is really a hidden element's serialized inline style."""
    return bool(_CSS_DECLARATION.match(chars) or _CSS_POSITION.match(chars) or _PX_PAIR.match(chars))


def _walk_all(node: dict[str, Any]) -> list[dict[str, Any]]:
    out = [node]
    for child in node.get("children") or ():
        out.extend(_walk_all(child))
    return out


def drop_css_artifact_texts(payload: dict[str, Any]) -> int:
    """Remove artifact TEXT nodes in place; returns how many were dropped."""

    def prune(node: dict[str, Any]) -> int:
        removed = 0
        children = node.get("children")
        if children is None:
            return 0
        kept = []
        for child in children:
            if child.get("type") == "TEXT" and is_css_artifact_text(str(child.get("characters", ""))):
                removed += 1
                continue
            kept.append(child)
            removed += prune(child)
        node["children"] = kept
        return removed

    total = 0
    for canvas in payload.get("document", {}).get("children", ()):  # type: ignore[union-attr]
        total += prune(canvas)
    return total


def reconcile_clips(payload: dict[str, Any], max_grow: float = 40.0) -> int:
    """Widen clip ancestors so snapshot text boxes are not clipped.

    The compiler computes flex/table element boxes itself while text boxes come
    from the browser snapshot; at narrow widths the two disagree by a few
    points and the clip cuts the first glyphs of list rows. Grow the tightest
    clip ancestor just enough to contain the text box (bounded by ``max_grow``;
    larger overflows are real truncations the paint layer ellipsizes).

    Structural shells are never clip candidates: each canvas child is an
    assembled screen, and a screen's first child is the captured content frame
    whose geometry is canonical.
    """
    fixed = 0

    # Horizontal drift at narrow widths is a few points; sideways growth past
    # that starts eating into neighbouring chrome (icons, adjacent inputs).
    SIDE_GROW_LIMIT = 16.0

    def walk(node: dict[str, Any], clips: list[dict[str, Any]], shell_depth: int) -> None:
        nonlocal fixed
        box = node.get("absoluteBoundingBox")
        here = clips
        if box and node.get("clipsContent") and shell_depth <= 0:
            here = [*clips, node]
        chars = node.get("characters")
        if chars and box and here:
            grew_any = False
            for clip in here:
                cb = clip["absoluteBoundingBox"]
                grow_left = cb["x"] - box["x"]
                grow_right = (box["x"] + box["width"]) - (cb["x"] + cb["width"])
                grow_top = cb["y"] - box["y"]
                grow_bottom = (box["y"] + box["height"]) - (cb["y"] + cb["height"])
                grew = False
                if 0 < grow_left <= SIDE_GROW_LIMIT:
                    cb["x"] = box["x"]
                    cb["width"] += grow_left
                    grew = True
                if 0 < grow_right <= max_grow:
                    cb["width"] += grow_right
                    grew = True
                if 0 < grow_top <= SIDE_GROW_LIMIT:
                    cb["y"] = box["y"]
                    cb["height"] += grow_top
                    grew = True
                if 0 < grow_bottom <= max_grow:
                    cb["height"] += grow_bottom
                    grew = True
                if grew:
                    grew_any = True
            if grew_any:
                fixed += 1
        for index, child in enumerate(node.get("children") or ()):
            walk(child, here, shell_depth - 1 if shell_depth > 0 and index == 0 else 0)

    for canvas in payload.get("document", {}).get("children", ()):  # type: ignore[union-attr]
        for screen in canvas.get("children") or ():
            # One structural shell per screen: the screen frame itself never
            # grows; everything inside it is eligible.
            walk(screen, [], 1)
    return fixed


# ── vector chrome ─────────────────────────────────────────────────────────────


def rounded_rect_path(x: float, y: float, w: float, h: float, r: float) -> str:
    return (
        f"M{x + r} {y} h{w - 2 * r} a{r} {r} 0 0 1 {r} {r} v{h - 2 * r} "
        f"a{r} {r} 0 0 1 -{r} {r} h-{w - 2 * r} a{r} {r} 0 0 1 -{r} -{r} "
        f"v-{h - 2 * r} a{r} {r} 0 0 1 {r} -{r} Z"
    )


def tab_icon_path(kind: str) -> str:
    """Filled tab glyphs on a 24x24 grid, after the SF Symbols bubble.left.fill,
    folder.fill, square.stack.fill, and person.fill (tab bars prefer filled
    symbols [S-TABBARS]; SF Symbols themselves can't be bundled)."""
    if kind == "assistant":
        return (
            "M7 3.5 h10 a5 5 0 0 1 5 5 v4.5 a5 5 0 0 1 -5 5 h-5.6 l-4.6 3.5 "
            "a0.7 0.7 0 0 1 -1.1 -0.6 v-3.1 a5 5 0 0 1 -3.7 -4.8 v-4.5 a5 5 0 0 1 5 -5 Z"
        )
    if kind == "drive":
        return (
            "M2 7 a2.5 2.5 0 0 1 2.5 -2.5 h4.4 a2 2 0 0 1 1.5 0.7 l1.5 1.8 h7.6 "
            "a2.5 2.5 0 0 1 2.5 2.5 v9 a2.5 2.5 0 0 1 -2.5 2.5 h-15 a2.5 2.5 0 0 1 -2.5 -2.5 Z"
        )
    if kind == "projects":
        return " ".join(
            (
                rounded_rect_path(3, 9, 18, 12.5, 3),
                rounded_rect_path(5, 5.6, 14, 2.2, 1.1),
                rounded_rect_path(7.5, 2.5, 9, 2, 1),
            )
        )
    if kind == "profile":
        return (
            "M12 2.8 a4.6 4.6 0 1 1 0 9.2 a4.6 4.6 0 1 1 0 -9.2 Z "
            "M3.6 20.2 c0.4 -3.9 4 -6.4 8.4 -6.4 c4.4 0 8 2.5 8.4 6.4 "
            "a1 1 0 0 1 -1 1.1 h-14.8 a1 1 0 0 1 -1 -1.1 Z"
        )
    raise ValueError(f"unknown tab icon kind: {kind}")


def _solid(rgb: tuple[int, int, int], opacity: float = 1.0) -> dict[str, Any]:
    return {"type": "SOLID", "color": {"r": rgb[0] / 255, "g": rgb[1] / 255, "b": rgb[2] / 255}, "opacity": opacity}


def _vector_node(node_id: str, path: str, *, x: float, y: float, size: float, color: tuple[int, int, int]) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "VECTOR",
        "name": "icon",
        "absoluteBoundingBox": {"x": x, "y": y, "width": size, "height": size},
        "size": {"x": size, "y": size},
        "vectorPaths": [{"path": path, "windingRule": "NONZERO"}],
        "fills": [_solid(color)],
        "strokes": [],
    }


def _label_node(node_id: str, text: str, *, x: float, y: float, width: float, color: tuple[int, int, int], active: bool) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "TEXT",
        "name": "label",
        "characters": text,
        "absoluteBoundingBox": {"x": x, "y": y, "width": width, "height": 13.0},
        "style": {
            "fontFamily": "Inter",
            "fontWeight": 600 if active else 500,
            "fontSize": TAB_LABEL_PT,
            "textAlignHorizontal": "CENTER",
            "textAutoResize": "NONE",
            "lineHeightPx": 13,
            "lineHeightUnit": "PIXELS",
        },
        "fills": [_solid(color)],
    }


def build_tab_bar_node(
    tabs: list[tuple[str, str, str]], active: str | None = None, *, appearance: str = "light"
) -> dict[str, Any]:
    """Build the floating glass tab bar; ``tabs`` is (label, icon kind, destination id).

    The bar is a capsule inset from the screen edges, sitting just above the
    home-indicator zone. Each tab fills an equal slot inside the capsule's
    padding, so the selected tab's pill is concentric with the bar: its radius
    is the bar radius minus the padding [S-WWDC25-356]. ``active`` names the
    icon kind of the selected tab. ``appearance`` picks the glass theme; the
    geometry is identical in light and dark.
    """
    theme = bar_theme(appearance)
    bar_x, bar_w, bar_h = TAB_BAR_INSET_PT, FRAME_W - 2 * TAB_BAR_INSET_PT, TAB_BAR_HEIGHT_PT
    pad = TAB_BAR_PADDING_PT
    slot_w = (bar_w - 2 * pad) / len(tabs)
    slot_h = bar_h - 2 * pad
    slot_y = TAB_BAR_Y + pad
    children: list[dict[str, Any]] = []
    for index, (label, kind, destination) in enumerate(tabs):
        x = bar_x + pad + index * slot_w
        is_active = kind == active
        color = theme.selected if is_active else theme.unselected
        parts: list[dict[str, Any]] = []
        if is_active:
            parts.append(
                {
                    "id": f"tab:{kind}:selection",
                    "type": "RECTANGLE",
                    "name": "selection",
                    "absoluteBoundingBox": {"x": x, "y": slot_y, "width": slot_w, "height": slot_h},
                    "cornerRadius": bar_h / 2 - pad,
                    "fills": [_solid(theme.pill_rgb, theme.pill_opacity)],
                }
            )
        parts.append(
            _vector_node(
                f"tab:{kind}:icon",
                tab_icon_path(kind),
                x=x + slot_w / 2 - TAB_ICON_PT / 2,
                y=slot_y + 7,
                size=TAB_ICON_PT,
                color=color,
            )
        )
        parts.append(_label_node(f"tab:{kind}:label", label, x=x, y=slot_y + 35, width=slot_w, color=color, active=is_active))
        children.append(
            {
                "id": f"tab:{kind}",
                "type": "FRAME",
                "name": f"{label} Tab",
                "absoluteBoundingBox": {"x": x, "y": slot_y, "width": slot_w, "height": slot_h},
                "clipsContent": False,
                "fills": [],
                "interactions": [
                    {
                        "trigger": {"type": "ON_CLICK"},
                        "actions": [
                            {
                                "type": "NODE",
                                "destinationId": destination,
                                "navigation": "NAVIGATE",
                                "transition": None,
                            }
                        ],
                    }
                ],
                "children": parts,
            }
        )
    return {
        "id": "tab:bar",
        "type": "FRAME",
        "name": "Tab Bar",
        "absoluteBoundingBox": {"x": bar_x, "y": TAB_BAR_Y, "width": bar_w, "height": bar_h},
        "cornerRadius": bar_h / 2,
        "clipsContent": False,
        "fills": [_solid(theme.tint, theme.tint_opacity)],
        "strokes": [_solid(theme.stroke_rgb, theme.stroke_opacity)],
        "strokeWeight": 0.5,
        "strokeAlign": "INSIDE",
        "effects": [
            {"type": "DROP_SHADOW", "color": {"r": 0, "g": 0, "b": 0, "a": theme.shadow_alpha}, "offset": {"x": 0, "y": 4}, "radius": 16, "visible": True},
            {"type": "BACKGROUND_BLUR", "radius": GLASS_BLUR_PT, "visible": True},
            {"type": "INNER_SHADOW", "color": {"r": 1, "g": 1, "b": 1, "a": theme.highlight_alpha}, "offset": {"x": 0, "y": 1}, "radius": 1, "visible": True},
        ],
        "children": children,
    }


# ── screen assembly ───────────────────────────────────────────────────────────


def assemble_screen(
    capture_frame: dict[str, Any],
    *,
    name: str,
    tab_bar: dict[str, Any],
    appearance: str = "light",
) -> dict[str, Any]:
    """Turn one captured 402x874 frame into an app screen.

    The captured frame becomes the screen itself: every descendant shifts down
    by the status-bar clear height (children are positioned in frame-local
    absolute coordinates), and the tab bar is appended as the last child (the
    renderer's fixed overlay). The frame and its background run to the screen
    bottom underneath the floating bar [S-LAYOUT]; it grows exactly far enough
    that the end of the content can scroll up to the bar's top edge.
    """
    content_h = float(capture_frame["absoluteBoundingBox"]["height"])
    bar_top = float(tab_bar["absoluteBoundingBox"]["y"])
    visible_content = bar_top - STATUS_CLEAR_PT
    height = VIEWPORT_H + max(0.0, content_h - visible_content)
    capture_frame["name"] = name
    capture_frame["absoluteBoundingBox"]["height"] = height
    capture_frame["overflowDirection"] = (
        "VERTICAL_SCROLLING" if content_h > visible_content + 0.5 else "NONE"
    )
    for node in _walk_all(capture_frame):
        if node is capture_frame:
            continue
        box = node.get("absoluteBoundingBox")
        if box is not None:
            box["y"] = float(box.get("y", 0.0)) + STATUS_CLEAR_PT
        rel = node.get("relativeTransform")
        if isinstance(rel, list) and len(rel) == 2 and "size" in node:
            rel[1][2] = float(rel[1][2]) + STATUS_CLEAR_PT
    children = capture_frame.setdefault("children", [])
    children.append(build_scroll_edge_node(capture_frame, appearance=appearance))
    children.append(tab_bar)
    capture_frame["numberOfFixedChildren"] = 2
    return capture_frame


def build_scroll_edge_node(screen: dict[str, Any], *, appearance: str = "light") -> dict[str, Any]:
    """A top scroll edge effect: content fades out under the status bar.

    Floating UI over a scroll view separates itself from content with a scroll
    edge effect rather than an opaque band [S-LAYOUT], [S-SCROLLVIEWS]. At rest
    it matches the screen background, so it is invisible until content scrolls.
    """
    fallback = bar_theme(appearance).scroll_edge_fallback
    color = {"r": fallback[0], "g": fallback[1], "b": fallback[2]}
    for paint in screen.get("fills") or ():
        if paint.get("type") == "SOLID":
            color = {k: float(paint["color"][k]) for k in ("r", "g", "b")}
            break
    height = STATUS_CLEAR_PT + SCROLL_EDGE_FADE_PT
    opaque_until = (STATUS_CLEAR_PT - 8.0) / height
    return {
        "id": f"{screen.get('id', 'screen')}:scroll-edge",
        "type": "RECTANGLE",
        "name": "Scroll Edge",
        "absoluteBoundingBox": {"x": 0.0, "y": 0.0, "width": FRAME_W, "height": height},
        "fills": [
            {
                "type": "GRADIENT_LINEAR",
                "gradientHandlePositions": [{"x": 0.5, "y": 0.0}, {"x": 0.5, "y": 1.0}, {"x": 0.0, "y": 0.0}],
                "gradientStops": [
                    {"position": 0.0, "color": {**color, "a": 1.0}},
                    {"position": opaque_until, "color": {**color, "a": 1.0}},
                    {"position": 1.0, "color": {**color, "a": 0.0}},
                ],
            }
        ],
    }


def drop_misplaced_header_widgets(screen: dict[str, Any]) -> int:
    """Remove header widgets the compiler overlapped at mobile width.

    The Drive header's organization switcher compiles on top of the breadcrumb
    at mobile width (flex measurement drift); it carries no demo value, so drop
    it rather than ship an overlapping gray blob. Selects of the same kind
    further down the page (Profile's Theme picker) are real controls and stay.
    """
    removed = 0
    header_bottom = STATUS_CLEAR_PT + HEADER_BAND_PT

    def prune(node: dict[str, Any]) -> None:
        nonlocal removed
        children = node.get("children")
        if children is None:
            return
        kept = []
        for child in children:
            top = float((child.get("absoluteBoundingBox") or {}).get("y", 0.0))
            if str(child.get("name", "")).startswith("button.data-[placeholder]") and top < header_bottom:
                removed += 1
                continue
            kept.append(child)
            prune(child)
        node["children"] = kept

    prune(screen)
    return removed


def pin_composer_above_tab_bar(screen: dict[str, Any], needle: str) -> bool:
    """Make the chat composer a fixed child that sits on top of the floating tab bar.

    The web layout pins the composer to the bottom of its viewport, which the
    status-bar shift pushes under the tab bar. The tab bar must stay visible
    [S-TABBARS], so the composer block (the largest ancestor of the ``needle``
    text short enough to be a control) moves out of the scrolling content and
    becomes a fixed child whose bottom meets the bar's top edge.
    """
    path = _path_to_text(screen, needle)
    if path is None:
        return False
    blocks = [n for n in path[1:-1] if float(n["absoluteBoundingBox"]["height"]) <= COMPOSER_MAX_H_PT]
    if not blocks:
        return False
    block = blocks[0]
    parent = path[path.index(block) - 1]
    parent["children"] = [c for c in parent["children"] if c is not block]
    box = block["absoluteBoundingBox"]
    _translate_y(block, TAB_BAR_Y - (float(box["y"]) + float(box["height"])))
    fixed = int(screen.get("numberOfFixedChildren", 0))
    screen["children"].insert(len(screen["children"]) - fixed, block)
    screen["numberOfFixedChildren"] = fixed + 1
    return True


def _path_to_text(node: dict[str, Any], needle: str) -> list[dict[str, Any]] | None:
    if node.get("type") == "TEXT" and needle in str(node.get("characters", "")):
        return [node]
    for child in node.get("children") or ():
        found = _path_to_text(child, needle)
        if found is not None:
            return [node, *found]
    return None


def _translate_y(node: dict[str, Any], dy: float) -> None:
    box = node.get("absoluteBoundingBox")
    if box is not None:
        box["y"] = float(box.get("y", 0.0)) + dy
    rel = node.get("relativeTransform")
    if isinstance(rel, list) and len(rel) == 2 and "size" in node:
        rel[1][2] = float(rel[1][2]) + dy
    for child in node.get("children") or ():
        _translate_y(child, dy)


def rename_composer_chip(screen: dict[str, Any]) -> bool:
    """Name the composer's model-mode chip so `on_tap` can answer it with a hint."""
    for node in _walk_all(screen):
        if node.get("type") == "TEXT" and str(node.get("characters", "")).strip() == "Auto":
            node["name"] = "Mode Chip"
            return True
    return False


def wire_content_hotspot(screen: dict[str, Any], needle: str, hotspot_name: str, destination_id: str) -> bool:
    """Attach a NAVIGATE interaction to the text node whose characters contain ``needle``."""
    for node in _walk_all(screen):
        if node.get("type") == "TEXT" and needle in str(node.get("characters", "")):
            node["name"] = hotspot_name
            node["interactions"] = [
                {
                    "trigger": {"type": "ON_CLICK"},
                    "actions": [
                        {"type": "NODE", "destinationId": destination_id, "navigation": "NAVIGATE", "transition": None}
                    ],
                }
            ]
            return True
    return False


def remap_ids(node: dict[str, Any], prefix: str) -> None:
    """Prefix every node id (and interaction destination) so merged captures cannot collide."""
    if isinstance(node.get("id"), str) and ":" in node["id"]:
        node["id"] = prefix + node["id"]
    for interaction in node.get("interactions") or ():
        for action in interaction.get("actions") or ():
            destination = action.get("destinationId")
            if isinstance(destination, str) and ":" in destination:
                action["destinationId"] = prefix + destination
    for child in node.get("children") or ():
        remap_ids(child, prefix)


def merge_captures(frames: list[tuple[dict[str, Any], str]], title: str, *, appearance: str = "light") -> dict[str, Any]:
    """One canvas, one renamed screen frame per capture, in tour order."""
    theme = bar_theme(appearance)
    renamed: list[dict[str, Any]] = []
    for frame, name in frames:
        frame["name"] = name
        renamed.append(frame)
    canvas = {
        "id": "0:1",
        "type": "CANVAS",
        "name": title,
        "backgroundColor": {"r": theme.canvas_background[0], "g": theme.canvas_background[1], "b": theme.canvas_background[2], "a": 1},
        "flowStartingPoints": [{"nodeId": renamed[0]["id"], "name": "Start"}],
        "children": renamed,
    }
    return {
        "name": title,
        "schemaVersion": 1,
        "document": {"id": "0:0", "type": "DOCUMENT", "name": "Document", "children": [canvas]},
    }


SCREEN_SPECS = [
    ("assistant", "Assistant", 911.0),
    ("convo", "Conversation", 911.0),
    ("files", "Drive", 911.0),
    ("projects", "Projects", 911.0),
    ("settings", "Profile", 911.0),
]
COMPOSER_NEEDLE = "Integrations/MCPs"
TABS = [
    ("Assistant", "assistant", "Assistant"),
    ("Drive", "drive", "Drive"),
    ("Projects", "projects", "Projects"),
    ("Profile", "profile", "Profile"),
]


def assemble_design(
    captures: dict[str, Path],
    *,
    click_map: dict[str, Any] | None = None,
    appearance: str = "light",
) -> dict[str, Any]:
    """Build one design document from per-screen capture dirs for one appearance."""
    frames: list[tuple[dict[str, Any], str]] = []
    ids: dict[str, str] = {}
    for index, (key, name, _height) in enumerate(SCREEN_SPECS):
        capture = json.loads((captures[key] / "figma_file.json").read_text(encoding="utf-8"))
        frame = capture["document"]["children"][0]["children"][0]
        # Every capture reuses "1:0"; prefix per screen so ids stay unique.
        remap_ids(frame, f"S{index}:")
        ids[name] = frame["id"]
        frames.append((frame, name))
    order = [name for _key, name, _height in SCREEN_SPECS]

    screens: list[dict[str, Any]] = []
    for (_key, name, _height), (frame, _original) in zip(SCREEN_SPECS, frames):
        tabs = [(label, kind, ids[dest_name]) for label, kind, dest_name in TABS]
        active = next((kind for _label, kind, dest_name in TABS if dest_name == name), None)
        bar = build_tab_bar_node(tabs, active=active, appearance=appearance)
        screens.append(assemble_screen(frame, name=name, tab_bar=bar, appearance=appearance))

    if click_map:
        for needle, spec in click_map.items():
            screen = screens[order.index(spec["screen"])]
            if not wire_content_hotspot(screen, needle, spec["name"], ids[spec["destination"]]):
                print(f"[nomic_ios:{appearance}] warning: hotspot text not found: {needle!r}")

    for name in ("Assistant", "Conversation"):
        if not rename_composer_chip(screens[order.index(name)]):
            print(f"[nomic_ios:{appearance}] warning: composer mode chip not found on {name}")
    for name in order:
        dropped = drop_misplaced_header_widgets(screens[order.index(name)])
        if dropped:
            print(f"[nomic_ios:{appearance}] dropped {dropped} misplaced header widget(s) on {name}")
    if not pin_composer_above_tab_bar(screens[order.index("Conversation")], COMPOSER_NEEDLE):
        print(f"[nomic_ios:{appearance}] warning: composer not found on Conversation")

    payload = merge_captures(
        [(screen, name) for screen, name in zip(screens, order)], title="Nomic iOS", appearance=appearance
    )
    # Artifact cleanup + clip reconciliation run per assembled screen.
    removed = drop_css_artifact_texts(payload)
    reconciled = reconcile_clips(payload)
    print(f"[nomic_ios:{appearance}] removed {removed} css artifact text(s), reconciled {reconciled} clip(s)")
    return payload


def _capture_specs(specs: list[str]) -> dict[str, Path]:
    captures: dict[str, Path] = {}
    for spec in specs:
        key, _, value = spec.partition("=")
        captures[key.strip()] = Path(value.strip())
    return captures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--captures", action="append", required=True, help="name=path/to/capture-dir (light appearance)"
    )
    parser.add_argument(
        "--dark-captures",
        action="append",
        default=None,
        help="name=path/to/capture-dir for the dark appearance; also writes figma_file.dark.json",
    )
    parser.add_argument("--out", type=Path, required=True, help="Design dir for figma_file.json")
    parser.add_argument("--click-map", type=Path, default=None, help="JSON: hotspot needle -> {name, frame}")
    args = parser.parse_args()

    click_map = json.loads(args.click_map.read_text(encoding="utf-8")) if args.click_map else None

    variants: list[tuple[str, dict[str, Path], str]] = [("light", _capture_specs(args.captures), "figma_file.json")]
    if args.dark_captures:
        variants.append(("dark", _capture_specs(args.dark_captures), "figma_file.dark.json"))

    args.out.mkdir(parents=True, exist_ok=True)
    for appearance, captures, filename in variants:
        payload = assemble_design(captures, click_map=click_map, appearance=appearance)
        design = args.out / filename
        design.write_text(json.dumps(payload), encoding="utf-8")
        screens = payload["document"]["children"][0]["children"]
        print(f"[nomic_ios:{appearance}] wrote {design} with {len(screens)} screens")


if __name__ == "__main__":
    main()