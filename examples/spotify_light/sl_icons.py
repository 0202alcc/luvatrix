"""Phosphor icon glyphs for the dock and card chrome.

The TTFs are bundled in ``assets/fonts/`` (MIT, see ``Phosphor-LICENSE.txt``),
and the runtime font resolver searches that directory on every host, so the
macOS Metal text path and the headless CI rasterizer draw identical icon
pixels. Two families are used, per Alec's pick:

- ``Phosphor`` (regular weight): nav, search, overflow, idle note.
- ``Phosphor-Fill`` (solid): transport play/prev/next.

Both weights encode the same codepoints in the private use area, so the char
below is identical across families and only the family selects the weight.
"""
from __future__ import annotations

ICON_FONT = "Phosphor"
ICON_FONT_FILL = "Phosphor-Fill"

HOME = "\ue2c2"     # house
SEARCH = "\ue30c"   # magnifying-glass
MORE = "\ue1fe"     # dots-three
PREV = "\ue5a4"     # skip-back
NEXT = "\ue5a6"     # skip-forward
PLAY = "\ue3d0"     # play
NOTE = "\ue33c"     # music-note

# name -> (char, family)
GLYPHS = {
    "home": (HOME, ICON_FONT),
    "search": (SEARCH, ICON_FONT),
    "more": (MORE, ICON_FONT),
    "note": (NOTE, ICON_FONT),
    "prev": (PREV, ICON_FONT_FILL),
    "next": (NEXT, ICON_FONT_FILL),
    "play": (PLAY, ICON_FONT_FILL),
}
