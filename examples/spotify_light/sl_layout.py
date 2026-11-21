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

Interior ids (pill.art / pill.progress / pill.title / pill.transport,
rounds 33+37) work the same way in PILL-LOCAL space: naturals and specs are
local to the pill's top-left, resolution and clamping run against the
pill's current rect, and the draw offsets the result by the pill position —
so interior overrides compose with (and survive) whole-pill overrides.

The third spec form (round 37, SL-22) is a RELATIONSHIP: {align: {edge, to,
ref_edge, offset}} pins one edge of a component to an edge of another id's
CURRENT rect (natural or overridden), keeping the opposite edge fixed
(center edges keep the size instead). It persists like the other forms, so
the layout file records "progress aligns to the text column" — resize-safe,
and it tracks the reference if the reference later moves.

The fourth spec form (round 41, SL-27) is CONTAINMENT: {attach: {container,
slot, inset}} moves a window-space component INTO a container at a named
slot (top-right/top-left/bottom-right/bottom-left, inset points in from the
corner). The component switches to container-local space: it rides the
container's current rect (natural or overridden) like the interior ids do,
keeps its size, and clamps inside the container. The attachment persists as
a relationship — never resolved pixels — and slot_reservations() exposes
each slot's occupied rect (container-local) so the container's own layout
can yield the region (the pill's text column narrows left of an attached
top-right button). layout_clear restores the component's window-space
natural; a rect/anchor/align spec replaces the attachment.

Round 38 (SL-23) extends the relationship form in two ways. keep="size" on
an EDGE rule turns it into a position move — the named edge meets the
reference line and the extent holds (the default extent-changing behavior
collapses a component whose natural sits past the reference, e.g. nav_more
at the dock aligning right → pill.left). And an align spec may carry up to
two rules, one per axis — {align: [rule, rule]} persists as an array of
tables — so a component can ride a reference in x and y at once
(nav_more: right → pill.left −12 keep-size AND center_y → pill.center_y).
The layout_align MCP tool upserts one rule per call: same axis replaces,
the other axis adds; a rect/anchor spec is replaced by the align form.

