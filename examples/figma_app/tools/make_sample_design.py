"""Regenerate the sample Figma REST payload in ../design/.

The output mirrors `GET /v1/files/:key?geometry=paths`: nodes carry
`absoluteBoundingBox`, `relativeTransform`, `size`, paints, effects, vector
`fillGeometry`, and prototype `interactions`. Replace it with a real export via
`luvatrix figma pull FILE_KEY --out examples/figma_app/design`.
"""

from __future__ import annotations

import itertools
import json
import math
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

DESIGN_DIR = Path(__file__).resolve().parents[1] / "design"
W, H = 393, 852
_ids = itertools.count(10)

GREEN = (0.18, 0.49, 0.34)
DARK = (0.09, 0.13, 0.11)
MUTED = (0.42, 0.47, 0.44)
CREAM = (0.97, 0.96, 0.93)
WHITE = (1.0, 1.0, 1.0)
PHOTO_REF = "6f1c0e2a9b7d4c3e8a5f0b1d2c3e4f5a"


def rgba(c: tuple[float, float, float], a: float = 1.0) -> dict[str, float]:
    return {"r": c[0], "g": c[1], "b": c[2], "a": a}


def solid(c: tuple[float, float, float], a: float = 1.0, opacity: float | None = None) -> dict[str, Any]:
    paint: dict[str, Any] = {"blendMode": "NORMAL", "type": "SOLID", "color": rgba(c, a)}
    if opacity is not None:
        paint["opacity"] = opacity
    return paint


def linear(c0, c1, *, start=(0.5, 0.0), end=(0.5, 1.0), a0=1.0, a1=1.0) -> dict[str, Any]:
    return {
        "blendMode": "NORMAL",
        "type": "GRADIENT_LINEAR",
        "gradientHandlePositions": [{"x": start[0], "y": start[1]}, {"x": end[0], "y": end[1]}, {"x": 0, "y": 1}],
        "gradientStops": [{"position": 0, "color": rgba(c0, a0)}, {"position": 1, "color": rgba(c1, a1)}],
    }


def shadow(y: float = 8, radius: float = 24, a: float = 0.12, spread: float = 0) -> dict[str, Any]:
    return {
        "type": "DROP_SHADOW",
        "visible": True,
        "color": rgba((0.05, 0.12, 0.08), a),
        "blendMode": "NORMAL",
        "offset": {"x": 0, "y": y},
        "radius": radius,
        "spread": spread,
        "showShadowBehindNode": False,
    }


class Builder:
    def __init__(self, origin_x: float) -> None:
        self.origin_x = origin_x

    def node(self, kind: str, name: str, x: float, y: float, w: float, h: float, parent=(0.0, 0.0), **extra) -> dict[str, Any]:
        ax, ay = self.origin_x + parent[0] + x, parent[1] + y
        out: dict[str, Any] = {
            "id": f"{next(_ids)}:{next(_ids)}",
            "name": name,
            "type": kind,
            "scrollBehavior": "SCROLLS",
            "blendMode": "PASS_THROUGH",
            "absoluteBoundingBox": {"x": ax, "y": ay, "width": w, "height": h},
            "absoluteRenderBounds": {"x": ax, "y": ay, "width": w, "height": h},
            "relativeTransform": [[1, 0, x], [0, 1, y]],
            "size": {"x": w, "y": h},
            "constraints": {"vertical": "TOP", "horizontal": "LEFT"},
            "fills": [],
            "strokes": [],
            "strokeWeight": 1,
            "strokeAlign": "INSIDE",
            "effects": [],
        }
        out.update(extra)
        return out

    def text(self, name: str, chars: str, x: float, y: float, w: float, h: float, *, size: float, weight: int = 400,
             color=DARK, align: str = "LEFT", line: float | None = None, parent=(0.0, 0.0), spacing: float = 0.0,
             auto: str = "HEIGHT", **extra) -> dict[str, Any]:
        style = {
            "fontFamily": "Inter",
            "fontPostScriptName": None,
            "fontWeight": weight,
            "textAutoResize": auto,
            "fontSize": size,
            "textAlignHorizontal": align,
            "textAlignVertical": "TOP",
            "letterSpacing": spacing,
            "lineHeightPx": line or round(size * 1.21, 2),
            "lineHeightPercent": 100,
            "lineHeightUnit": "INTRINSIC_%" if line is None else "PIXELS",
        }
        return self.node("TEXT", name, x, y, w, h, parent, characters=chars, style=style, fills=[solid(color)],
                         strokeAlign="OUTSIDE", characterStyleOverrides=[], styleOverrideTable={}, **extra)

    def frame(self, name: str, children: list[dict[str, Any]], fills: list[dict[str, Any]], *, height: float = H,
              fixed: int = 0) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        if height > H:
            extra = {"overflowDirection": "VERTICAL_SCROLLING", "numberOfFixedChildren": fixed}
        frame = self.node("FRAME", name, 0, 0, W, height, clipsContent=True, fills=fills, children=children, **extra)
        frame["relativeTransform"] = [[1, 0, self.origin_x], [0, 1, 0]]
        frame["background"] = fills
        return frame


