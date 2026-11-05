"""Native composer for the Nomic iOS app.

The captured web composer is a picture of a text field: tapping it cannot
summon the iOS keyboard, and its pixels cannot show a caret. This module
replaces those captured pixels at load time with an authored native composer
node tree — placeholder, live value text, caret, and a send button — driven by
`luvatrix_core.platform.ios.text_input` (a hidden UITextView owns first
responder, so typing, autocorrect, and the keyboard itself are the real iOS
ones). Keyboard frame notifications lift the composer and the floating tab
capsule in sync with the keyboard; Send appends a natively rendered user
bubble plus a quiet stub to the Conversation screen.

Design language follows the clean harness composers (Cursor / ChatGPT /
Claude): one rounded surface, a hairline that turns into an accent ring while
focused, multiline growth to five lines, and a teal send button that is only
enabled with real text.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

from luvatrix_ui.figma import FigmaApp, FigmaDocument
from luvatrix_core.platform.ios.text_input import IOSTextInput, default_text_input, poll_text_input_events

APP_DIR = Path(__file__).resolve().parent


def _load_assemble():
    spec = importlib.util.spec_from_file_location("nomic_ios_assemble", APP_DIR / "assemble_capture.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_asm = _load_assemble()

TAB_BAR_Y = _asm.TAB_BAR_Y
COMPOSER_GAP = _asm.COMPOSER_BAR_GAP_PT
FRAME_W = _asm.FRAME_W
VIEWPORT_H = _asm.VIEWPORT_H
COMPOSER_NEEDLE = _asm.COMPOSER_NEEDLE

PLACEHOLDER = "Ask anything"
STUB_TEXT = "Sign-in is coming — live responses land with the auth bridges."

COMPOSER_X = 16.0
COMPOSER_W = 370.0
TEXT_LEFT = 16.0
SEND_D = 32.0
SEND_RIGHT = 8.0
SEND_BOTTOM = 10.0
TEXT_W = COMPOSER_W - TEXT_LEFT - SEND_RIGHT - SEND_D - 8.0
FONT_SIZE = 17.0
LINE_HEIGHT = 22.0
MAX_LINES = 5
PAD_TOP = 15.0
PAD_BOTTOM = 15.0
MIN_HEIGHT = PAD_TOP + LINE_HEIGHT + PAD_BOTTOM
MAX_HEIGHT = PAD_TOP + MAX_LINES * LINE_HEIGHT + PAD_BOTTOM
CORNER_RADIUS = 20.0
CARET_W = 2.0
CARET_H = 20.0
BUBBLE_MAX_W = 0.78 * FRAME_W
BUBBLE_PAD_X = 12.0
BUBBLE_PAD_Y = 10.0
BUBBLE_RADIUS = 18.0
STUB_FONT_SIZE = 15.0

GRAY_400 = (145, 148, 146)


@dataclass(frozen=True)
class ComposerTheme:
    """Per-appearance composer palette, derived from the Nomic tokens."""

    surface: tuple[int, int, int]
    stroke_rgb: tuple[int, int, int]
    stroke_opacity: float
    accent: tuple[int, int, int]
    text: tuple[int, int, int]
    placeholder: tuple[int, int, int]
    caret: tuple[int, int, int]
    send_enabled_glyph: tuple[int, int, int]
    send_disabled_fill: tuple[int, int, int]
    send_disabled_opacity: float
    send_disabled_glyph: tuple[int, int, int]
    bubble_fill: tuple[int, int, int]
    bubble_text: tuple[int, int, int]


_THEMES = {
    "light": ComposerTheme(
        surface=(255, 255, 255),
        stroke_rgb=(0, 0, 0),
        stroke_opacity=0.10,
        accent=_asm.TAB_ACCENT_LIGHT,  # teal-600
        text=(25, 29, 26),  # gray-900
        placeholder=GRAY_400,
        caret=_asm.TAB_ACCENT_LIGHT,
        send_enabled_glyph=(255, 255, 255),
        send_disabled_fill=(0, 0, 0),
        send_disabled_opacity=0.06,
        send_disabled_glyph=GRAY_400,
        bubble_fill=(241, 241, 234),  # gray-100
        bubble_text=(25, 29, 26),
    ),
    "dark": ComposerTheme(
        surface=(38, 43, 40),  # raised gray-800 over the gray-900 canvas
        stroke_rgb=(255, 255, 255),
        stroke_opacity=0.14,
        accent=_asm.TAB_ACCENT_DARK,  # teal-400
        text=(241, 241, 234),  # gray-100
        placeholder=GRAY_400,
        caret=_asm.TAB_ACCENT_DARK,
        send_enabled_glyph=(25, 29, 26),
        send_disabled_fill=(255, 255, 255),
        send_disabled_opacity=0.10,
        send_disabled_glyph=GRAY_400,
        bubble_fill=(45, 50, 47),
        bubble_text=(241, 241, 234),
    ),
}


def composer_theme(appearance: str) -> ComposerTheme:
    try:
        return _THEMES[appearance]
    except KeyError:
        names = ", ".join(sorted(_THEMES))
        raise ValueError(f"unknown appearance {appearance!r}; expected one of: {names}") from None


# ── text measurement (caret placement and multiline growth) ──────────────────


class TextMeasure:
    """Greedy word wrap + measuring in the composer's own font (Inter 17)."""

    def __init__(self) -> None:
        from luvatrix_ui.figma.text import FontLibrary

        self._fonts = FontLibrary()
        self._font: Any = None

    def _face(self) -> Any:
        if self._font is None:
            path = self._fonts.resolve("Inter", 400, False)
            self._font = self._fonts.font(path, FONT_SIZE)
        return self._font

    def measure(self, text: str) -> float:
        if not text:
            return 0.0
        return float(self._face().getlength(text))

    def wrap(self, text: str, width: float) -> list[tuple[int, str]]:
        """(start index, line) pairs; empty input wraps to one empty line."""
        out: list[tuple[int, str]] = []
        idx = 0
        for para in text.split("\n"):
            line = ""
            line_start = idx
            pos = idx
            for match in re.finditer(r"[^ ]+ *| +", para):
                word = match.group()
                if line and self.measure((line + word).rstrip(" ")) > width:
                    out.append((line_start, line))
                    line_start = pos
                    line = word
                    while len(line) > 1 and self.measure(line.rstrip(" ")) > width:
                        cut = len(line) - 1
                        while cut > 1 and self.measure(line[:cut]) > width:
                            cut -= 1
                        out.append((line_start, line[:cut]))
                        line_start += cut
                        line = line[cut:]
                else:
                    line = line + word
                pos += len(word)
            out.append((line_start, line))
            idx += len(para) + 1
        return out

    def caret(self, text: str, selection: int, width: float) -> tuple[int, float]:
        """(line index, x offset within the line) for a caret at `selection`."""
        lines = self.wrap(text, width)
        selection = max(0, min(selection, len(text)))
        for i, (start, line) in enumerate(lines):
            end = start + len(line)
            if selection <= end or i == len(lines) - 1:
                col = max(0, min(selection - start, len(line)))
                return i, min(self.measure(line[:col]), width)
        return 0, 0.0


