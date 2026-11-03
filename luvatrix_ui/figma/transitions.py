from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

_FADES = frozenset({"DISSOLVE", "SMART_ANIMATE", "SCROLL_ANIMATE"})
_SLIDES = frozenset({"PUSH", "MOVE_IN", "MOVE_OUT", "SLIDE_IN", "SLIDE_OUT"})
_OPPOSITE = {"LEFT": "RIGHT", "RIGHT": "LEFT", "TOP": "BOTTOM", "BOTTOM": "TOP"}
_REVERSED_KIND = {"MOVE_IN": "MOVE_OUT", "MOVE_OUT": "MOVE_IN", "SLIDE_IN": "SLIDE_OUT", "SLIDE_OUT": "SLIDE_IN"}


def ease(name: str, t: float) -> float:
    t = min(1.0, max(0.0, t))
    if name == "LINEAR":
        return t
    if name in {"EASE_IN", "EASE_IN_BACK"}:
        return t * t * t
    if name in {"EASE_IN_AND_OUT", "EASE_IN_AND_OUT_BACK", "CUSTOM_CUBIC_BEZIER"}:
        return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2
    return 1 - (1 - t) ** 3


@dataclass
class Transition:
    kind: str
    direction: str
    duration: float
    easing: str
    source: np.ndarray
    target: np.ndarray
    elapsed: float = 0.0

    @classmethod
    def from_figma(cls, spec: dict[str, Any] | None, source: np.ndarray, target: np.ndarray, *, reverse: bool = False) -> "Transition | None":
        if not spec:
            return None
        kind = str(spec.get("type", "INSTANT"))
        duration = float(spec.get("duration", 0.0) or 0.0)
        if duration <= 0 or (kind not in _FADES and kind not in _SLIDES):
            return None
        direction = str(spec.get("direction", "LEFT"))
        if reverse:
            direction = _OPPOSITE.get(direction, direction)
            kind = _REVERSED_KIND.get(kind, kind)
        easing = str((spec.get("easing") or {}).get("type", "EASE_OUT"))
        return cls(kind, direction, duration, easing, source, target)

    @property
    def done(self) -> bool:
        return self.elapsed >= self.duration

    def advance(self, dt: float) -> None:
        self.elapsed = min(self.duration, self.elapsed + max(0.0, float(dt)))

    def frame(self) -> np.ndarray:
        p = ease(self.easing, self.elapsed / self.duration)
        if self.kind in _FADES:
            mixed = self.source.astype(np.float32) * (1 - p) + self.target.astype(np.float32) * p
            return np.rint(mixed).astype(np.uint8)
        h, w = self.target.shape[:2]
        horizontal = self.direction in {"LEFT", "RIGHT"}
        extent = w if horizontal else h
        sign = -1 if self.direction in {"LEFT", "TOP"} else 1
        travel = int(round(extent * p))
        incoming = -sign * (extent - travel)
        out = self.source.copy()
        if self.kind in {"MOVE_OUT", "SLIDE_OUT"}:
            out[...] = self.target
            _paste_shifted(out, self.source, sign * travel, horizontal)
            return out
        if self.kind == "PUSH":
            out[...] = 0
            out[..., 3] = 255
            _paste_shifted(out, self.source, sign * travel, horizontal)
        _paste_shifted(out, self.target, incoming, horizontal)
        return out


def _paste_shifted(dst: np.ndarray, src: np.ndarray, offset: int, horizontal: bool) -> None:
    n = src.shape[1] if horizontal else src.shape[0]
    lo, hi = max(0, offset), min(n, n + offset)
    if hi <= lo:
        return
    if horizontal:
        dst[:, lo:hi] = src[:, lo - offset : hi - offset]
    else:
        dst[lo:hi] = src[lo - offset : hi - offset]