def navigate(dest: str, kind: str = "SMART_ANIMATE") -> list[dict[str, Any]]:
    return [{
        "trigger": {"type": "ON_CLICK"},
        "actions": [{
            "type": "NODE",
            "destinationId": dest,
            "navigation": "NAVIGATE",
            "transition": {"type": kind, "easing": {"type": "EASE_OUT"}, "duration": 0.3},
            "preserveScrollPosition": False,
        }],
    }]


def back() -> list[dict[str, Any]]:
    return [{"trigger": {"type": "ON_CLICK"}, "actions": [{"type": "BACK"}]}]


LEAF = ("M12 2C6 2 3 7 3 12c0 3 1 5 3 7 1-5 4-9 9-11-4 3-6 6-7 11 1 1 3 1 4 1 6 0 9-5 9-11V2h-9Z")
HEART = ("M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3.1 4 7 4c2.1 0 3.6 1.2 5 3 1.4-1.8 2.9-3 5-3 3.9 0 6.1 4.4 4.6 "
         "7.8C19.5 16.4 12 21 12 21Z")
HOME = "M3 11 12 3l9 8v10h-6v-6H9v6H3V11Z"
USER = "M12 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10Zm0 2c-5 0-9 2.5-9 6v2h18v-2c0-3.5-4-6-9-6Z"
DROP = "M12 2s7 7.6 7 12.5A7 7 0 0 1 5 14.5C5 9.6 12 2 12 2Z"
SUN = ("M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10ZM11 0h2v4h-2zM11 20h2v4h-2zM0 11h4v2H0zM20 11h4v2h-4z")


def icon(b: Builder, name: str, path: str, x: float, y: float, color, *, parent=(0.0, 0.0), size: float = 24, **extra):
    k = size / 24.0
    vec = b.node("VECTOR", name, x, y, size, size, parent, fills=[solid(color)], **extra)
    vec["fillGeometry"] = [{"path": _scale_path(path, k), "windingRule": "NONZERO", "overrideID": None}]
    return vec


def _scale_path(path: str, k: float) -> str:
    if k == 1.0:
        return path
    if re.search(r"[Aa]", path):
        raise ValueError("arc flags cannot be scaled numerically; draw arc icons at 24px")
    return re.sub(r"-?\d*\.?\d+", lambda m: f"{float(m.group()) * k:g}", path)


def chevron(b: Builder, name: str, x: float, y: float, color, *, parent=(0.0, 0.0)):
    vec = b.node("VECTOR", name, x, y, 24, 24, parent, strokes=[solid(color)], strokeWeight=2.5, strokeAlign="CENTER",
                 strokeCap="ROUND", strokeJoin="ROUND")
    vec["fillGeometry"] = []
    vec["strokeGeometry"] = []
    vec["vectorPaths"] = [{"path": "M15 5 8 12l7 7", "windingRule": "NONE"}]
    return vec


def status_bar(b: Builder, color=DARK) -> list[dict[str, Any]]:
    return [
        b.text("Time", "9:41", 32, 16, 54, 22, size=17, weight=600, color=color, align="CENTER", auto="WIDTH_AND_HEIGHT"),
        b.node("RECTANGLE", "Battery", 336, 20, 25, 12, fills=[], strokes=[solid(color, opacity=0.4)], strokeWeight=1,
               cornerRadius=3.5),
        b.node("RECTANGLE", "Battery Level", 338, 22, 21, 8, fills=[solid(color)], cornerRadius=2),
    ]


