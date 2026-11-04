"""UITraitCollection.userInterfaceStyle bridge for the iOS scaffold.

setup_ui records the window's initial trait and the native scaffold forwards
later traitCollectionDidChange callbacks through set_user_interface_style.
Appearance-aware apps (e.g. FigmaApp) read LUVATRIX_IOS_USER_INTERFACE_STYLE;
LUVATRIX_APPEARANCE remains the explicit override that beats this bridge.
"""

from __future__ import annotations

import os
import threading

# UIUserInterfaceStyle raw values: unspecified is deliberately absent — a
# transient trait collection must never flash the wrong theme.
_UIKIT_STYLES = {1: "light", 2: "dark"}

_lock = threading.Lock()
_style = "light"


def set_user_interface_style(style: object) -> bool:
    """Record the host UIUserInterfaceStyle; False for unknown/unspecified values."""
    global _style
    name = _normalize(style)
    if name is None:
        return False
    with _lock:
        _style = name
    os.environ["LUVATRIX_IOS_USER_INTERFACE_STYLE"] = name
    return True


def user_interface_style() -> str:
    """The last reported host style: "light" or "dark" (light until reported)."""
    with _lock:
        return _style


def _normalize(style: object) -> str | None:
    if isinstance(style, str):
        name = style.strip().lower()
        return name if name in _UIKIT_STYLES.values() else None
    if isinstance(style, bool):
        return None
    try:
        raw = int(style)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return _UIKIT_STYLES.get(raw)