Validation happens at set() time only: rect/anchor specs never raise from
resolve(), so a bad value can never crash the scene (align specs need the
frame's naturals map at resolve() time — every app call path supplies it).
LayoutError surfaces through mcp_call as a tool error naming the offender
and the valid ids.
"""
from __future__ import annotations

import math
import os
import tomllib
from pathlib import Path

# Interior ids (round 33) address the pill's inside in PILL-LOCAL space:
# (0, 0) is the pill's top-left, specs clamp into the pill's current rect
# (never the window), and locals compose with whole-pill moves. pill.title
# (round 37) is the title/artist text column — the reference the progress
# strip aligns to (SL-21/22).
INTERIOR_IDS = ("pill.art", "pill.progress", "pill.title", "pill.transport")
COMPONENT_IDS = ("pill", "nav_home", "nav_search", "nav_more", "sidebar") + INTERIOR_IDS
ANCHORS = ("top-left", "top-right", "bottom-left", "bottom-right", "center")
# Align spec edges (round 37, SL-22): left/right/center_x are the x-axis
# edges, top/bottom/center_y the y-axis ones. An edge only ever aligns to a
# reference edge on the same axis.
EDGES = ("left", "right", "top", "bottom", "center_x", "center_y")
_X_EDGES = ("left", "right", "center_x")
# Attach spec slots (round 41, SL-27): named anchors inside a container —
# the four corners, inset points inward.
ATTACH_SLOTS = ("top-right", "top-left", "bottom-right", "bottom-left")

APP_LAYOUT_FILE = Path(__file__).resolve().parent / "layout.toml"

_FILE_HEADER = """\
# layout.toml — persisted layout overrides for the spotify_light chrome.
# Written by the MCP layout tools (layout_set / layout_align / layout_attach /
# layout_clear) and the effect tools (effect_apply / effect_remove, SL-34);
# read at startup. Specs stay resize-safe: anchor + inward dx/dy offsets
# re-resolve against the window size every frame, align specs re-resolve
# against the reference's current rect, and attach specs re-resolve against
# the container's current rect. A raw rect table persists only as the
# degenerate fallback. Effect tables (["<id>".effect]) declare scrim bands:
# edge, height (band + fade), fade, alpha, margin. Table headers quote the
# id so dotted interior ids stay one literal key. Hand edits are fine —
# malformed entries are ignored, never fatal.
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


def _edge_point(rect: Rect, edge: str) -> float:
    """The 1D position of an edge along its axis."""
    x, y, w, h = rect
    return {"left": x, "right": x + w, "center_x": x + w / 2.0,
            "top": y, "bottom": y + h, "center_y": y + h / 2.0}[edge]


def attach_slot_rect(frame: Rect, slot: str, inset: float,
                     size: tuple[float, float]) -> Rect:
    """The rect a `size` component occupies when attached at `slot` inside
    `frame`, `inset` points in from the frame's corner (round 41, SL-27).
    The component keeps its size; the position clamps inside the frame so
    a degenerate (tiny) container can never push it outside. Works in any
    coordinate space — pass a container-local frame for a local rect, the
    window-space frame for a window rect."""
    fx, fy, fw, fh = frame
    sw, sh = size
    if slot in ("top-right", "bottom-right"):
        x = fx + fw - inset - sw
    else:
        x = fx + inset
    if slot in ("bottom-right", "bottom-left"):
        y = fy + fh - inset - sh
    else:
        y = fy + inset
    x = min(max(x, fx), max(fx, fx + fw - sw))
    y = min(max(y, fy), max(fy, fy + fh - sh))
    return (x, y, sw, sh)


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
        forms = [form for form in ("rect", "anchor", "align", "attach") if form in spec]
        if len(forms) != 1:
            raise LayoutError(
                f"spec for {cid} needs exactly one of 'rect', 'anchor', 'align', "
                f"or 'attach', got {sorted(spec)}")
        if "attach" in spec:
            stored = {"attach": self._validate_attach_spec(cid, spec["attach"])}
        elif "align" in spec:
            stored = {"align": self._validate_align_spec(cid, spec["align"])}
        elif "rect" in spec:
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
        if "align" in stored or "attach" in stored:
            self._check_align_cycle(cid, stored)
        self._specs[cid] = stored
        return dict(stored)

    def _validate_attach_spec(self, cid: str, raw: object) -> dict:
        """Validate an attach spec (round 41, SL-27): containment of a
        window-space component in a window-space container at a named slot.
        No self-attach, no interior ids on either side (they already live
        in the pill's local frame), and the inset is a finite number.
        Cycles are rejected separately (staged, like align)."""
        if cid in INTERIOR_IDS:
            raise LayoutError(
                f"interior id {cid} already lives in the pill's local frame; "
                "attach is a window-space relationship")
        if not isinstance(raw, dict):
            raise LayoutError(f"attach spec for {cid} must be an object, got {raw!r}")
        container = _check_id(raw.get("container"))
        if container == cid:
            raise LayoutError(f"{cid} cannot attach to itself")
        if container in INTERIOR_IDS:
            raise LayoutError(
                f"{cid} cannot attach to interior id {container!r}; "
                "attach containers are window-space components")
        slot = raw.get("slot")
        if slot not in ATTACH_SLOTS:
            raise LayoutError(
                f"unknown attach slot {slot!r}; valid slots: {', '.join(ATTACH_SLOTS)}")
        return {
            "container": container,
            "slot": slot,
            "inset": _num(raw.get("inset", 0.0), field="inset"),
        }

    @staticmethod
    def _validate_align_rule(cid: str, raw: object) -> dict:
        """Validate ONE align rule: edge-to-edge alignment against another
        id's CURRENT rect. ref_edge defaults to edge; the two must share an
        axis. keep="size" (round 38) is only meaningful on edge rules — it
        moves the named edge to the reference line holding the extent,
        where the default keeps the opposite edge fixed and changes the
        extent. References stay in one frame — interior ids reference
        interior ids (or the pill frame itself as "pill"), window ids
        reference window ids — and never the component itself."""
        if not isinstance(raw, dict):
            raise LayoutError(f"align rule for {cid} must be an object, got {raw!r}")
        edge = raw.get("edge")
        if edge not in EDGES:
            raise LayoutError(f"unknown align edge {edge!r}; valid edges: {', '.join(EDGES)}")
        ref_edge = raw.get("ref_edge", edge)
        if ref_edge not in EDGES:
            raise LayoutError(
                f"unknown align ref_edge {ref_edge!r}; valid edges: {', '.join(EDGES)}")
        if (edge in _X_EDGES) != (ref_edge in _X_EDGES):
            raise LayoutError(
                f"align edge {edge!r} and ref_edge {ref_edge!r} are on different axes")
        to = _check_id(raw.get("to"))
        if to == cid:
            raise LayoutError(f"{cid} cannot align to itself")
        if cid in INTERIOR_IDS:
            if to not in INTERIOR_IDS and to != "pill":
                raise LayoutError(
                    f"interior id {cid} can only reference the pill's interior "
                    f"(or 'pill' itself), not {to!r}")
        elif to in INTERIOR_IDS:
            raise LayoutError(f"window id {cid} cannot reference interior id {to!r}")
        keep = raw.get("keep", "opposite")
        if keep not in ("opposite", "size"):
            raise LayoutError(f"align keep must be 'opposite' or 'size', got {keep!r}")
        if keep == "size" and edge in ("center_x", "center_y"):
            raise LayoutError(
                f"keep='size' applies to edge rules, not center edge {edge!r} "
                "(center rules already hold the size)")
        rule = {
            "edge": edge,
            "to": to,
            "ref_edge": ref_edge,
            "offset": _num(raw.get("offset", 0.0), field="offset"),
        }
        if keep == "size":
            rule["keep"] = "size"  # stored only when non-default, so single-rule specs stay round-37-shaped
        return rule

    def _validate_align_spec(self, cid: str, raw: object) -> dict | list[dict]:
        """The align VALUE: one rule dict (the round-37 form) or a list of
        up to two rules on distinct axes (round 38). Lists normalize to a
        deterministic order (x rule first, then y, by edge name) so the
        persisted file is stable; a single-rule list canonicalizes to the
        plain dict form."""
        if isinstance(raw, dict):
            return self._validate_align_rule(cid, raw)
        if isinstance(raw, list):
            if not 1 <= len(raw) <= 2:
                raise LayoutError(
                    f"align for {cid} takes 1 or 2 rules (one per axis), got {len(raw)}")
            rules = [self._validate_align_rule(cid, item) for item in raw]
            axes = ["x" if rule["edge"] in _X_EDGES else "y" for rule in rules]
            if len(set(axes)) != len(axes):
                raise LayoutError(
                    f"align rules for {cid} must be on distinct axes, got {axes}")
            rules.sort(key=lambda rule: (0 if rule["edge"] in _X_EDGES else 1, rule["edge"]))
            return rules[0] if len(rules) == 1 else rules
        raise LayoutError(
            f"align for {cid} must be a rule object or a list of rules, got {raw!r}")

    def set_align(self, component_id: object, rule: object) -> dict:
        """Upsert ONE align rule — the layout_align tool's verb (round 38).
        A rule on the same axis replaces the existing one; a rule on the
        other axis is added, so two calls build a two-axis relationship.
        Any rect/anchor spec on the id is replaced by the align form."""
        cid = _check_id(component_id)
        new_rule = self._validate_align_rule(cid, rule)
        new_axis = "x" if new_rule["edge"] in _X_EDGES else "y"
        rules: list[dict] = []
        current = self._specs.get(cid)
        if current is not None and "align" in current:
            existing = current["align"]
            rules = list(existing) if isinstance(existing, list) else [existing]
        rules = [rule_ for rule_ in rules
                 if ("x" if rule_["edge"] in _X_EDGES else "y") != new_axis]
        rules.append(new_rule)
        staged = {"align": self._validate_align_spec(cid, rules)}
        self._check_align_cycle(cid, staged)
        self._specs[cid] = staged
        return dict(staged)

    def _check_align_cycle(self, cid: str, staged: dict) -> None:
        """Walk the reference graph (align 'to' edges plus attach 'container'
        edges — a rect can depend on another rect through either form) with
        the new spec staged; reaching cid again means the specs would
        resolve each other forever. Checked at set() time so resolve()
        never loops. From an interior id, the "pill" reference is the local
        FRAME (terminal), not the window pill."""
        specs = dict(self._specs)
        specs[cid] = staged
        stack = [cid]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            spec = specs.get(current)
            if spec is None:
                continue
            refs: list[str] = []
            if "align" in spec:
                align = spec["align"]
                rules = align if isinstance(align, list) else [align]
                refs.extend(rule["to"] for rule in rules)
            if "attach" in spec:
                refs.append(spec["attach"]["container"])
            for nxt in refs:
                if current in INTERIOR_IDS and nxt == "pill":
                    continue  # the local frame, not the window pill spec
                if nxt == cid:
                    raise LayoutError(
                        f"layout cycle through {nxt!r}: {cid} would resolve against itself")
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)

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

    def resolve(self, component_id: str, natural: Rect, *, width: float, height: float,
                naturals: dict[str, Rect] | None = None) -> Rect:
        """Apply the override (if any) to the natural rect, clamped into the
        frame. Rect/anchor specs never raise: they were validated at set()
        time. Align specs additionally need the frame's naturals map (every
        id they could reference, including transitively) — resolving the
        reference's CURRENT rect, natural or overridden, is the whole point
        of the relationship."""
        spec = self._specs.get(component_id)
        if spec is None:
            return natural
        nx, ny, nw, nh = natural
        if "attach" in spec:
            attach = spec["attach"]
            container = self._attach_container_rect(
                component_id, attach, width=width, height=height, naturals=naturals)
            x, y, w, h = attach_slot_rect(container, attach["slot"], attach["inset"],
                                          (nw, nh))
        elif "align" in spec:
            align = spec["align"]
            rules = align if isinstance(align, list) else [align]
            x, y, w, h = nx, ny, nw, nh
            for rule in rules:  # at most one rule per axis, validated at set()
                ref = self._align_reference_rect(component_id, rule,
                                                 width=width, height=height, naturals=naturals)
                point = _edge_point(ref, rule["ref_edge"]) + rule["offset"]
                keep_size = rule.get("keep") == "size"
                edge = rule["edge"]
                if edge == "left":
                    if keep_size:
                        x = point              # left edge meets the line; size holds
                    else:
                        x = min(point, nx + nw - 1.0)  # right edge fixed; 1pt floor
                        w = nx + nw - x
                elif edge == "right":
                    if keep_size:
                        x = point - nw         # right edge meets the line; size holds
                    else:
                        w = max(1.0, point - nx)       # left edge fixed
                elif edge == "center_x":
                    x = point - nw / 2.0       # size fixed; position moves
                elif edge == "top":
                    if keep_size:
                        y = point
                    else:
                        y = min(point, ny + nh - 1.0)  # bottom edge fixed
                        h = ny + nh - y
                elif edge == "bottom":
                    if keep_size:
                        y = point - nh
                    else:
                        h = max(1.0, point - ny)       # top edge fixed
                else:  # center_y
                    y = point - nh / 2.0
        elif "rect" in spec:
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

    def _attach_container_rect(self, cid: str, attach: dict, *, width: float,
                               height: float,
                               naturals: dict[str, Rect] | None) -> Rect:
        """The container's CURRENT rect in window space — natural or
        overridden — so the attachment rides the container like the
        interior ids do. Containers are window ids (validated at set()),
        and cycles were rejected at set() time, so the recursion is safe."""
        container = attach["container"]
        if naturals is None or container not in naturals:
            raise LayoutError(
                f"attach container {container!r} for {cid} has no natural rect in "
                "this frame; pass the frame's naturals map to resolve()")
        return self.resolve(container, naturals[container], width=width, height=height,
                            naturals=naturals)

    def slot_reservations(self, container: str, container_rect: Rect, *,
                          naturals: dict[str, Rect] | None) -> dict[str, Rect]:
        """Every slot of `container` occupied by an attached component,
        mapped to its CONTAINER-LOCAL rect (round 41, SL-27). This is the
        container's yield input: the pill's text column reads the top-right
        reservation to stop its right edge short of the attached button."""
        reserved: dict[str, Rect] = {}
        if naturals is None:
            return reserved
        for cid, spec in self._specs.items():
            attach = spec.get("attach")
            if attach is None or attach["container"] != container or cid not in naturals:
                continue
            _, _, nw, nh = naturals[cid]
            wx, wy, w, h = attach_slot_rect(container_rect, attach["slot"],
                                            attach["inset"], (nw, nh))
            reserved[attach["slot"]] = (wx - container_rect[0], wy - container_rect[1], w, h)
        return reserved

    def _align_reference_rect(self, cid: str, align: dict, *, width: float,
                              height: float,
                              naturals: dict[str, Rect] | None) -> Rect:
        """The reference's CURRENT rect in the caller's frame. From an
        interior id, "pill" names the local frame itself — the pill's own
        (window-space) override must not leak into local coordinates."""
        to = align["to"]
        if cid in INTERIOR_IDS and to == "pill":
            return (0.0, 0.0, width, height)
        if naturals is None or to not in naturals:
            raise LayoutError(
                f"align reference {to!r} for {cid} has no natural rect in this frame; "
                "pass the frame's naturals map to resolve()")
        return self.resolve(to, naturals[to], width=width, height=height,
                            naturals=naturals)

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
                    height=local_frames.get(cid, (width, height))[1],
                    naturals=naturals)]
                for cid in sorted(self._specs)
            },
        }