def tab_bar(b: Builder, active: str, targets: dict[str, str]) -> dict[str, Any]:
    items = []
    for i, (label, path) in enumerate((("Home", HOME), ("Favorites", HEART), ("Profile", USER))):
        cx = 66 + i * 130
        color = GREEN if label == active else MUTED
        extra = {"interactions": navigate(targets[label], "DISSOLVE")} if label in targets and label != active else {}
        tab = b.node("FRAME", f"Tab {label}", cx - 40, 8, 80, 56, (0, 762), fills=[], children=[
            icon(b, f"{label} Icon", path, 28, 6, color, parent=(cx - 40, 770)),
            b.text(f"{label} Label", label, 0, 34, 80, 16, size=11, weight=600 if label == active else 500, color=color,
                   align="CENTER", parent=(cx - 40, 770)),
        ], **extra)
        items.append(tab)
    bar = b.node("FRAME", "Tab Bar", 0, 762, W, 90, fills=[solid(WHITE, opacity=0.92)], children=items,
                 effects=[{**shadow(-4, 20, 0.06), "offset": {"x": 0, "y": -4}}])
    bar["strokes"] = [solid((0.88, 0.9, 0.88))]
    bar["individualStrokeWeights"] = {"top": 1, "right": 0, "bottom": 0, "left": 0}
    return bar


def welcome(ids: dict[str, str]) -> dict[str, Any]:
    b = Builder(0)
    hero = b.node("ELLIPSE", "Glow", -80, 90, 553, 553, fills=[{
        "type": "GRADIENT_RADIAL",
        "gradientHandlePositions": [{"x": 0.5, "y": 0.5}, {"x": 1, "y": 0.5}, {"x": 0.5, "y": 1}],
        "gradientStops": [{"position": 0, "color": rgba((0.55, 0.85, 0.62), 0.55)},
                          {"position": 1, "color": rgba((0.55, 0.85, 0.62), 0.0)}],
    }])
    badge = b.node("FRAME", "Logo Badge", 136, 250, 120, 120, fills=[linear((0.27, 0.66, 0.45), GREEN)],
                   cornerRadius=36, effects=[shadow(16, 32, 0.25)], children=[
                       icon(b, "Logo Leaf", LEAF, 30, 30, WHITE, parent=(136, 250), size=60),
                   ])
    button = b.node("FRAME", "Get Started", 24, 712, 345, 58, fills=[solid(DARK)], cornerRadius=29,
                    effects=[shadow(10, 24, 0.22)], interactions=navigate(ids["Home"]), children=[
                        b.text("Button Label", "Get started", 0, 18, 345, 22, size=17, weight=600, color=WHITE,
                               align="CENTER", parent=(24, 712)),
                    ])
    return b.frame("Welcome", [
        hero,
        *status_bar(b),
        badge,
        b.text("Title", "Grow something\nbeautiful", 24, 420, 345, 80, size=34, weight=700, align="CENTER", line=40,
               spacing=-0.6),
        b.text("Subtitle", "Personal care plans, watering reminders and light tips for every plant in your home.",
               40, 520, 313, 66, size=16, color=MUTED, align="CENTER", line=22),
        button,
        b.text("Sign In", "I already have an account", 24, 790, 345, 20, size=15, weight=500, color=GREEN, align="CENTER"),
    ], [linear(CREAM, (0.9, 0.95, 0.9))])


def plant_card(b: Builder, name: str, latin: str, x: float, y: float, tint, dest: str | None) -> dict[str, Any]:
    extra = {"interactions": navigate(dest)} if dest else {}
    p = (x, y)
    return b.node("FRAME", f"Card {name}", x, y, 166, 214, fills=[solid(WHITE)], cornerRadius=24, effects=[shadow()],
                  children=[
                      b.node("RECTANGLE", "Thumb", 10, 10, 146, 126, p, cornerRadius=18,
                             fills=[{"type": "IMAGE", "scaleMode": "FILL", "imageRef": PHOTO_REF}] if dest else [
                                 linear(tint, (0.93, 0.96, 0.92))]),
                      *([] if dest else [icon(b, "Thumb Leaf", LEAF, 59, 49, GREEN, parent=p, size=48)]),
                      b.text("Name", name, 14, 148, 140, 22, size=17, weight=600, parent=p),
                      b.text("Latin", latin, 14, 172, 140, 18, size=13, color=MUTED, parent=p),
                  ], **extra)