# ── node builders ─────────────────────────────────────────────────────────────


def _solid(rgb: tuple[int, int, int], opacity: float = 1.0) -> dict[str, Any]:
    return {"type": "SOLID", "color": {"r": rgb[0] / 255, "g": rgb[1] / 255, "b": rgb[2] / 255}, "opacity": opacity}


def _text_style(size: float, *, weight: float = 400) -> dict[str, Any]:
    return {
        "fontFamily": "Inter",
        "fontWeight": weight,
        "fontSize": size,
        "textAlignHorizontal": "LEFT",
        "textAlignVertical": "TOP",
        "textAutoResize": "NONE",
        "lineHeightPx": LINE_HEIGHT if size == FONT_SIZE else size * 1.3,
        "lineHeightUnit": "PIXELS",
    }


def _send_glyph_path() -> str:
    """Filled arrow-up glyph on a 24x24 grid, after SF Symbols arrow.up."""
    return (
        "M12 4 a1.5 1.5 0 0 0 -1.06 0.44 l-6 6 a1.5 1.5 0 1 0 2.12 2.12 "
        "l3.44 -3.44 V19.5 a1.5 1.5 0 0 0 3 0 V9.12 l3.44 3.44 "
        "a1.5 1.5 0 1 0 2.12 -2.12 l-6 -6 A1.5 1.5 0 0 0 12 4 Z"
    )


