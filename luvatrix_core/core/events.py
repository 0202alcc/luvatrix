from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


EventType = Literal[
    "pointer_move",
    "pointer_down",
    "pointer_up",
    "wheel",
    "key_down",
    "key_up",
]


@dataclass(frozen=True)
class InputEvent:
    event_type: EventType
    timestamp: float
    x: Optional[float] = None
    y: Optional[float] = None
    button: Optional[int] = None
    delta_x: Optional[float] = None
    delta_y: Optional[float] = None
    key: Optional[str] = None
    code: Optional[str] = None
    modifiers: Optional[dict[str, bool]] = None
