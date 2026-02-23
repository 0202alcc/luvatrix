from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Element:
    element_id: str
    svg_path: Path
    x: float
    y: float
    scale: float
    opacity: float
    animation: Optional[dict[str, float | str]] = None