# -- visual effects (SL-34) ---------------------------------------------------

EFFECT_KINDS = ("scrim",)
EFFECT_EDGES = ("top", "bottom", "left", "right")
_EFFECT_FIELDS = frozenset({"kind", "edge", "height", "fade", "alpha", "margin"})


def _check_effect_id(effect_id: object) -> str:
    if (not isinstance(effect_id, str) or not effect_id.strip()
            or '"' in effect_id or "\n" in effect_id):
        raise LayoutError(
            f"unknown effect id {effect_id!r}: non-empty text without quotes or newlines")
    return effect_id


class EffectSpecs:
    """Session-scoped registry of validated visual-effect specs, keyed by
    effect id (SL-34). A scrim spec is {kind, edge, height, fade, alpha,
    margin}: a solid band of `height - fade` points in from `edge`, then a
    smoothstep fade over the remaining `fade` points; `alpha` is the band's
    opacity (0-255); `margin` insets the band along its long axis (x for
    top/bottom edges, y for left/right). The effects twin of
    LayoutOverrides — the MCP effect tools mutate it, and it persists into
    the same layout.toml."""

    def __init__(self) -> None:
        self._specs: dict[str, dict] = {}

    def __len__(self) -> int:
        return len(self._specs)

    def specs(self) -> dict[str, dict]:
        return {eid: dict(spec) for eid, spec in self._specs.items()}

    def set(self, effect_id: object, spec: object) -> dict:
        """Validate and store a spec; returns the stored copy. A partial spec
        on an EXISTING id merges — live tuning keeps the omitted knobs — while
        a new id needs edge + height. Never partially stores."""
        eid = _check_effect_id(effect_id)
        if not isinstance(spec, dict):
            raise LayoutError(f"spec for {eid} must be an object, got {spec!r}")
        unknown = set(spec) - _EFFECT_FIELDS
        if unknown:
            raise LayoutError(f"spec for {eid} has unknown fields: {sorted(unknown)}")
        merged = dict(self._specs.get(eid, {}))
        merged.update(spec)
        stored = self._validate_effect_spec(eid, merged)
        self._specs[eid] = stored
        return dict(stored)

    def clear(self, effect_id: object = None) -> list[str]:
        if effect_id is None:
            cleared = sorted(self._specs)
            self._specs.clear()
            return cleared
        eid = _check_effect_id(effect_id)
        return [eid] if self._specs.pop(eid, None) is not None else []

    @staticmethod
    def _validate_effect_spec(eid: str, spec: dict) -> dict:
        kind = spec.get("kind", "scrim")
        if kind not in EFFECT_KINDS:
            raise LayoutError(f"kind for {eid} must be one of {EFFECT_KINDS}, got {kind!r}")
        edge = spec.get("edge")
        if edge not in EFFECT_EDGES:
            raise LayoutError(
                f"edge for {eid} must be one of {EFFECT_EDGES}, got {edge!r}")
        if "height" not in spec:
            raise LayoutError(f"height for {eid} is required for a new effect")
        height = _size(spec["height"], field="height")
        fade = _num(spec.get("fade", 0.0), field="fade")
        if not 0.0 <= fade <= height:
            raise LayoutError(
                f"fade for {eid} must sit within the height {height}, got {fade}")
        alpha = _num(spec.get("alpha", 255.0), field="alpha")
        if not 0.0 <= alpha <= 255.0:
            raise LayoutError(f"alpha for {eid} must be 0-255, got {alpha}")
        margin = _num(spec.get("margin", 0.0), field="margin")
        if margin < 0.0:
            raise LayoutError(f"margin for {eid} must be >= 0, got {margin}")
        return {"kind": kind, "edge": edge, "height": height,
                "fade": fade, "alpha": alpha, "margin": margin}


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


