"""The iOS native text-input bridge: a hidden UITextView owns the keyboard.

The Swift side (`Luvatrix/TextInputBridge.swift`) keeps an offscreen UITextView
that becomes first responder when the composer is tapped, forwards text,
selection, editing-end, and keyboard-frame notifications into Python, and takes
programmatic text/placeholder/focus updates from Python. The Python side
(`luvatrix_core.platform.ios.text_input`) resolves that ObjC class through
rubicon-objc on first use; Linux tests substitute a fake Swift object via
``IOSTextInput(bridge=...)``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from luvatrix_core.platform.ios import text_input
from luvatrix_core.platform.ios.text_input import (
    IOSTextInput,
    IOSTextInputError,
    enqueue_native_text_input_events,
    poll_text_input_events,
    reset_text_input_events,
)

ROOT = Path(__file__).resolve().parents[1]
NATIVE_IOS_DIRS = (
    ROOT / "ios",
    ROOT / "luvatrix_core" / "templates" / "native" / "ios",
    ROOT / "examples" / "nomic_ios" / "ios",
)


class FakeSwiftTextInput:
    """Fake for the ObjC `LuvatrixTextInput` boundary on the Swift side.

    Method names mirror the ObjC selectors (`focusComposer`, `resignComposer`,
    `setComposerText:`, `setComposerPlaceholder:`, `isComposerFocused`) exactly
    as rubicon-objc surfaces them to Python.
    """

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


@pytest.fixture(autouse=True)
def _clean_event_queue():
    reset_text_input_events()
    yield
    reset_text_input_events()


# ── event queue ──────────────────────────────────────────────────────────────


def test_text_events_round_trip_in_order() -> None:
    accepted = enqueue_native_text_input_events(
        [
            {"type": "text", "text": "H", "selection": 1},
            {"type": "text", "text": "Hi", "selection": 2},
        ]
    )

    assert accepted == 2
    assert poll_text_input_events() == [
        {"type": "text", "text": "H", "selection": 1},
        {"type": "text", "text": "Hi", "selection": 2},
    ]
    assert poll_text_input_events() == []


def test_text_event_defaults_selection_to_the_end_and_coerces_types() -> None:
    accepted = enqueue_native_text_input_events([{"type": "text", "text": "hello"}])

    assert accepted == 1
    (event,) = poll_text_input_events()
    assert event == {"type": "text", "text": "hello", "selection": 5}


def test_text_event_selection_is_clamped_into_the_text() -> None:
    enqueue_native_text_input_events(
        [
            {"type": "text", "text": "hi", "selection": 99},
            {"type": "text", "text": "hi", "selection": -3},
        ]
    )

    events = poll_text_input_events()
    assert [event["selection"] for event in events] == [2, 0]


def test_keyboard_events_carry_height_and_animation_duration() -> None:
    accepted = enqueue_native_text_input_events(
        [
            {"type": "keyboard", "height": 346.0, "duration": 0.25},
            {"type": "keyboard", "height": 0.0, "duration": 0.25},
        ]
    )

    assert accepted == 2
    events = poll_text_input_events()
    assert events[0] == {"type": "keyboard", "height": 346.0, "duration": 0.25}
    assert events[1]["height"] == 0.0


def test_editing_end_events_are_forwarded() -> None:
    assert enqueue_native_text_input_events([{"type": "editing_end"}]) == 1
    assert poll_text_input_events() == [{"type": "editing_end"}]


def test_malformed_events_are_skipped_not_queued() -> None:
    accepted = enqueue_native_text_input_events(
        [
            None,
            "text",
            {},
            {"type": "mystery"},
            {"type": "text"},  # text payload missing
            {"type": "keyboard", "height": "tall"},
            {"type": "text", "text": "ok"},
        ]
    )

    assert accepted == 1
    assert poll_text_input_events() == [{"type": "text", "text": "ok", "selection": 2}]


def test_negative_keyboard_metrics_are_clamped_to_zero() -> None:
    enqueue_native_text_input_events([{"type": "keyboard", "height": -4, "duration": -1}])

    (event,) = poll_text_input_events()
    assert event["height"] == 0.0
    assert event["duration"] == 0.0


# ── IOSTextInput over the Swift boundary ─────────────────────────────────────


def test_focus_and_resign_forward_to_the_swift_side() -> None:
    bridge = FakeSwiftTextInput()
    field = IOSTextInput(bridge=bridge)

    assert field.focus() is True
    assert field.is_focused() is True
    assert field.resign() is True
    assert field.is_focused() is False
    assert bridge.calls == [("focus",), ("resign",)]


def test_repeated_focus_requests_are_safe() -> None:
    # A user may tap the composer twice before the keyboard animation finishes;
    # the second request must not error or confuse the native side.
    bridge = FakeSwiftTextInput()
    field = IOSTextInput(bridge=bridge)

    assert field.focus() is True
    assert field.focus() is True
    assert field.is_focused() is True


def test_set_text_and_placeholder_forward_to_the_swift_side() -> None:
    bridge = FakeSwiftTextInput()
    field = IOSTextInput(bridge=bridge)

    assert field.set_text("draft") is True
    assert field.set_placeholder("Ask anything") is True
    assert bridge.text == "draft"
    assert bridge.placeholder == "Ask anything"
    assert bridge.calls == [("set_text", "draft"), ("set_placeholder", "Ask anything")]


def test_unavailable_bridge_degrades_gracefully() -> None:
    def resolver() -> object:
        raise ImportError("No module named 'rubicon'")

    field = IOSTextInput(resolver=resolver)

    assert field.available() is False
    assert field.focus() is False
    assert field.resign() is False
    assert field.set_text("hi") is False
    assert field.set_placeholder("hi") is False
    assert field.is_focused() is False


def test_native_bridge_errors_are_actionable() -> None:
    class BrokenBridge(FakeSwiftTextInput):
        def focusComposer(self) -> bool:
            raise RuntimeError("no key window")

    field = IOSTextInput(bridge=BrokenBridge())
    with pytest.raises(IOSTextInputError, match="text input"):
        field.focus()


def test_module_level_helpers_use_the_default_input() -> None:
    bridge = FakeSwiftTextInput()
    previous = text_input.default_text_input()
    text_input.set_default_text_input(IOSTextInput(bridge=bridge))
    try:
        assert text_input.focus() is True
        text_input.set_text("queued")
        assert bridge.focused is True
        assert bridge.text == "queued"
        text_input.resign()
        assert bridge.focused is False
    finally:
        text_input.set_default_text_input(previous)


# ── native scaffold ──────────────────────────────────────────────────────────


def test_swift_scaffold_ships_the_text_input_bridge() -> None:
    for native in NATIVE_IOS_DIRS:
        swift_path = native / "Luvatrix" / "TextInputBridge.swift"
        assert swift_path.exists(), swift_path
        swift = swift_path.read_text(encoding="utf-8")
        # rubicon-objc resolves this exported class name from Python.
        assert "@objc(LuvatrixTextInput)" in swift, native
        # Multiline input with a real first responder + software keyboard.
        assert "UITextView" in swift, native
        assert "becomeFirstResponder" in swift, native
        # Keyboard avoidance: frame + animation duration flow into Python.
        assert "UIKeyboardWillChangeFrameNotification" in swift, native
        assert "UIKeyboardAnimationDurationUserInfoKey" in swift, native
        # Swift -> Python entry point (LuvatrixPyRunSimpleString script).
        assert "enqueue_native_text_input_events" in swift, native
        assert "luvatrix_core.platform.ios.text_input" in swift, native
        # Python -> Swift selectors the Python bridge calls.
        for selector in ("focusComposer", "resignComposer", "setComposerText", "setComposerPlaceholder"):
            assert selector in swift, (native, selector)
