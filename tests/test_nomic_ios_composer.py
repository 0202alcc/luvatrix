"""The nomic_ios native composer: real keyboard input, caret, and send flow.

The captured web composer pixels are replaced at load time by an authored
native composer node tree (placeholder, value text, caret, send button) in both
design variants. Tapping it focuses the hidden native text field (the real iOS
keyboard), keyboard notifications translate the composer and the floating tab
capsule, and Send appends a natively rendered user bubble plus a quiet stub to
the Conversation screen.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from luvatrix_core.core.hdi_thread import HDIEvent
from luvatrix_core.platform.ios.text_input import (
    IOSTextInput,
    enqueue_native_text_input_events,
    reset_text_input_events,
)

APP_DIR = Path(__file__).resolve().parents[1] / "examples" / "nomic_ios"
DESIGN = APP_DIR / "design" / "figma_file.json"
DESIGN_DARK = APP_DIR / "design" / "figma_file.dark.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def asm():
    return _load_module("nomic_ios_assemble", APP_DIR / "assemble_capture.py")


@pytest.fixture(scope="module")
def composer():
    return _load_module("nomic_ios_composer", APP_DIR / "composer.py")


class FakeSwiftTextInput:
    """Fake for the ObjC `LuvatrixTextInput` boundary (rubicon selector names)."""

    def __init__(self) -> None:
        self.text = ""
        self.placeholder = ""
        self.focused = False
        self.calls: list[tuple[str, ...]] = []

    def focusComposer(self) -> bool:
        self.calls.append(("focus",))
        self.focused = True
        return True

    def resignComposer(self) -> bool:
        self.calls.append(("resign",))
        self.focused = False
        return True

    def setComposerText_(self, value: str) -> None:
        self.calls.append(("set_text", value))
        self.text = value

    def setComposerPlaceholder_(self, value: str) -> None:
        self.calls.append(("set_placeholder", value))
        self.placeholder = value

    def isComposerFocused(self) -> bool:
        return self.focused


class _FakeCtx:
    def __init__(self, width: int = 402, height: int = 874) -> None:
        self._snapshot = np.zeros((height, width, 4), dtype=np.uint8)
        self._events: list[HDIEvent] = []
        self.frames: list[np.ndarray] = []
        self.display_width_px, self.display_height_px = width, height

    def read_matrix_snapshot(self) -> np.ndarray:
        return self._snapshot

    def poll_hdi_events(self, max_events: int, frame: str | None = None) -> list[HDIEvent]:
        _ = (max_events, frame)
        events, self._events = self._events, []
        return events

    def submit_write_batch(self, batch) -> None:
        tensor = batch.operations[0].tensor_h_w_4
        self.frames.append(np.asarray(tensor.cpu() if hasattr(tensor, "cpu") else tensor).copy())

    def queue(self, *events: HDIEvent) -> None:
        self._events.extend(events)


def _touch(phase: str, x: float, y: float) -> HDIEvent:
    return HDIEvent(1, 1, "w", "touch", "touch", "OK", {"touch_id": 1, "phase": phase, "x": x, "y": y})


def _payload(appearance: str = "light") -> dict:
    path = DESIGN if appearance == "light" else DESIGN_DARK
    return json.loads(path.read_text(encoding="utf-8"))


def _screen(payload: dict, name: str) -> dict:
    return next(
        frame
        for page in payload["document"]["children"]
        for frame in page["children"]
        if frame["name"] == name
    )


def _walk(node: dict):
    yield node
    for child in node.get("children") or []:
        yield from _walk(child)


def _find(node: dict, name: str) -> dict | None:
    return next((n for n in _walk(node) if n.get("name") == name), None)


def _box(node: dict) -> tuple[float, float, float, float]:
    b = node["absoluteBoundingBox"]
    return b["x"], b["y"], b["width"], b["height"]


def _rgb(paint: dict) -> tuple[int, int, int]:
    c = paint["color"]
    return round(c["r"] * 255), round(c["g"] * 255), round(c["b"] * 255)


@pytest.fixture()
def app(composer, monkeypatch):
    monkeypatch.delenv("LUVATRIX_APPEARANCE", raising=False)
    monkeypatch.delenv("LUVATRIX_IOS_USER_INTERFACE_STYLE", raising=False)
    reset_text_input_events()
    bridge = FakeSwiftTextInput()
    light = _payload("light")
    dark = _payload("dark")
    app = composer.create_app(light, dark=dark, text_input=IOSTextInput(bridge=bridge))
    ctx = _FakeCtx()
    app.init(ctx)
    app.loop(ctx, 0.016)
    app.test_bridge = bridge
    app.test_ctx = ctx
    yield app
    reset_text_input_events()


# ── install: the captured composer pixels become a native composer ────────────


def test_conversation_composer_is_a_fixed_native_composer_above_the_tab_bar(composer, asm) -> None:
    payload = _payload("light")
    assert composer.install(payload, appearance="light")

    convo = _screen(payload, "Conversation")
    assert convo["numberOfFixedChildren"] == 3
    native = convo["children"][-3]
    assert native["name"] == "Composer"
    assert _find(native, "Composer Placeholder")["characters"] == composer.PLACEHOLDER
    assert _find(native, "Composer Send") is not None
    # No captured web composer chrome survives on the screen.
    assert all(node.get("name") != "Mode Chip" for node in _walk(convo))
    assert all("Integrations/MCPs" not in str(node.get("characters", "")) for node in _walk(convo))
    # The composer hovers above the glass capsule; the two never touch.
    _x, cy, _w, ch = _box(native)
    _x, by, _w, _h = _box(convo["children"][-1])
    assert by - (cy + ch) == pytest.approx(asm.COMPOSER_BAR_GAP_PT)
    assert convo["children"][-1]["name"] == "Tab Bar"


def test_assistant_composer_is_replaced_in_the_scroll_content(composer) -> None:
    payload = _payload("light")
    composer.install(payload, appearance="light")

    assistant = _screen(payload, "Assistant")
    native = _find(assistant, "Composer")
    assert native is not None
    assert native not in assistant["children"][-assistant["numberOfFixedChildren"]:]
    # It sits where the captured hero composer sat.
    x, y, w, _h = _box(native)
    assert (x, w) == (16.0, 370.0)
    assert 150.0 < y < 250.0
    assert all(node.get("name") != "Mode Chip" for node in _walk(assistant))


def test_install_marks_both_variants_with_the_same_node_ids(composer) -> None:
    light, dark = _payload("light"), _payload("dark")
    composer.install(light, appearance="light")
    composer.install(dark, appearance="dark")

    for payload in (light, dark):
        for screen in ("Assistant", "Conversation"):
            assert _find(_screen(payload, screen), "Composer")["id"] == f"composer:{screen.lower()}:root"


# ── focus, typing, and the caret ──────────────────────────────────────────────


def _conversation(app) -> None:
    app.navigate("Conversation")
    app.loop(app.test_ctx, 0.016)


def test_initial_state_shows_the_placeholder_with_a_disabled_send(composer, app) -> None:
    _conversation(app)

    native = _find(app.document.node(app.current_frame_id), "Composer")
    assert _find(native, "Composer Placeholder")["visible"] is not False
    assert _find(native, "Composer Caret").get("visible", True) is False
    assert app.composer.send_enabled is False
    send = _find(native, "Composer Send")
    assert _rgb(send["fills"][0]) != composer.composer_theme("light").accent


def test_tapping_the_composer_focuses_the_native_field(app) -> None:
    _conversation(app)

    app.tap("Composer")
    app.loop(app.test_ctx, 0.016)

    assert app.test_bridge.focused is True
    assert app.composer.focused is True
    native = _find(app.document.node(app.current_frame_id), "Composer")
    assert _find(native, "Composer Caret")["visible"] is not False
    # The focused state reads as an accent ring.
    assert _rgb(native["strokes"][0]) == app.composer.theme.accent


def test_typing_renders_real_text_with_a_caret_and_enables_send(composer, app) -> None:
    _conversation(app)
    app.tap("Composer")

    app.composer.inject_text("Concrete pour")
    app.loop(app.test_ctx, 0.016)

    native = _find(app.document.node(app.current_frame_id), "Composer")
    value = _find(native, "Composer Text")
    assert value["characters"] == "Concrete pour"
    assert _find(native, "Composer Placeholder").get("visible", True) is False
    assert app.composer.send_enabled is True
    caret = _find(native, "Composer Caret")
    assert caret["visible"] is not False
    # The caret sits just past the last glyph on the first line.
    assert caret["absoluteBoundingBox"]["x"] > value["absoluteBoundingBox"]["x"] + 40
    assert caret["absoluteBoundingBox"]["y"] < value["absoluteBoundingBox"]["y"] + composer.LINE_HEIGHT


def test_swift_text_events_drive_the_composer(app) -> None:
    _conversation(app)
    app.tap("Composer")

    enqueue_native_text_input_events([{"type": "text", "text": "Hi there", "selection": 8}])
    app.loop(app.test_ctx, 0.016)

    assert app.composer.text == "Hi there"


def test_return_key_inserts_a_newline_and_the_composer_grows(composer, app) -> None:
    _conversation(app)
    app.tap("Composer")
    app.composer.inject_text("line one")

    _x, _y, _w, single_h = _box(_find(app.document.node(app.current_frame_id), "Composer"))
    app.composer.inject_text("line one\nline two")
    app.loop(app.test_ctx, 0.016)

    native = _find(app.document.node(app.current_frame_id), "Composer")
    assert _box(native)[3] == pytest.approx(single_h + composer.LINE_HEIGHT)
    caret = _find(native, "Composer Caret")
    text = _find(native, "Composer Text")
    assert caret["absoluteBoundingBox"]["y"] >= text["absoluteBoundingBox"]["y"] + composer.LINE_HEIGHT


def test_growth_caps_at_five_lines_and_the_caret_stays_visible(composer, app) -> None:
    _conversation(app)
    app.tap("Composer")

    app.composer.inject_text("\n".join(f"line {i}" for i in range(8)))
    app.loop(app.test_ctx, 0.016)

    native = _find(app.document.node(app.current_frame_id), "Composer")
    assert _box(native)[3] == pytest.approx(composer.MAX_HEIGHT)
    caret = _find(native, "Composer Caret")
    _x, cy, _w, ch = _box(native)
    caret_box = caret["absoluteBoundingBox"]
    # The caret line is scrolled into the visible region of the clipped composer.
    assert cy < caret_box["y"] < cy + ch


# ── keyboard avoidance ────────────────────────────────────────────────────────


def test_keyboard_pushes_the_composer_and_tab_capsule_up(composer, asm, app) -> None:
    _conversation(app)
    app.tap("Composer")

    enqueue_native_text_input_events([{"type": "keyboard", "height": 346.0, "duration": 0.0}])
    app.loop(app.test_ctx, 0.016)

    convo = app.document.node(app.current_frame_id)
    native = _find(convo, "Composer")
    bar = _find(convo, "Tab Bar")
    _x, cy, _w, ch = _box(native)
    assert cy + ch == pytest.approx(asm.TAB_BAR_Y - asm.COMPOSER_BAR_GAP_PT - 346.0)
    assert _box(bar)[1] == pytest.approx(asm.TAB_BAR_Y - 346.0)
    # The scroll range grows with the keyboard so the conversation can still
    # scroll its last message above the raised composer.
    assert convo["absoluteBoundingBox"]["height"] >= 1032.0 + 346.0


def test_keyboard_animates_with_the_forwarded_duration(composer, app) -> None:
    _conversation(app)
    app.tap("Composer")

    app.composer.apply_keyboard(300.0, duration=0.3)
    app.loop(app.test_ctx, 0.1)
    mid = app.composer.keyboard_offset
    assert 0.0 < mid < 300.0
    for _ in range(5):
        app.loop(app.test_ctx, 0.1)
    assert app.composer.keyboard_offset == pytest.approx(300.0)


def test_keyboard_hide_settles_the_chrome_back(composer, asm, app) -> None:
    _conversation(app)
    app.tap("Composer")
    app.composer.apply_keyboard(346.0, duration=0.0)
    app.loop(app.test_ctx, 0.016)

    app.composer.apply_keyboard(0.0, duration=0.0)
    app.loop(app.test_ctx, 0.016)

    convo = app.document.node(app.current_frame_id)
    assert _box(_find(convo, "Tab Bar"))[1] == pytest.approx(asm.TAB_BAR_Y)
    assert convo["absoluteBoundingBox"]["height"] == pytest.approx(1032.0)


def test_tapping_outside_the_composer_resigns_the_keyboard(app) -> None:
    _conversation(app)
    app.tap("Composer")
    assert app.composer.focused is True

    # A tap on empty conversation content (no hotspot) dismisses the keyboard.
    app.test_ctx.queue(_touch("down", 201, 500), _touch("up", 201, 500))
    app.loop(app.test_ctx, 0.016)

    assert app.composer.focused is False
    assert app.test_bridge.focused is False
    native = _find(app.document.node(app.current_frame_id), "Composer")
    assert _find(native, "Composer Caret").get("visible", True) is False


def test_user_dismissed_keyboard_ends_the_focus(app) -> None:
    _conversation(app)
    app.tap("Composer")

    enqueue_native_text_input_events(
        [{"type": "keyboard", "height": 0.0, "duration": 0.25}, {"type": "editing_end"}]
    )
    app.loop(app.test_ctx, 0.016)

    assert app.composer.focused is False
    native = _find(app.document.node(app.current_frame_id), "Composer")
    assert _find(native, "Composer Caret").get("visible", True) is False


# ── send flow ─────────────────────────────────────────────────────────────────


def _replies(screen: dict) -> dict:
    return _find(screen, "Conversation Replies")


def test_send_appends_a_user_bubble_and_a_quiet_stub(composer, app) -> None:
    _conversation(app)
    app.tap("Composer")
    app.composer.inject_text("What changed in rev C?")

    assert app.composer.send() is True
    app.loop(app.test_ctx, 0.016)

    convo = app.document.node(app.current_frame_id)
    replies = _replies(convo)
    bubbles = [n for n in _walk(replies) if n.get("name") == "User Bubble"]
    assert len(bubbles) == 1
    bubble = bubbles[0]
    text = next(n for n in _walk(bubble) if n.get("type") == "TEXT")
    assert text["characters"] == "What changed in rev C?"
    assert text["style"]["fontSize"] == 17.0
    # Right-aligned, comfortable max width.
    bx, _by, bw, _bh = _box(bubble)
    assert bx + bw == pytest.approx(402.0 - 16.0)
    assert bw <= 0.78 * 402.0 + 1.0
    stub = _find(replies, "Stub Reply")
    assert stub["characters"] == composer.STUB_TEXT
    assert _rgb(stub["fills"][0]) == (145, 148, 146)  # gray-400, no bubble fill
    assert stub.get("type") == "TEXT"


def test_send_clears_the_composer_and_the_native_field(app) -> None:
    _conversation(app)
    app.tap("Composer")
    app.composer.inject_text("hello")

    app.composer.send()
    app.loop(app.test_ctx, 0.016)

    assert app.composer.text == ""
    assert app.test_bridge.text == ""
    assert app.composer.send_enabled is False
    native = _find(app.document.node(app.current_frame_id), "Composer")
    assert _find(native, "Composer Placeholder")["visible"] is not False


def test_send_scrolls_the_conversation_to_the_bottom(composer, app) -> None:
    _conversation(app)
    app.tap("Composer")
    app.composer.inject_text("one")

    app.composer.send()
    app.loop(app.test_ctx, 0.016)

    screen = app._screen(app.current_frame_id)
    assert app.scroll_y == pytest.approx(screen.max_scroll)
    assert app.scroll_y > 0.0


def test_send_via_the_send_button_tap(app) -> None:
    _conversation(app)
    app.tap("Composer")
    app.composer.inject_text("via button")
    app.loop(app.test_ctx, 0.016)

    app.tap("Composer Send")
    app.loop(app.test_ctx, 0.016)

    convo = app.document.node(app.current_frame_id)
    assert any(n.get("name") == "User Bubble" for n in _walk(_replies(convo)))


def test_whitespace_only_text_cannot_be_sent(composer, app) -> None:
    _conversation(app)
    app.tap("Composer")
    app.composer.inject_text("   \n  ")

    assert app.composer.send_enabled is False
    assert app.composer.send() is False
    app.loop(app.test_ctx, 0.016)

    convo = app.document.node(app.current_frame_id)
    assert not any(n.get("name") == "User Bubble" for n in _walk(_replies(convo)))


def test_send_from_the_assistant_screen_lands_in_the_conversation(app) -> None:
    assert app.current_frame_name == "Assistant"
    app.tap("Composer")
    app.composer.inject_text("from the hero")

    app.composer.send()
    app.loop(app.test_ctx, 0.016)

    assert app.current_frame_name == "Conversation"
    convo = app.document.node(app.current_frame_id)
    bubbles = [n for n in _walk(_replies(convo)) if n.get("name") == "User Bubble"]
    assert len(bubbles) == 1
    text = next(n for n in _walk(bubbles[0]) if n.get("type") == "TEXT")
    assert text["characters"] == "from the hero"


# ── appearance ────────────────────────────────────────────────────────────────


def test_dark_composer_uses_the_dark_palette(composer, app) -> None:
    app.set_appearance("dark")
    app.loop(app.test_ctx, 0.016)
    _conversation(app)

    native = _find(app.document.node(app.current_frame_id), "Composer")
    surface = _rgb(native["fills"][0])
    assert max(surface) < 80, "dark composer surface is a raised dark gray"
    theme = composer.composer_theme("dark")
    assert theme.accent == (122, 167, 151)  # teal-400
    value = _find(native, "Composer Text")
    assert min(_rgb(value["fills"][0])) >= 200, "dark composer text stays light"


def test_composer_state_survives_an_appearance_swap(composer, app) -> None:
    _conversation(app)
    app.tap("Composer")
    app.composer.inject_text("still drafting")

    app.set_appearance("dark")
    app.loop(app.test_ctx, 0.016)

    assert app.current_frame_name == "Conversation"
    native = _find(app.document.node(app.current_frame_id), "Composer")
    assert _find(native, "Composer Text")["characters"] == "still drafting"
    assert app.composer.focused is True
