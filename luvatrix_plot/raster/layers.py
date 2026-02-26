from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class LayerCache:
    frame_key: tuple[Any, ...] | None = None
    frame_template: np.ndarray | None = None
    grid_key: tuple[Any, ...] | None = None
    grid_template: np.ndarray | None = None
    text_key: tuple[Any, ...] | None = None
    text_template: np.ndarray | None = None

    def invalidate(self) -> None:
        self.frame_key = None
        self.frame_template = None
        self.grid_key = None
        self.grid_template = None
        self.text_key = None
        self.text_template = None


@dataclass
class DirtyState:
    dirty: bool = True
    rect: tuple[int, int, int, int] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
