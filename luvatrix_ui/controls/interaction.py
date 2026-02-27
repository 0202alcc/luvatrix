from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping


PressPhase = Literal[
    "down",
    "repeat",
    "hold_start",
    "hold_tick",
    "up",
    "hold_end",
    "single",
    "double",
    "cancel",
]


@dataclass(frozen=True)
class HDIPressEvent:
    """Minimal standardized HDI press event contract consumed by controls."""

    phase: PressPhase
    key: str
    active_keys: tuple[str, ...]


def parse_hdi_press_event(event_type: str, payload: object) -> HDIPressEvent | None:
    """Parse normalized HDI `press` events into a typed control interaction event.

    The parser is intentionally decoupled from `luvatrix_core` dataclasses so this
    module can be extracted as first-party UI library code without runtime coupling.
    """

    if event_type != "press" or not isinstance(payload, Mapping):
        return None
    phase = payload.get("phase")
    if phase not in {
        "down",
        "repeat",
        "hold_start",
        "hold_tick",
        "up",
        "hold_end",
        "single",
        "double",
        "cancel",
    }:
        return None
    key = str(payload.get("key", ""))
    raw_active_keys = payload.get("active_keys", ())
    if not isinstance(raw_active_keys, (list, tuple)):
        raw_active_keys = ()
    active_keys = tuple(str(k) for k in raw_active_keys)
    return HDIPressEvent(phase=phase, key=key, active_keys=active_keys)
