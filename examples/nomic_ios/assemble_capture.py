"""Assemble captured Nomic screens into a mobile (393x852) luvatrix iOS app.

Reads the per-screen `figma capture` outputs, cleans capture artifacts
(serialize-style CSS text and compiler/clip mismatches), and composes one
393x852 screen frame per capture: app content below the simulator's real
status-bar clear zone, plus an authored iOS-style bottom tab bar pinned over
the scrollable content as the frame's fixed child.

    python assemble_capture.py --captures assistant=/tmp/... --out design/
"""

from __future__ import annotations

import argparse
import io
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

STATUS_CLEAR_PT = 59.0
TAB_BAR_HEIGHT_PT = 80.0
FRAME_W = 393.0
VIEWPORT_H = 852.0
FALLBACK_DARK = (10, 10, 12)
FALLBACK_ACCENT = (94, 92, 230)

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


# ── palette ───────────────────────────────────────────────────────────────────


def sample_palette(pngs: list[bytes]) -> dict[str, tuple[int, int, int]]:
    """Sample the tab-bar dark and the app accent color from capture renders."""
    import numpy as np
    from PIL import Image

    best_dark: tuple[int, int, int] | None = None
    best_sat: tuple[int, tuple[int, int, int]] | None = None
    for png in pngs:
        image = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), dtype=np.int32)
        flat = image.reshape(-1, 3)
        luminance = flat @ np.array([299, 587, 114], dtype=np.int32) // 1000
        dark_rows = flat[luminance < 60]
        if len(dark_rows):
            # The single darkest pixel cluster anchors the near-black chrome.
            counts = Counter(map(tuple, dark_rows.tolist()))
            candidate = min(counts, key=lambda px: sum(px))
            if best_dark is None or sum(candidate) < sum(best_dark):
                best_dark = candidate
        saturation = flat.max(axis=1) - flat.min(axis=1)
        colorful = saturation > 60
        if colorful.any():
            row = int(np.argmax(np.where(colorful, saturation, -1)))
            px = tuple(int(v) for v in flat[row])
            score = int(saturation[row])
            if best_sat is None or score > best_sat[0]:
                best_sat = (score, px)
    return {
        "dark": best_dark or FALLBACK_DARK,
        "accent": (best_sat or (0, FALLBACK_ACCENT))[1],
    }


# ── vector chrome ─────────────────────────────────────────────────────────────


def rounded_rect_path(x: float, y: float, w: float, h: float, r: float) -> str:
    return (
        f"M{x + r} {y} h{w - 2 * r} a{r} {r} 0 0 1 {r} {r} v{h - 2 * r} "
        f"a{r} {r} 0 0 1 -{r} {r} h-{w - 2 * r} a{r} {r} 0 0 1 -{r} -{r} "
        f"v-{h - 2 * r} a{r} {r} 0 0 1 {r} -{r} Z"
    )


def tab_icon_path(kind: str) -> str:
    """Outline-style tab icons authored on a 24x24 grid."""
    if kind == "assistant":
        return (
            "M6 4 h12 a2.5 2.5 0 0 1 2.5 2.5 v7.5 a2.5 2.5 0 0 1 -2.5 2.5 "
            "h-7.5 l-4 3.5 v-3.5 h-0.5 a2.5 2.5 0 0 1 -2.5 -2.5 v-7.5 a2.5 2.5 0 0 1 2.5 -2.5 Z"
        )
    if kind == "drive":
        return (
            "M3.5 7.5 a2 2 0 0 1 2-2 h3.6 a1 1 0 0 1 0.8 0.4 l1.3 1.6 h7.3 "
            "a2 2 0 0 1 2 2 v7.5 a2 2 0 0 1 -2 2 h-13 a2 2 0 0 1 -2 -2 Z"
        )
    if kind == "projects":
        return (
            "M12 3.2 20 7.7 12 12.2 4 7.7 Z "
            "M4.6 11.5 12 15.8 19.4 11.5 "
            "M4.6 15.3 12 19.6 19.4 15.3"
        )
    if kind == "profile":
        return (
            "M12 10.4 a3.4 3.4 0 1 0 0 -6.8 a3.4 3.4 0 0 0 0 6.8 Z "
            "M5.2 20.2 a6.8 5.6 0 0 1 13.6 0"
        )
    raise ValueError(f"unknown tab icon kind: {kind}")