def load_effects(path: Path) -> EffectSpecs:
    """Seed the effect registry from the persisted file (SL-34) — the same
    fail-soft contract as load(): a missing file, malformed TOML, or invalid
    entries never keep the app from booting."""
    registry = EffectSpecs()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return registry
    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError:
        return registry
    for eid, spec in data.items():
        if not isinstance(spec, dict) or "effect" not in spec:
            continue
        try:
            registry.set(eid, spec["effect"])
        except LayoutError:
            continue
    return registry


def _toml_num(value: float) -> str:
    return repr(float(value))


def _align_toml_lines(rule: dict) -> list[str]:
    lines = [f'edge = "{rule["edge"]}"',
             f'to = "{rule["to"]}"',
             f'ref_edge = "{rule["ref_edge"]}"',
             f"offset = {_toml_num(rule['offset'])}"]
    if rule.get("keep") == "size":
        lines.append('keep = "size"')
    return lines


def _effect_toml_lines(spec: dict) -> list[str]:
    return [f'kind = "{spec["kind"]}"',
            f'edge = "{spec["edge"]}"',
            f"height = {_toml_num(spec['height'])}",
            f"fade = {_toml_num(spec['fade'])}",
            f"alpha = {_toml_num(spec['alpha'])}",
            f"margin = {_toml_num(spec['margin'])}"]


