"""Live layout overrides for the MCP surface (round 31, Alec).

The layout-tool loop: nudge chrome positions on the RUNNING app over MCP
(layout_set / layout_list / layout_clear), then layout_export the overrides
as JSON for inspection. Addressable components are the chrome — the
playback pill, the nav circles (home/search/more), and the sidebar rail.

An override is either an explicit rect or an anchor + offsets (the anchor
re-resolves against the window size every frame, so a "top-right, 16pt
margin" override behaves exactly like the pill's own layout rule). Overrides
are consulted at draw time, so they win over the app's per-frame layout
recomputation: state changes cannot stomp them.

Persistence (round 36, SL-20): overrides are the app's source of truth for
chrome layout, not session scratch. setup() seeds the registry from
APP_LAYOUT_FILE (TOML — a declarative data file, never patched Python);
layout_set/layout_clear write the registry back through to the same file,
so a nudge survives restart and shows up as an ordinary git diff. Specs
persist in their resize-safe form (anchor + inward dx/dy); a raw rect is
only the degenerate fallback. SPOTIFY_LIGHT_LAYOUT_FILE redirects the path
(tests point it at a tmp copy).

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
import os
import tomllib
from pathlib import Path

# Interior ids (round 33) address the pill's inside in PILL-LOCAL space:
# (0, 0) is the pill's top-left, specs clamp into the pill's current rect
# (never the window), and locals compose with whole-pill moves.
INTERIOR_IDS = ("pill.art", "pill.progress", "pill.transport")
COMPONENT_IDS = ("pill", "nav_home", "nav_search", "nav_more", "sidebar") + INTERIOR_IDS
ANCHORS = ("top-left", "top-right", "bottom-left", "bottom-right", "center")

APP_LAYOUT_FILE = Path(__file__).resolve().parent / "layout.toml"

_FILE_HEADER = """\
# layout.toml — persisted layout overrides for the spotify_light chrome.
# Written by the MCP layout tools (layout_set / layout_clear); read at
# startup. Specs stay resize-safe: anchor + inward dx/dy offsets re-resolve
# against the window size every frame. A raw rect table persists only as
# the degenerate fallback. Hand edits are fine — malformed entries are
# ignored, never fatal.
"""

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
        """JSON-serializable dump for inspection: the specs to re-apply,
        plus the resolved rects at the current window size. Ids in
        local_frames resolve against that frame's (width, height) instead
        of the window's — interior ids export in pill-local coordinates
        this way."""
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


# -- persistence (round 36) ---------------------------------------------------

def default_path() -> Path:
    """Where overrides persist: SPOTIFY_LIGHT_LAYOUT_FILE when set (tests),
    else the app's own layout.toml — the file setup() reads and the MCP
    tools rewrite."""
    override = os.environ.get("SPOTIFY_LIGHT_LAYOUT_FILE")
    return Path(override) if override else APP_LAYOUT_FILE


def load(path: Path) -> LayoutOverrides:
    """Seed a registry from the persisted file. Fail-soft by contract: a
    missing file means no overrides, and malformed TOML or invalid entries
    are skipped — a corrupt hand edit must never keep the app from booting."""
    registry = LayoutOverrides()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return registry
    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError:
        return registry
    for cid, spec in data.items():
        try:
            registry.set(cid, spec)
        except LayoutError:
            continue
    return registry


def _toml_num(value: float) -> str:
    return repr(float(value))


def save(specs: dict[str, dict], path: Path) -> None:
    """Rewrite the persisted file with the registry's specs. Deterministic
    (sorted ids, fixed formatting) so the git diff shows only the nudge.
    Written via a sibling temp file + replace so a crash mid-write can't
    tear the file."""
    chunks = [_FILE_HEADER]
    for cid in sorted(specs):
        spec = specs[cid]
        if "rect" in spec:
            rect = spec["rect"]
            body = "\n".join(
                f"{key} = {_toml_num(rect[key])}"
                for key in ("x", "y", "width", "height"))
            chunks.append(f"[{cid}.rect]\n{body}\n")
        else:
            lines = [f'anchor = "{spec["anchor"]}"',
                     f"dx = {_toml_num(spec['dx'])}",
                     f"dy = {_toml_num(spec['dy'])}"]
            if "width" in spec:
                lines.append(f"width = {_toml_num(spec['width'])}")
            if "height" in spec:
                lines.append(f"height = {_toml_num(spec['height'])}")
            chunks.append(f"[{cid}]\n" + "\n".join(lines) + "\n")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(chunks), encoding="utf-8")
    os.replace(tmp, path)