def _vector_node(node_id: str, path: str, *, x: float, y: float, size: float, color: tuple[float, float, float], weight: float = 1.8) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "VECTOR",
        "name": "icon",
        "absoluteBoundingBox": {"x": x, "y": y, "width": size, "height": size},
        "size": {"x": size, "y": size},
        "vectorPaths": [{"path": path, "windingRule": "NONE"}],
        "strokes": [{"type": "SOLID", "color": {"r": color[0] / 255, "g": color[1] / 255, "b": color[2] / 255}, "opacity": 1}],
        "strokeWeight": weight,
        "strokeAlign": "CENTER",
        "fills": [],
    }


def _label_node(node_id: str, text: str, *, cx: float, y: float, color: tuple[float, float, float], active: bool) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "TEXT",
        "name": "label",
        "characters": text,
        "absoluteBoundingBox": {"x": cx - 40, "y": y, "width": 80, "height": 12},
        "style": {
            "fontFamily": "Inter",
            "fontWeight": 600 if active else 500,
            "fontSize": 10,
            "textAlignHorizontal": "CENTER",
            "textAutoResize": "NONE",
            "lineHeightPx": 12,
            "lineHeightUnit": "PIXELS",
        },
        "fills": [{"type": "SOLID", "color": {"r": color[0] / 255, "g": color[1] / 255, "b": color[2] / 255}, "opacity": 1}],
    }


def build_tab_bar_node(
    y: float,
    dark: tuple[int, int, int],
    accent: tuple[int, int, int],
    tabs: list[tuple[str, str, str]],
    active: str | None = None,
) -> dict[str, Any]:
    """Build the fixed bottom tab bar; ``tabs`` is (label, icon kind, destination id).

    ``active`` names the icon kind whose tab renders as selected (accent tint,
    semibold label); the rest render in the inactive gray.
    """
    children: list[dict[str, Any]] = []
    slot = FRAME_W / len(tabs)
    for index, (label, kind, destination) in enumerate(tabs):
        x = index * slot
        is_active = kind == active
        icon_color = accent if is_active else (152, 152, 159)
        label_color = (255, 255, 255) if is_active else (152, 152, 159)
        children.append(
            {
                "id": f"tab:{kind}",
                "type": "FRAME",
                "name": f"{label} Tab",
                "absoluteBoundingBox": {"x": x, "y": y, "width": slot, "height": TAB_BAR_HEIGHT_PT},
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
                "children": [
                    _vector_node(
                        f"tab:{kind}:icon",
                        tab_icon_path(kind),
                        x=x + slot / 2 - 12,
                        y=y + 16,
                        size=24,
                        color=icon_color,
                    ),
                    _label_node(
                        f"tab:{kind}:label",
                        label,
                        cx=x + slot / 2,
                        y=y + 50,
                        color=label_color,
                        active=is_active,
                    ),
                ],
            }
        )
    return {
        "id": "tab:bar",
        "type": "FRAME",
        "name": "Tab Bar",
        "absoluteBoundingBox": {"x": 0.0, "y": y, "width": FRAME_W, "height": TAB_BAR_HEIGHT_PT},
        "clipsContent": False,
        "fills": [{"type": "SOLID", "color": {"r": dark[0] / 255, "g": dark[1] / 255, "b": dark[2] / 255}, "opacity": 1}],
        "children": children,
    }


# ── screen assembly ───────────────────────────────────────────────────────────


def assemble_screen(
    capture_frame: dict[str, Any],
    *,
    name: str,
    tab_bar: dict[str, Any],
) -> dict[str, Any]:
    """Turn one captured 393x852 frame into an app screen.

    The captured frame becomes the screen itself: every descendant shifts down
    by the status-bar clear height (children are positioned in frame-local
    absolute coordinates), the frame grows exactly far enough that the whole
    content can scroll clear of the fixed tab bar, and the tab bar is appended
    as the last child (the renderer's fixed overlay) at the viewport bottom.
    """
    content_h = float(capture_frame["absoluteBoundingBox"]["height"])
    visible_content = VIEWPORT_H - STATUS_CLEAR_PT - TAB_BAR_HEIGHT_PT
    height = VIEWPORT_H + max(0.0, content_h - visible_content)
    capture_frame["name"] = name
    capture_frame["absoluteBoundingBox"]["height"] = height
    capture_frame["overflowDirection"] = (
        "VERTICAL_SCROLLING" if content_h > visible_content + 0.5 else "NONE"
    )
    capture_frame["numberOfFixedChildren"] = 1
    for node in _walk_all(capture_frame):
        if node is capture_frame:
            continue
        box = node.get("absoluteBoundingBox")
        if box is not None:
            box["y"] = float(box.get("y", 0.0)) + STATUS_CLEAR_PT
        rel = node.get("relativeTransform")
        if isinstance(rel, list) and len(rel) == 2 and "size" in node:
            rel[1][2] = float(rel[1][2]) + STATUS_CLEAR_PT
    bar_y = VIEWPORT_H - TAB_BAR_HEIGHT_PT
    built_y = float(tab_bar["absoluteBoundingBox"].get("y", 0.0))
    if abs(bar_y - built_y) > 0.01:
        _translate_y(tab_bar, bar_y - built_y)
    capture_frame.setdefault("children", []).append(tab_bar)
    return capture_frame