def home(ids: dict[str, str]) -> dict[str, Any]:
    b = Builder(500)
    search = b.node("FRAME", "Search", 24, 168, 345, 48, fills=[solid(WHITE)], cornerRadius=16,
                    strokes=[solid((0.88, 0.9, 0.88))], children=[
                        b.text("Placeholder", "Search plants", 48, 14, 200, 20, size=15, color=MUTED, parent=(24, 168)),
                        b.node("ELLIPSE", "Lens", 16, 15, 16, 16, (24, 168), strokes=[solid(MUTED)], strokeWeight=2),
                    ])
    reminder = b.node("FRAME", "Reminder", 24, 240, 345, 96, fills=[linear((0.27, 0.66, 0.45), GREEN, start=(0, 0), end=(1, 1))],
                      cornerRadius=24, effects=[shadow(12, 28, 0.25)], children=[
                          b.node("ELLIPSE", "Drop Bg", 20, 24, 48, 48, (24, 240), fills=[solid(WHITE, 0.2)]),
                          icon(b, "Drop", DROP, 32, 36, WHITE, parent=(24, 240)),
                          b.text("Reminder Title", "3 plants need water", 84, 26, 240, 22, size=17, weight=600,
                                 color=WHITE, parent=(24, 240)),
                          b.text("Reminder Body", "Monstera, Pothos and Fern", 84, 50, 240, 20, size=14,
                                 color=(0.86, 0.95, 0.89), parent=(24, 240)),
                      ])
    return b.frame("Home", [
        *status_bar(b),
        b.text("Greeting", "Good morning, Alec", 24, 72, 300, 20, size=15, weight=500, color=MUTED),
        b.text("Heading", "Your garden", 24, 96, 300, 41, size=34, weight=700, spacing=-0.6),
        b.node("ELLIPSE", "Avatar", 321, 82, 48, 48, fills=[{"type": "IMAGE", "scaleMode": "FILL", "imageRef": PHOTO_REF}],
               strokes=[solid(WHITE)], strokeWeight=3, strokeAlign="OUTSIDE", effects=[shadow(4, 12, 0.18)],
               interactions=navigate(ids["Profile"], "DISSOLVE")),
        search,
        reminder,
        b.text("Section", "My plants", 24, 362, 200, 24, size=20, weight=700),
        b.text("See All", "See all", 289, 365, 80, 20, size=15, weight=600, color=GREEN, align="RIGHT"),
        plant_card(b, "Monstera", "Monstera deliciosa", 24, 402, (0.8, 0.9, 0.8), ids["Detail"]),
        plant_card(b, "Snake Plant", "Dracaena trifasciata", 203, 402, (0.85, 0.92, 0.78), None),
        plant_card(b, "Fern", "Nephrolepis exaltata", 24, 632, (0.78, 0.9, 0.86), None),
        plant_card(b, "Pothos", "Epipremnum aureum", 203, 632, (0.9, 0.93, 0.78), None),
        plant_card(b, "Calathea", "Goeppertia orbifolia", 24, 862, (0.82, 0.9, 0.84), None),
        plant_card(b, "Fiddle Leaf", "Ficus lyrata", 203, 862, (0.88, 0.92, 0.8), None),
        b.text("Footer", "You're all caught up", 24, 1100, 345, 20, size=14, color=MUTED, align="CENTER"),
        tab_bar(b, "Home", {"Profile": ids["Profile"]}),
    ], [solid(CREAM)], height=1220, fixed=1)


def stat(b: Builder, label: str, value: str, path: str, x: float, y: float, parent: tuple[float, float]) -> dict[str, Any]:
    p = (parent[0] + x, parent[1] + y)
    return b.node("FRAME", f"Stat {label}", x, y, 105, 112, parent, fills=[solid(WHITE)], cornerRadius=20,
                  effects=[shadow(6, 18, 0.08)],
                  children=[
                      b.node("ELLIPSE", "Icon Bg", 14, 14, 36, 36, p, fills=[solid((0.9, 0.96, 0.92))]),
                      icon(b, f"{label} Icon", path, 20, 20, GREEN, parent=p),
                      b.text("Value", value, 14, 60, 85, 22, size=17, weight=700, parent=p),
                      b.text("Label", label, 14, 84, 85, 16, size=12, color=MUTED, parent=p),
                  ])