def save(specs: dict[str, dict], path: Path, *,
         effects: dict[str, dict] | None = None) -> None:
    """Rewrite the persisted file with the registries' specs. Deterministic
    (sorted ids, fixed formatting) so the git diff shows only the nudge.
    Written via a sibling temp file + replace so a crash mid-write can't
    tear the file. Table headers always quote the id (round 37): an
    UNQUOTED dotted id like [pill.progress.rect] parses as nested tables
    and collides with [pill] — quoting keeps every id one literal key.
    effects=None (SL-34) preserves the effect tables the file already
    carries, so layout-only callers never silently drop declared effects;
    pass an explicit dict — empty included — to rewrite them."""
    if effects is None:
        effects = load_effects(path).specs()
    chunks = [_FILE_HEADER]
    for cid in sorted(specs):
        quoted = f'"{cid}"'
        spec = specs[cid]
        if "attach" in spec:
            attach = spec["attach"]
            body = "\n".join([f'container = "{attach["container"]}"',
                              f'slot = "{attach["slot"]}"',
                              f"inset = {_toml_num(attach['inset'])}"])
            chunks.append(f"[{quoted}.attach]\n{body}\n")
        elif "align" in spec:
            align = spec["align"]
            rules = align if isinstance(align, list) else [align]
            if len(rules) == 1:
                body = "\n".join(_align_toml_lines(rules[0]))
                chunks.append(f"[{quoted}.align]\n{body}\n")
            else:  # two-axis relationship (round 38): one array entry per rule
                for rule in rules:
                    body = "\n".join(_align_toml_lines(rule))
                    chunks.append(f"[[{quoted}.align]]\n{body}\n")
        elif "rect" in spec:
            rect = spec["rect"]
            body = "\n".join(
                f"{key} = {_toml_num(rect[key])}"
                for key in ("x", "y", "width", "height"))
            chunks.append(f"[{quoted}.rect]\n{body}\n")
        else:
            lines = [f'anchor = "{spec["anchor"]}"',
                     f"dx = {_toml_num(spec['dx'])}",
                     f"dy = {_toml_num(spec['dy'])}"]
            if "width" in spec:
                lines.append(f"width = {_toml_num(spec['width'])}")
            if "height" in spec:
                lines.append(f"height = {_toml_num(spec['height'])}")
            chunks.append(f"[{quoted}]\n" + "\n".join(lines) + "\n")
    for eid in sorted(effects):
        quoted = f'"{eid}"'
        chunks.append(f"[{quoted}.effect]\n" + "\n".join(_effect_toml_lines(effects[eid])) + "\n")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(chunks), encoding="utf-8")
    os.replace(tmp, path)
