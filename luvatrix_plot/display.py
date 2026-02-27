from __future__ import annotations

import math


DEFAULT_ASPECT_RATIO = 16.0 / 9.0
DEFAULT_DISPLAY_FRACTION = 0.82
DEFAULT_MIN_WIDTH = 960
DEFAULT_MIN_HEIGHT = 540
DEFAULT_FALLBACK_SIZE = (1280, 720)


def resolve_default_figure_size(
    *,
    aspect_ratio: float = DEFAULT_ASPECT_RATIO,
    display_fraction: float = DEFAULT_DISPLAY_FRACTION,
    min_width: int = DEFAULT_MIN_WIDTH,
    min_height: int = DEFAULT_MIN_HEIGHT,
) -> tuple[int, int]:
    if aspect_ratio <= 0:
        raise ValueError("aspect_ratio must be > 0")
    if display_fraction <= 0:
        raise ValueError("display_fraction must be > 0")
    if min_width <= 0 or min_height <= 0:
        raise ValueError("min_width/min_height must be > 0")

    screen = _detect_screen_size()
    if screen is None:
        return _fit_aspect(DEFAULT_FALLBACK_SIZE[0], DEFAULT_FALLBACK_SIZE[1], aspect_ratio, min_width, min_height)

    sw, sh = screen
    target_w = max(1, int(sw * display_fraction))
    target_h = max(1, int(sh * display_fraction))
    return _fit_aspect(target_w, target_h, aspect_ratio, min_width, min_height)


def _fit_aspect(max_w: int, max_h: int, aspect_ratio: float, min_width: int, min_height: int) -> tuple[int, int]:
    w = max_w
    h = int(round(w / aspect_ratio))
    if h > max_h:
        h = max_h
        w = int(round(h * aspect_ratio))

    w = max(w, min_width)
    h = max(h, min_height)

    # Keep integer outputs consistent and >= 1.
    return (max(1, int(math.floor(w))), max(1, int(math.floor(h))))


def _detect_screen_size() -> tuple[int, int] | None:
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        width = int(root.winfo_screenwidth())
        height = int(root.winfo_screenheight())
        root.destroy()
        if width > 0 and height > 0:
            return (width, height)
    except Exception:
        return None
    return None