def detail(ids: dict[str, str]) -> dict[str, Any]:
    b = Builder(1000)
    photo = b.node("RECTANGLE", "Photo", 0, 0, W, 420, fills=[{"type": "IMAGE", "scaleMode": "FILL", "imageRef": PHOTO_REF}])
    scrim = b.node("RECTANGLE", "Scrim", 0, 0, W, 140, fills=[linear((0, 0, 0), (0, 0, 0), a0=0.35, a1=0.0)])
    back_btn = b.node("FRAME", "Back Button", 20, 56, 44, 44, fills=[solid(WHITE, opacity=0.9)], cornerRadius=22,
                      effects=[shadow(4, 12, 0.15)], interactions=back(), children=[chevron(b, "Chevron", 9, 10, DARK, parent=(20, 56))])
    fav = b.node("FRAME", "Favorite", 329, 56, 44, 44, fills=[solid(WHITE, opacity=0.9)], cornerRadius=22,
                 effects=[shadow(4, 12, 0.15)], children=[icon(b, "Heart", HEART, 10, 11, (0.9, 0.3, 0.35), parent=(329, 56))])
    sheet = b.node("FRAME", "Sheet", 0, 380, W, 472, fills=[solid(CREAM)], rectangleCornerRadii=[32, 32, 0, 0],
                   cornerRadius=32, clipsContent=True, children=[
                       b.node("RECTANGLE", "Grabber", 176, 10, 40, 5, (0, 380), fills=[solid(MUTED, 0.3)], cornerRadius=3),
                       b.text("Plant Name", "Monstera", 24, 32, 260, 41, size=34, weight=700, spacing=-0.6, parent=(0, 380)),
                       b.text("Plant Latin", "Monstera deliciosa · Indoor", 24, 76, 300, 20, size=15, color=MUTED, parent=(0, 380)),
                       stat(b, "Water", "250 ml", DROP, 24, 116, (0, 380)),
                       stat(b, "Light", "Indirect", SUN, 144, 116, (0, 380)),
                       stat(b, "Humidity", "60%", LEAF, 264, 116, (0, 380)),
                       b.text("About Title", "About", 24, 252, 200, 24, size=20, weight=700, parent=(0, 380)),
                       b.text("About Body", "Known for its dramatic split leaves, the Monstera thrives in bright, indirect "
                              "light. Water when the top few centimetres of soil feel dry and wipe the leaves "
                              "monthly to keep them glossy.", 24, 284, 345, 88, size=15, color=MUTED, line=22,
                              parent=(0, 380)),
                       b.node("FRAME", "Water Now", 24, 392, 345, 56, (0, 380), fills=[solid(GREEN)], cornerRadius=28,
                              effects=[shadow(10, 22, 0.25)], children=[
                                  b.text("Water Label", "Water now", 0, 17, 345, 22, size=17, weight=600, color=WHITE,
                                         align="CENTER", parent=(24, 772)),
                              ]),
                   ])
    return b.frame("Plant Detail", [photo, scrim, back_btn, fav, sheet], [solid(CREAM)])


