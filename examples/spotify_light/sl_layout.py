"""Live layout overrides for the MCP surface (round 31, Alec).

The layout-tool loop: nudge chrome positions on the RUNNING app over MCP
(layout_set / layout_list / layout_clear), then layout_export the overrides
as JSON for baking into the layout constants. Addressable components are the
chrome — the playback pill, the nav circles (home/search/more), and the
sidebar rail.

An override is either an explicit rect or an anchor + offsets (the anchor
re-resolves against the window size every frame, so a "top-right, 16pt
margin" override behaves exactly like the pill's own layout rule). Overrides
are consulted at draw time, so they win over the app's per-frame layout
recomputation: state changes cannot stomp them. They are session-scoped —
the registry is created in setup(), so a reboot starts clean with no
persistence file.

Interior ids (pill.art / pill.progress / pill.transport, round 33) work the
same way in PILL-LOCAL space: naturals and specs are local to the pill's
top-left, resolution and clamping run against the pill's current rect, and
the draw offsets the result by the pill position — so interior overrides
compose with (and survive) whole-pill overrides.

Validation happens at set() time only: resolve() never raises, so a bad
value can never crash the scene. LayoutError surfaces through mcp_call as a
tool error naming the offender and the valid ids.
"""
from __future__ import annotations

import math

# Interior ids (round 33) address the pill's inside in PILL-LOCAL space:
# (0, 0) is the pill's top-left, specs clamp into the pill's current rect
# (never the window), and locals compose with whole-pill moves.
INTERIOR_IDS = ("pill.art", "pill.progress", "pill.transport")
COMPONENT_IDS = ("pill", "nav_home", "nav_search", "nav_more", "sidebar") + INTERIOR_IDS
ANCHORS = ("top-left", "top-right", "bottom-left", "bottom-right", "center")

Rect = tuple[float, float, float, float]


class LayoutError(ValueError):
    """Unknown component id or malformed spec; surfaced as an MCP tool error."""


def _check_id(component_id: object) -> str:
    if not isinstance(component_id, str) or component_id not in COMPONENT_IDS:
        raise LayoutError(
            f"unknown layout id {component_id!r}; valid ids: {', '.join(COMPONENT_IDS)}")
    return component_id


def _num(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LayoutError(f"{field} must be a number, got {value!r}")
    result = float(value)
    if not math.isfinite(result):
        raise LayoutError(f"{field} must be finite, got {value!r}")
    return result


def _size(value: object, *, field: str) -> float:
    result = _num(value, field=field)
    if result < 1.0:
        raise LayoutError(f"{field} must be at least 1pt, got {value!r}")
    return result


class LayoutOverrides:
    """Session-scoped registry of validated layout specs, keyed by component id."""

    def __init__(self) -> None:
        self._specs: dict[str, dict] = {}

    def __len__(self) -> int:
        return len(self._specs)

    def set(self, component_id: object, spec: object) -> dict:
        """Validate and store a spec; returns the stored copy. Never partially stores."""
        cid = _check_id(component_id)
        if not isinstance(spec, dict):
            raise LayoutError(f"spec for {cid} must be an object, got {spec!r}")
        has_rect = "rect" in spec
        has_anchor = "anchor" in spec
        if has_rect == has_anchor:
            raise LayoutError(
                f"spec for {cid} needs exactly one of 'rect' or 'anchor', got {sorted(spec)}")
        if has_rect:
            raw = spec["rect"]
            if not isinstance(raw, dict):
                raise LayoutError(f"rect for {cid} must be an object, got {raw!r}")
            missing = {"x", "y", "width", "height"} - set(raw)
            if missing:
                raise LayoutError(f"rect for {cid} is missing keys: {sorted(missing)}")
            stored = {
                "rect": {
                    "x": _num(raw["x"], field="rect.x"),
                    "y": _num(raw["y"], field="rect.y"),
                    "width": _size(raw["width"], field="rect.width"),
                    "height": _size(raw["height"], field="rect.height"),
                }
            }
        else:
            anchor = spec["anchor"]
            if anchor not in ANCHORS:
                raise LayoutError(
                    f"unknown anchor {anchor!r}; valid anchors: {', '.join(ANCHORS)}")
            stored = {
                "anchor": anchor,
                "dx": _num(spec.get("dx", 0.0), field="dx"),
                "dy": _num(spec.get("dy", 0.0), field="dy"),
            }
            if "width" in spec:
                stored["width"] = _size(spec["width"], field="width")
            if "height" in spec:
                stored["height"] = _size(spec["height"], field="height")
        self._specs[cid] = stored
        return dict(stored)

    def clear(self, component_id: object = None) -> list[str]:
        """Clear one id or (None) all; returns the cleared ids."""
        if component_id is None:
            cleared = sorted(self._specs)
            self._specs.clear()
            return cleared
        cid = _check_id(component_id)
        return [cid] if self._specs.pop(cid, None) is not None else []

    def specs(self) -> dict[str, dict]:
        return {cid: dict(spec) for cid, spec in self._specs.items()}

    def resolve(self, component_id: str, natural: Rect, *, width: float, height: float) -> Rect:
        """Apply the override (if any) to the natural rect, clamped into the
        window. Never raises: specs were validated at set() time."""
        spec = self._specs.get(component_id)
        if spec is None:
            return natural
        nx, ny, nw, nh = natural
        if "rect" in spec:
            rect = spec["rect"]
            x, y, w, h = rect["x"], rect["y"], rect["width"], rect["height"]
        else:
            w = spec.get("width", nw)
            h = spec.get("height", nh)
            dx, dy = spec["dx"], spec["dy"]
            anchor = spec["anchor"]
            if anchor == "top-left":
                x, y = dx, dy
            elif anchor == "top-right":
                x, y = width - dx - w, dy
            elif anchor == "bottom-left":
                x, y = dx, height - dy - h
            elif anchor == "bottom-right":
                x, y = width - dx - w, height - dy - h
            else:  # center
                x, y = width / 2.0 - w / 2.0 + dx, height / 2.0 - h / 2.0 + dy
        w = min(w, width)
        h = min(h, height)
        x = min(max(x, 0.0), width - w)
        y = min(max(y, 0.0), height - h)
        return (x, y, w, h)

    def export(self, *, width: float, height: float,
               naturals: dict[str, Rect] | None = None,
               local_frames: dict[str, tuple[float, float]] | None = None) -> dict:
        """JSON-serializable dump for the bake path: the specs to re-apply,
        plus the resolved rects at the current window size for transcribing
        into layout constants. Ids in local_frames resolve against that
        frame's (width, height) instead of the window's — interior ids
        export in pill-local coordinates this way."""
        naturals = naturals or {}
        local_frames = local_frames or {}
        return {
            "version": 1,
            "window": {"width": float(width), "height": float(height)},
            "overrides": self.specs(),
            "resolved": {
                cid: [round(v, 2) for v in self.resolve(
                    cid, naturals.get(cid, (0.0, 0.0, 0.0, 0.0)),
                    width=local_frames.get(cid, (width, height))[0],
                    height=local_frames.get(cid, (width, height))[1])]
                for cid in sorted(self._specs)
            },
        }
