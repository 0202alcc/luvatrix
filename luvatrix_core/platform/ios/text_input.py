"""iOS native text-input bridge for the hidden-UITextView pattern.

The Swift side of the native scaffold (`Luvatrix/TextInputBridge.swift`) owns
an offscreen UITextView. When the app asks for focus that view becomes first
responder, so the real iOS keyboard appears and all editing (autocorrect,
predictive text, dictation, hardware keyboards) behaves natively. The delegate
forwards text changes, selection, and editing-end into Python, and
UIKeyboardWillChangeFrameNotification forwards the keyboard frame and
animation duration so the app can lift its composer with the keyboard.

This module resolves the exported ObjC class `LuvatrixTextInput` through
rubicon-objc on first use and exposes focus/resign/set_text/set_placeholder.
Linux tests substitute a fake Swift object via ``IOSTextInput(bridge=...)``.
Every Python-facing call degrades to a no-op (``False``) when the native
bridge is absent — e.g. headless runs — while a present-but-failing bridge
raises `IOSTextInputError` so real defects stay visible.
"""

from __future__ import annotations

from collections import deque
import threading
from typing import Callable

_EVENT_LOCK = threading.Lock()
_EVENTS: deque[dict[str, object]] = deque(maxlen=256)
_KNOWN_TYPES = ("text", "keyboard", "editing_end")


class IOSTextInputError(RuntimeError):
    """The native text-input bridge is present but rejected an operation."""


# ── Swift -> Python event queue ──────────────────────────────────────────────


def enqueue_native_text_input_events(events: object) -> int:
    """Queue events emitted by the Swift delegate; returns how many were kept.

    Malformed entries are skipped (the bridge must never take the app down),
    valid ones are normalized:
    ``{"type": "text", "text": str, "selection": int}`` with the selection
    clamped into the text, ``{"type": "keyboard", "height": float,
    "duration": float}`` with both clamped >= 0, and ``{"type": "editing_end"}``.
    """
    if not isinstance(events, list):
        return 0
    accepted = 0
    for event in events:
        normalized = _normalize_event(event)
        if normalized is None:
            continue
        with _EVENT_LOCK:
            _EVENTS.append(normalized)
        accepted += 1
    return accepted


def poll_text_input_events() -> list[dict[str, object]]:
    """Drain every queued native text-input event, in order."""
    with _EVENT_LOCK:
        out = list(_EVENTS)
        _EVENTS.clear()
    return out


def reset_text_input_events() -> None:
    with _EVENT_LOCK:
        _EVENTS.clear()


def _normalize_event(event: object) -> dict[str, object] | None:
    if not isinstance(event, dict):
        return None
    kind = event.get("type")
    if kind == "text":
        text = event.get("text")
        if not isinstance(text, str):
            return None
        try:
            selection = int(event.get("selection", len(text)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            selection = len(text)
        return {"type": "text", "text": text, "selection": max(0, min(selection, len(text)))}
    if kind == "keyboard":
        try:
            height = float(event.get("height"))  # type: ignore[arg-type]
            duration = float(event.get("duration", 0.0))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return {"type": "keyboard", "height": max(0.0, height), "duration": max(0.0, duration)}
    if kind == "editing_end":
        return {"type": "editing_end"}
    return None


# ── Python -> Swift calls ────────────────────────────────────────────────────


class IOSTextInput:
    """The composer text field over the Swift `LuvatrixTextInput` ObjC class."""

    def __init__(
        self,
        *,
        bridge: object | None = None,
        resolver: Callable[[], object] | None = None,
    ) -> None:
        self._bridge = bridge
        self._resolver = resolver or _resolve_swift_text_input

    def available(self) -> bool:
        """True when the native scaffold's text-input bridge can be reached."""
        try:
            self._bridge_obj()
        except IOSTextInputError:
            return False
        return True

    def focus(self) -> bool:
        """Summon the keyboard; False when running without the native scaffold."""
        bridge = self._try_bridge()
        if bridge is None:
            return False
        try:
            return bool(bridge.focusComposer())
        except Exception as exc:
            raise IOSTextInputError(f"the native iOS text input bridge failed to focus: {exc}") from exc

    def resign(self) -> bool:
        """Dismiss the keyboard; False when running without the native scaffold."""
        bridge = self._try_bridge()
        if bridge is None:
            return False
        try:
            return bool(bridge.resignComposer())
        except Exception as exc:
            raise IOSTextInputError(f"the native iOS text input bridge failed to resign: {exc}") from exc

    def set_text(self, text: str) -> bool:
        """Replace the native field's text (Python stays the source of truth)."""
        bridge = self._try_bridge()
        if bridge is None:
            return False
        try:
            bridge.setComposerText_(str(text))
        except Exception as exc:
            raise IOSTextInputError(f"the native iOS text input bridge failed to set text: {exc}") from exc
        return True

    def set_placeholder(self, text: str) -> bool:
        bridge = self._try_bridge()
        if bridge is None:
            return False
        try:
            bridge.setComposerPlaceholder_(str(text))
        except Exception as exc:
            raise IOSTextInputError(f"the native iOS text input bridge failed to set the placeholder: {exc}") from exc
        return True

    def is_focused(self) -> bool:
        bridge = self._try_bridge()
        if bridge is None:
            return False
        try:
            return bool(bridge.isComposerFocused())
        except Exception:
            return False

    def _try_bridge(self) -> object | None:
        try:
            return self._bridge_obj()
        except IOSTextInputError:
            return None

    def _bridge_obj(self) -> object:
        if self._bridge is None:
            try:
                self._bridge = self._resolver()
            except Exception as exc:
                raise IOSTextInputError(
                    "the native iOS text input bridge is unavailable; run inside the "
                    "Luvatrix iOS scaffold (LuvatrixTextInput) for real keyboard input"
                ) from exc
        return self._bridge


def _resolve_swift_text_input() -> object:
    from rubicon.objc import ObjCClass

    return ObjCClass("LuvatrixTextInput")


_default_lock = threading.Lock()
_default_input = IOSTextInput()


def default_text_input() -> IOSTextInput:
    with _default_lock:
        return _default_input


def set_default_text_input(text_input: IOSTextInput) -> None:
    with _default_lock:
        global _default_input
        _default_input = text_input


def focus() -> bool:
    return default_text_input().focus()


def resign() -> bool:
    return default_text_input().resign()


def set_text(text: str) -> bool:
    return default_text_input().set_text(text)


def set_placeholder(text: str) -> bool:
    return default_text_input().set_placeholder(text)