def profile(ids: dict[str, str]) -> dict[str, Any]:
    b = Builder(1500)
    rows = []
    for i, (label, value) in enumerate((("Plants", "12"), ("Watering streak", "18 days"), ("Reminders", "On"),
                                        ("Units", "Metric"))):
        y = 400 + i * 64
        row = b.node("FRAME", f"Row {label}", 24, y, 345, 64, fills=[], children=[
            b.text("Row Label", label, 20, 21, 200, 22, size=16, weight=500, parent=(24, y)),
            b.text("Row Value", value, 165, 21, 160, 22, size=16, color=MUTED, align="RIGHT", parent=(24, y)),
        ])
        if i < 3:
            row["strokes"] = [solid((0.9, 0.91, 0.9))]
            row["individualStrokeWeights"] = {"top": 0, "right": 0, "bottom": 1, "left": 0}
        rows.append(row)
    card = b.node("FRAME", "Settings Card", 24, 380, 345, 296, fills=[solid(WHITE)], cornerRadius=24, effects=[shadow()],
                  children=[])
    return b.frame("Profile", [
        b.node("RECTANGLE", "Header", 0, 0, W, 300, fills=[linear((0.27, 0.66, 0.45), GREEN, start=(0, 0), end=(1, 1))],
               rectangleCornerRadii=[0, 0, 40, 40]),
        *status_bar(b, WHITE),
        b.node("ELLIPSE", "Avatar Large", 136, 92, 120, 120, fills=[{"type": "IMAGE", "scaleMode": "FILL", "imageRef": PHOTO_REF}],
               strokes=[solid(WHITE)], strokeWeight=4, strokeAlign="OUTSIDE", effects=[shadow(10, 24, 0.25)]),
        b.text("Name", "Alec", 24, 228, 345, 30, size=26, weight=700, color=WHITE, align="CENTER"),
        b.text("Handle", "Plant parent since 2024", 24, 262, 345, 20, size=15, color=(0.86, 0.95, 0.89), align="CENTER"),
        card,
        *rows,
        tab_bar(b, "Profile", {"Home": ids["Home"]}),
    ], [solid(CREAM)])


def make_photo(path: Path) -> None:
    size = 480
    img = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(img)
    for y in range(size):
        t = y / size
        draw.line([(0, y), (size, y)], fill=(int(214 - 40 * t), int(226 - 30 * t), int(205 - 50 * t)))
    draw.ellipse([120, 330, 360, 520], fill=(170, 110, 80))
    leaf = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ld = ImageDraw.Draw(leaf)
    for angle, length, shade in ((-60, 210, 0), (-20, 240, 20), (25, 230, 10), (65, 200, 30), (-95, 170, 15), (100, 160, 5)):
        rad = math.radians(angle - 90)
        cx, cy = 240 + math.cos(rad) * length * 0.55, 360 + math.sin(rad) * length * 0.55
        rx, ry = 70, length * 0.48
        poly = []
        for k in range(48):
            t = 2 * math.pi * k / 48
            px, py = rx * math.cos(t), ry * math.sin(t)
            r2 = math.radians(angle)
            poly.append((cx + px * math.cos(r2) - py * math.sin(r2), cy + px * math.sin(r2) + py * math.cos(r2)))
        ld.polygon(poly, fill=(36 + shade, 110 + shade, 64 + shade // 2, 255))
        ld.line([(240, 360), (cx, cy)], fill=(28, 80, 46, 255), width=4)
    shadow_layer = leaf.split()[3].filter(ImageFilter.GaussianBlur(10))
    img.paste((40, 60, 40), (8, 14), Image.eval(shadow_layer, lambda v: v // 3))
    img.paste(leaf, (0, 0), leaf)
    img.save(path, optimize=True)


def main() -> None:
    ids: dict[str, str] = {}
    # Frame ids are needed before the frames exist, so reserve them up front.
    for name in ("Welcome", "Home", "Detail", "Profile"):
        ids[name] = f"{next(_ids)}:{next(_ids)}"
    frames = [welcome(ids), home(ids), detail(ids), profile(ids)]
    for frame, key in zip(frames, ("Welcome", "Home", "Detail", "Profile")):
        frame["id"] = ids[key]
    document = {
        "name": "Luvatrix Plant Care",
        "lastModified": "2026-11-02T00:00:00Z",
        "version": "1",
        "schemaVersion": 0,
        "document": {
            "id": "0:0",
            "name": "Document",
            "type": "DOCUMENT",
            "children": [{
                "id": "0:1",
                "name": "App",
                "type": "CANVAS",
                "backgroundColor": rgba((0.12, 0.12, 0.12)),
                "flowStartingPoints": [{"nodeId": ids["Welcome"], "name": "Onboarding"}],
                "prototypeStartNodeID": ids["Welcome"],
                "children": frames,
            }],
        },
        "components": {},
        "styles": {},
    }
    DESIGN_DIR.mkdir(parents=True, exist_ok=True)
    (DESIGN_DIR / "images").mkdir(exist_ok=True)
    make_photo(DESIGN_DIR / "images" / f"{PHOTO_REF}.png")
    (DESIGN_DIR / "figma_file.json").write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {DESIGN_DIR / 'figma_file.json'}")


if __name__ == "__main__":
    main()