def _translate_y(node: dict[str, Any], dy: float) -> None:
    box = node.get("absoluteBoundingBox")
    if box is not None:
        box["y"] = float(box.get("y", 0.0)) + dy
    for child in node.get("children") or ():
        _translate_y(child, dy)


def drop_misplaced_header_widgets(screen: dict[str, Any]) -> int:
    """Remove header widgets the compiler overlapped at mobile width.

    The Drive header's organization switcher compiles on top of the breadcrumb
    at 393pt (flex measurement drift); it carries no demo value, so drop it
    rather than ship an overlapping gray blob.
    """
    removed = 0

    def prune(node: dict[str, Any]) -> None:
        nonlocal removed
        children = node.get("children")
        if children is None:
            return
        kept = []
        for child in children:
            if str(child.get("name", "")).startswith("button.data-[placeholder]"):
                removed += 1
                continue
            kept.append(child)
            prune(child)
        node["children"] = kept

    prune(screen)
    return removed


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


def merge_captures(frames: list[tuple[dict[str, Any], str]], title: str) -> dict[str, Any]:
    """One canvas, one renamed screen frame per capture, in tour order."""
    renamed: list[dict[str, Any]] = []
    for frame, name in frames:
        frame["name"] = name
        renamed.append(frame)
    canvas = {
        "id": "0:1",
        "type": "CANVAS",
        "name": title,
        "backgroundColor": {"r": 1, "g": 1, "b": 1, "a": 1},
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
TABS = [
    ("Assistant", "assistant", "Assistant"),
    ("Drive", "drive", "Drive"),
    ("Projects", "projects", "Projects"),
    ("Profile", "profile", "Profile"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", action="append", required=True, help="name=path/to/capture-dir")
    parser.add_argument("--out", type=Path, required=True, help="Design dir for figma_file.json")
    parser.add_argument("--renders", type=Path, default=None, help="Dir with <Name>.png renders for palette sampling")
    parser.add_argument("--click-map", type=Path, default=None, help="JSON: hotspot needle -> {name, frame}")
    args = parser.parse_args()

    captures: dict[str, Path] = {}
    for spec in args.captures:
        key, _, value = spec.partition("=")
        captures[key.strip()] = Path(value.strip())

    palette_pngs: list[bytes] = []
    if args.renders is not None:
        for _, name, _height in SCREEN_SPECS:
            png = args.renders / f"{name}.png"
            if png.exists():
                palette_pngs.append(png.read_bytes())
    palette = sample_palette(palette_pngs)
    print(f"[nomic_ios] palette: dark={palette['dark']} accent={palette['accent']}")

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
        bar = build_tab_bar_node(VIEWPORT_H - TAB_BAR_HEIGHT_PT, palette["dark"], palette["accent"], tabs, active=active)
        screens.append(assemble_screen(frame, name=name, tab_bar=bar))

    if args.click_map:
        wanted = json.loads(args.click_map.read_text(encoding="utf-8"))
        for needle, spec in wanted.items():
            screen = screens[order.index(spec["screen"])]
            if not wire_content_hotspot(screen, needle, spec["name"], ids[spec["destination"]]):
                print(f"[nomic_ios] warning: hotspot text not found: {needle!r}")

    for name in ("Assistant", "Conversation"):
        if not rename_composer_chip(screens[order.index(name)]):
            print(f"[nomic_ios] warning: composer mode chip not found on {name}")
    for name in order:
        dropped = drop_misplaced_header_widgets(screens[order.index(name)])
        if dropped:
            print(f"[nomic_ios] dropped {dropped} misplaced header widget(s) on {name}")

    payload = merge_captures([(screen, name) for screen, name in zip(screens, order)], title="Nomic iOS")
    # Artifact cleanup + clip reconciliation run per assembled screen.
    removed = drop_css_artifact_texts(payload)
    reconciled = reconcile_clips(payload)
    print(f"[nomic_ios] removed {removed} css artifact text(s), reconciled {reconciled} clip(s)")

    args.out.mkdir(parents=True, exist_ok=True)
    design = args.out / "figma_file.json"
    design.write_text(json.dumps(payload), encoding="utf-8")
    print(f"[nomic_ios] wrote {design} with {len(screens)} screens")


if __name__ == "__main__":
    main()