def build_composer_node(slug: str, *, x: float, y: float, theme: ComposerTheme) -> dict[str, Any]:
    """The native composer: rounded surface, placeholder, value, caret, send."""
    text_x = x + TEXT_LEFT
    text_y = y + PAD_TOP
    return {
        "id": f"composer:{slug}:root",
        "type": "FRAME",
        "name": "Composer",
        "absoluteBoundingBox": {"x": x, "y": y, "width": COMPOSER_W, "height": MIN_HEIGHT},
        "cornerRadius": CORNER_RADIUS,
        "clipsContent": True,
        "fills": [_solid(theme.surface)],
        "strokes": [_solid(theme.stroke_rgb, theme.stroke_opacity)],
        "strokeWeight": 1.0,
        "strokeAlign": "INSIDE",
        "effects": [
            {
                "type": "DROP_SHADOW",
                "color": {"r": 0, "g": 0, "b": 0, "a": 0.06},
                "offset": {"x": 0, "y": 2},
                "radius": 8,
                "visible": True,
            }
        ],
        "children": [
            {
                "id": f"composer:{slug}:placeholder",
                "type": "TEXT",
                "name": "Composer Placeholder",
                "characters": PLACEHOLDER,
                "visible": True,
                "absoluteBoundingBox": {"x": text_x, "y": text_y, "width": TEXT_W, "height": LINE_HEIGHT},
                "style": _text_style(FONT_SIZE),
                "fills": [_solid(theme.placeholder)],
            },
            {
                "id": f"composer:{slug}:value",
                "type": "TEXT",
                "name": "Composer Text",
                "characters": "",
                "visible": True,
                "absoluteBoundingBox": {"x": text_x, "y": text_y, "width": TEXT_W, "height": LINE_HEIGHT},
                "style": _text_style(FONT_SIZE),
                "fills": [_solid(theme.text)],
            },
            {
                "id": f"composer:{slug}:caret",
                "type": "RECTANGLE",
                "name": "Composer Caret",
                "visible": False,
                "absoluteBoundingBox": {"x": text_x, "y": text_y + (LINE_HEIGHT - CARET_H) / 2, "width": CARET_W, "height": CARET_H},
                "fills": [_solid(theme.caret)],
            },
            {
                "id": f"composer:{slug}:send",
                "type": "FRAME",
                "name": "Composer Send",
                "absoluteBoundingBox": {
                    "x": x + COMPOSER_W - SEND_RIGHT - SEND_D,
                    "y": y + MIN_HEIGHT - SEND_BOTTOM - SEND_D,
                    "width": SEND_D,
                    "height": SEND_D,
                },
                "cornerRadius": SEND_D / 2,
                "clipsContent": False,
                "fills": [_solid(theme.send_disabled_fill, theme.send_disabled_opacity)],
                "children": [
                    {
                        "id": f"composer:{slug}:send:glyph",
                        "type": "VECTOR",
                        "name": "icon",
                        "absoluteBoundingBox": {
                            "x": x + COMPOSER_W - SEND_RIGHT - SEND_D + 7,
                            "y": y + MIN_HEIGHT - SEND_BOTTOM - SEND_D + 7,
                            "width": 18,
                            "height": 18,
                        },
                        "size": {"x": 18, "y": 18},
                        "vectorPaths": [{"path": _send_glyph_path(), "windingRule": "NONZERO"}],
                        "fills": [_solid(theme.send_disabled_glyph)],
                        "strokes": [],
                    }
                ],
            },
        ],
    }


def _walk_all(node: dict[str, Any]) -> list[dict[str, Any]]:
    out = [node]
    for child in node.get("children") or ():
        out.extend(_walk_all(child))
    return out


def _path_to_text(node: dict[str, Any], needle: str) -> list[dict[str, Any]] | None:
    if node.get("type") == "TEXT" and needle in str(node.get("characters", "")):
        return [node]
    for child in node.get("children") or ():
        found = _path_to_text(child, needle)
        if found is not None:
            return [node, *found]
    return None


def _find_named(node: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((n for n in _walk_all(node) if n.get("name") == name), None)


def _screens(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(frame.get("name", "")): frame
        for page in payload["document"]["children"]
        for frame in page.get("children") or ()
    }


def _content_bottom(screen: dict[str, Any], fixed_count: int) -> float:
    """Bottom of the scrolling content's last text (the conversation's end)."""
    bottom = 0.0
    for child in screen.get("children", [])[: max(0, len(screen.get("children", [])) - fixed_count)]:
        for node in _walk_all(child):
            if node.get("type") == "TEXT":
                box = node.get("absoluteBoundingBox") or {}
                bottom = max(bottom, float(box.get("y", 0.0)) + float(box.get("height", 0.0)))
    return bottom


def install(payload: dict[str, Any], appearance: str = "light") -> bool:
    """Swap the captured composer pixels for a native composer, in one design payload.

    Conversation's pinned composer keeps its fixed slot above the floating tab
    bar; Assistant's hero composer is replaced in place in the scroll content.
    A ``Conversation Replies`` container is added to hold natively rendered
    send bubbles. Idempotent; returns True when both screens carry a composer.
    """
    theme = composer_theme(appearance)
    screens = _screens(payload)
    ok = True

    convo = screens.get("Conversation")
    if convo is None:
        ok = False
    elif _find_named(convo, "Composer") is None:
        fixed = int(convo.get("numberOfFixedChildren", 0) or 0)
        bottom = TAB_BAR_Y - COMPOSER_GAP
        native = build_composer_node("conversation", x=COMPOSER_X, y=bottom - MIN_HEIGHT, theme=theme)
        children = convo.get("children") or []
        if fixed >= 3 and children:
            children[-3] = native
        else:
            children.insert(max(0, len(children) - fixed), native)
            convo["numberOfFixedChildren"] = fixed + 1
        replies_y = _content_bottom(convo, int(convo.get("numberOfFixedChildren", 0))) + 24.0
        children.insert(
            len(children) - int(convo.get("numberOfFixedChildren", 0)),
            {
                "id": "composer:conversation:replies",
                "type": "FRAME",
                "name": "Conversation Replies",
                "absoluteBoundingBox": {"x": 0.0, "y": replies_y, "width": FRAME_W, "height": 0.0},
                "clipsContent": False,
                "fills": [],
                "children": [],
            },
        )

    assistant = screens.get("Assistant")
    if assistant is None:
        ok = False
    elif _find_named(assistant, "Composer") is None:
        path = _path_to_text(assistant, COMPOSER_NEEDLE)
        blocks = [n for n in (path[1:-1] if path else []) if float((n.get("absoluteBoundingBox") or {}).get("height", 1e9)) <= 160.0]
        if not blocks:
            ok = False
        else:
            block = blocks[0]
            parent = path[path.index(block) - 1]
            box = block["absoluteBoundingBox"]
            native = build_composer_node("assistant", x=float(box["x"]), y=float(box["y"]), theme=theme)
            parent["children"] = [native if child is block else child for child in parent["children"]]

    return ok


# ── runtime controller ────────────────────────────────────────────────────────


def _ease_out_cubic(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3


class ComposerController:
    """Owns composer state and keeps the native field, chrome, and bubbles in sync."""

    def __init__(self, text_input: IOSTextInput | None = None) -> None:
        self.text_input = text_input or default_text_input()
        self.text = ""
        self.selection = 0
        self.focused = False
        self.keyboard_offset = 0.0
        self._kb_target = 0.0
        self._kb_from = 0.0
        self._kb_duration = 0.0
        self._kb_elapsed = 0.0
        self._measurer = TextMeasure()
        self._content_h: dict[int, float] = {}
        self._bubble_count = 0
        self.app: NomicIOSApp | None = None

    # ── wiring ───────────────────────────────────────────────────────────

    def attach(self, app: "NomicIOSApp") -> None:
        self.app = app
        app.on_tap("Composer", self._on_composer_tap)
        app.on_tap("Composer Send", self._on_send_tap)
        self.text_input.set_placeholder(PLACEHOLDER)
        for doc in app._documents.values():
            self._content_h[id(doc)] = self._conversation_height(doc)

    @staticmethod
    def _conversation_height(doc: FigmaDocument) -> float:
        try:
            frame = doc.frame_by_name("Conversation")
        except KeyError:
            return VIEWPORT_H
        return float(frame.node.get("absoluteBoundingBox", {}).get("height", VIEWPORT_H))

    @property
    def theme(self) -> ComposerTheme:
        return composer_theme(self.app.appearance if self.app is not None else "light")

    @property
    def send_enabled(self) -> bool:
        return bool(self.text.strip())

    def _on_composer_tap(self, app: "NomicIOSApp", node: str) -> bool:
        _ = node
        self.focus(app)
        return False

    def _on_send_tap(self, app: "NomicIOSApp", node: str) -> bool:
        _ = node
        self.send()
        return False

    # ── focus ────────────────────────────────────────────────────────────

    def focus(self, app: "NomicIOSApp") -> None:
        self.focused = True
        self.text_input.focus()
        self._sync_chrome(app)

    def resign(self, app: "NomicIOSApp") -> None:
        self.focused = False
        self.text_input.resign()
        self._sync_chrome(app)

    # ── text state ───────────────────────────────────────────────────────

    def inject_text(self, text: str, selection: int | None = None) -> None:
        """Replace the draft (native delegate events land here via `tick`)."""
        self.text = str(text)
        self.selection = len(self.text) if selection is None else max(0, min(int(selection), len(self.text)))
        if self.app is not None:
            self._sync_chrome(self.app)

    def tick(self, app: "NomicIOSApp", dt: float) -> None:
        changed = False
        for event in poll_text_input_events():
            kind = event.get("type")
            if kind == "text":
                self.text = str(event.get("text", ""))
                self.selection = int(event.get("selection", len(self.text)))  # type: ignore[arg-type]
                changed = True
            elif kind == "keyboard":
                self.apply_keyboard(float(event.get("height", 0.0)), duration=float(event.get("duration", 0.25)))  # type: ignore[arg-type]
            elif kind == "editing_end":
                self.focused = False
                changed = True
        if changed:
            self._sync_chrome(app)
        if self.keyboard_offset != self._kb_target:
            self._kb_elapsed += dt
            t = 1.0 if self._kb_duration <= 0 else min(1.0, self._kb_elapsed / self._kb_duration)
            self.keyboard_offset = self._kb_from + (self._kb_target - self._kb_from) * _ease_out_cubic(t)
            if t >= 1.0:
                self.keyboard_offset = self._kb_target
            self._layout_chrome(app)

    def apply_keyboard(self, height: float, *, duration: float = 0.25) -> None:
        """Aim the keyboard avoidance at `height` (0 = hidden)."""
        height = max(0.0, float(height))
        self._kb_from = self.keyboard_offset
        self._kb_target = height
        self._kb_duration = max(0.0, float(duration))
        self._kb_elapsed = 0.0
        if self._kb_duration <= 0 and self.app is not None:
            self.keyboard_offset = height
            self._kb_from = height
            self._layout_chrome(self.app)

    # ── send flow ────────────────────────────────────────────────────────

    def send(self) -> bool:
        app = self.app
        if app is None:
            return False
        text = self.text.strip()
        if not text:
            return False
        if app.current_frame_name != "Conversation":
            app.navigate("Conversation")
        self._append_turn(app, text)
        self.text = ""
        self.selection = 0
        self.text_input.set_text("")
        self._sync_chrome(app)
        self._scroll_to_bottom(app)
        return True

    def _append_turn(self, app: "NomicIOSApp", text: str) -> None:
        # Both variants get the bubbles so an appearance swap keeps the thread.
        for appearance, doc in app._documents.items():
            self._append_turn_in(doc, text, composer_theme(appearance))

    def _append_turn_in(self, doc: FigmaDocument, text: str, theme: ComposerTheme) -> None:
        try:
            frame = doc.frame_by_name("Conversation")
        except KeyError:
            return
        replies = _find_named(frame.node, "Conversation Replies")
        if replies is None:
            return
        box = replies["absoluteBoundingBox"]
        cursor = float(box["y"]) + float(box["height"])
        bubble, bubble_h = self._build_bubble(text, y=cursor, theme=theme)
        stub_y = cursor + bubble_h + 8.0
        stub = {
            "id": f"composer:conversation:stub{self._bubble_count}",
            "type": "TEXT",
            "name": "Stub Reply",
            "characters": STUB_TEXT,
            "absoluteBoundingBox": {"x": COMPOSER_X, "y": stub_y, "width": COMPOSER_W, "height": 20.0},
            "style": _text_style(STUB_FONT_SIZE),
            "fills": [_solid(GRAY_400)],
        }
        replies.setdefault("children", []).extend([bubble, stub])
        box["height"] = stub_y + 20.0 + 24.0 - float(box["y"])
        self._bubble_count += 1
        content_bottom = stub_y + 20.0 + 12.0
        needed = content_bottom + (VIEWPORT_H - (TAB_BAR_Y - COMPOSER_GAP - self._current_composer_height())) + 12.0
        self._grow_conversation(doc, max(self._content_h.get(id(doc), VIEWPORT_H), needed))

    def _build_bubble(self, text: str, *, y: float, theme: ComposerTheme) -> tuple[dict[str, Any], float]:
        max_text_w = BUBBLE_MAX_W - 2 * BUBBLE_PAD_X
        lines = self._measurer.wrap(text, max_text_w)
        text_h = len(lines) * LINE_HEIGHT
        text_w = min(max((self._measurer.measure(line) for _start, line in lines), default=0.0), max_text_w)
        bubble_w = max(text_w + 2 * BUBBLE_PAD_X, 2 * BUBBLE_RADIUS)
        bubble_h = text_h + 2 * BUBBLE_PAD_Y
        x = FRAME_W - COMPOSER_X - bubble_w
        node = {
            "id": f"composer:conversation:bubble{self._bubble_count}",
            "type": "FRAME",
            "name": "User Bubble",
            "absoluteBoundingBox": {"x": x, "y": y, "width": bubble_w, "height": bubble_h},
            "cornerRadius": BUBBLE_RADIUS,
            "clipsContent": True,
            "fills": [_solid(theme.bubble_fill)],
            "children": [
                {
                    "id": f"composer:conversation:bubble{self._bubble_count}:text",
                    "type": "TEXT",
                    "name": "User Message",
                    "characters": text,
                    "absoluteBoundingBox": {
                        "x": x + BUBBLE_PAD_X,
                        "y": y + BUBBLE_PAD_Y,
                        "width": bubble_w - 2 * BUBBLE_PAD_X,
                        "height": text_h,
                    },
                    "style": _text_style(FONT_SIZE),
                    "fills": [_solid(theme.bubble_text)],
                }
            ],
        }
        return node, bubble_h

    def _current_composer_height(self) -> float:
        lines = self._measurer.wrap(self.text, TEXT_W) if self.text else []
        visible = max(1, min(len(lines), MAX_LINES))
        return PAD_TOP + visible * LINE_HEIGHT + PAD_BOTTOM

    def _grow_conversation(self, doc: FigmaDocument, height: float) -> None:
        self._content_h[id(doc)] = height
        try:
            frame = doc.frame_by_name("Conversation")
        except KeyError:
            return
        self._set_frame_height(doc, frame, height + self.keyboard_offset)

    def _set_frame_height(self, doc: FigmaDocument, frame: Any, height: float) -> None:
        _ = doc
        box = frame.node.get("absoluteBoundingBox")
        if box is not None and abs(float(box.get("height", 0.0)) - height) > 0.01:
            box["height"] = height
            object.__setattr__(frame, "height", height)
            object.__setattr__(frame, "scrolls_vertically", True)
            if self.app is not None:
                self._invalidate(self.app, frame.id)

    def _scroll_to_bottom(self, app: "NomicIOSApp") -> None:
        if app.current_frame_name == "Conversation":
            app._scroll_to(math.inf)

    # ── chrome sync ──────────────────────────────────────────────────────

    def _invalidate(self, app: "NomicIOSApp", frame_id: str) -> None:
        for key in [k for k in app._screens if k[0] == frame_id]:
            del app._screens[key]
        app._targets.pop(frame_id, None)
        app._fixed_bounds.pop(frame_id, None)
        app.invalidate()

    def _composer_root(self, app: "NomicIOSApp") -> dict[str, Any] | None:
        frame_node = app.document.node(app.current_frame_id)
        return _find_named(frame_node, "Composer")

    def _sync_chrome(self, app: "NomicIOSApp") -> None:
        root = self._composer_root(app)
        if root is not None:
            self._sync_value(app, root)
        self._layout_chrome(app)

    def _sync_value(self, app: "NomicIOSApp", root: dict[str, Any]) -> None:
        theme = self.theme
        box = root["absoluteBoundingBox"]
        rx, ry = float(box["x"]), float(box["y"])
        lines = self._measurer.wrap(self.text, TEXT_W) if self.text else []
        visible_lines = max(1, min(len(lines), MAX_LINES))
        height = PAD_TOP + visible_lines * LINE_HEIGHT + PAD_BOTTOM
        box["height"] = height
        box["y"] = self._composer_top(app, height)
        ry = float(box["y"])

        text_x = rx + TEXT_LEFT
        text_y = ry + PAD_TOP
        caret_line, caret_x = self._measurer.caret(self.text, self.selection, TEXT_W)
        total_h = max(1, len(lines)) * LINE_HEIGHT
        scroll = max(0.0, (caret_line + 1) * LINE_HEIGHT - visible_lines * LINE_HEIGHT)

        placeholder = _find_named(root, "Composer Placeholder")
        value = _find_named(root, "Composer Text")
        caret = _find_named(root, "Composer Caret")
        send = _find_named(root, "Composer Send")

        if placeholder is not None:
            placeholder["visible"] = not self.text
            pbox = placeholder["absoluteBoundingBox"]
            pbox["x"], pbox["y"] = text_x, text_y
        if value is not None:
            if value.get("characters") != self.text:
                value["characters"] = self.text
                value["characterStyleOverrides"] = []
            vbox = value["absoluteBoundingBox"]
            vbox["x"], vbox["y"] = text_x, text_y - scroll
            vbox["width"], vbox["height"] = TEXT_W, total_h
        if caret is not None:
            caret["visible"] = self.focused
            cbox = caret["absoluteBoundingBox"]
            cbox["x"] = text_x + caret_x
            cbox["y"] = text_y - scroll + caret_line * LINE_HEIGHT + (LINE_HEIGHT - CARET_H) / 2
        if send is not None:
            enabled = self.send_enabled
            send["fills"] = [_solid(theme.accent if enabled else theme.send_disabled_fill, 1.0 if enabled else theme.send_disabled_opacity)]
            sbox = send["absoluteBoundingBox"]
            sbox["x"] = rx + COMPOSER_W - SEND_RIGHT - SEND_D
            sbox["y"] = ry + height - SEND_BOTTOM - SEND_D
            glyph = _find_named(send, "icon")
            if glyph is not None:
                glyph["fills"] = [_solid(theme.send_enabled_glyph if enabled else theme.send_disabled_glyph)]
                gbox = glyph["absoluteBoundingBox"]
                gbox["x"], gbox["y"] = sbox["x"] + 7, sbox["y"] + 7

        root["strokes"] = [_solid(theme.accent, 1.0) if self.focused else _solid(theme.stroke_rgb, theme.stroke_opacity)]
        root["strokeWeight"] = 1.5 if self.focused else 1.0
        self._invalidate(app, app.current_frame_id)

    def _composer_top(self, app: "NomicIOSApp", height: float) -> float:
        if app.current_frame_name == "Conversation":
            return TAB_BAR_Y - COMPOSER_GAP - self.keyboard_offset - height
        root = self._composer_root(app)
        return float(root["absoluteBoundingBox"]["y"]) if root is not None else 0.0

    def _layout_chrome(self, app: "NomicIOSApp") -> None:
        """Keyboard avoidance on Conversation: chrome lifts, scroll range grows."""
        if app.current_frame_name != "Conversation":
            return
        frame = app.document.frame(app.current_frame_id)
        root = _find_named(frame.node, "Composer")
        bar = _find_named(frame.node, "Tab Bar")
        if root is None or bar is None:
            return
        box = root["absoluteBoundingBox"]
        box["y"] = TAB_BAR_Y - COMPOSER_GAP - self.keyboard_offset - float(box["height"])
        dy = TAB_BAR_Y - self.keyboard_offset - float(bar["absoluteBoundingBox"]["y"])
        if abs(dy) > 0.01:
            _translate_y(bar, dy)
        self._set_frame_height(app.document, frame, self._content_h.get(id(app.document), VIEWPORT_H) + self.keyboard_offset)
        self._invalidate(app, frame.id)


def _translate_y(node: dict[str, Any], dy: float) -> None:
    box = node.get("absoluteBoundingBox")
    if box is not None:
        box["y"] = float(box.get("y", 0.0)) + dy
    rel = node.get("relativeTransform")
    if isinstance(rel, list) and len(rel) == 2 and "size" in node:
        rel[1][2] = float(rel[1][2]) + dy
    for child in node.get("children") or ():
        _translate_y(child, dy)


# ── the app ───────────────────────────────────────────────────────────────────


class NomicIOSApp(FigmaApp):
    """FigmaApp with the native composer wired into taps, ticks, and resign."""

    def __init__(self, *args: Any, text_input: IOSTextInput | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.composer = ComposerController(text_input=text_input)
        self._down_in_composer = False
        self._down_pos = (0.0, 0.0)

    def setup(self) -> None:
        super().setup()
        self.composer.attach(self)

    def update(self, dt: float) -> None:
        self.composer.tick(self, dt)
        super().update(dt)

    def set_appearance(self, name: str) -> bool:
        changed = super().set_appearance(name)
        if changed:
            self.composer._sync_chrome(self)
        return changed

    def _pointer_phase(self, pointer_id: int, phase: str) -> None:
        if phase == "down" and self.composer.focused:
            spot, overlay_idx, _outside, _scroll_y, _scroll_x = self._press_target()
            _ = overlay_idx
            self._down_in_composer = spot is not None and spot.node_name in {"Composer", "Composer Send"}
            self._down_pos = self._pointer
        super()._pointer_phase(pointer_id, phase)
        if phase == "up" and self.composer.focused and not self._down_in_composer:
            moved = max(abs(self._pointer[0] - self._down_pos[0]), abs(self._pointer[1] - self._down_pos[1]))
            if moved <= 6.0:
                self.composer.resign(self)


def _prepare_document(source: FigmaDocument | str | Path | dict[str, Any], appearance: str) -> FigmaDocument:
    if isinstance(source, FigmaDocument):
        return source
    base_dir: Path | None = None
    if isinstance(source, (str, Path)):
        path = Path(source)
        payload = json.loads(path.read_text(encoding="utf-8"))
        base_dir = path.parent
    else:
        payload = source
    install(payload, appearance=appearance)
    return FigmaDocument.from_dict(payload, base_dir=base_dir)


def create_app(
    design: FigmaDocument | str | Path | dict[str, Any],
    *,
    dark: FigmaDocument | str | Path | dict[str, Any] | None = None,
    text_input: IOSTextInput | None = None,
    **kwargs: Any,
) -> NomicIOSApp:
    """Build the Nomic iOS app: install the native composer, then boot FigmaApp."""
    light_doc = _prepare_document(design, "light")
    dark_doc = _prepare_document(dark, "dark") if dark is not None else None
    return NomicIOSApp(light_doc, dark=dark_doc, text_input=text_input, **kwargs)
