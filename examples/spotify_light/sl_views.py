"""Scene-graph rendering for the Spotify Light desktop UI.

Draws the Spotify-style shell — sidebar, content views, now-playing bar —
with the luvatrix scene primitives (rects, rounded rects, circles, text) plus
``CpuLayerNode`` textures for album art. Functions only emit nodes and hit
regions; all data flows in through plain arguments, all interaction flows out
through the returned hit regions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from luvatrix_core.core.scene_graph import CpuLayerNode

import sl_icons
import sl_models
import sl_ui

# -- layout ------------------------------------------------------------------
SIDEBAR_W = 240.0
SIDEBAR_LIST_TOP = 142.0  # title + one nav row (Library) + section header
DOCK_H = 92.0             # bottom reservation for the floating pill zone
CONTENT_PAD = 28.0
CARD_W = 180.0
CARD_H = 236.0
CARD_GAP = 24.0
CARD_ART = 180.0
ROW_H = 48.0
NAV_H = 44.0

# -- theme (Spotify desktop palette) ------------------------------------------
BG = (18, 18, 18, 255)
CARD_BG = (26, 26, 26, 255)
CARD_HOVER_BG = (42, 42, 42, 255)
ROW_HOVER_BG = (30, 30, 30, 255)
BAR_BG = (24, 24, 24, 255)
# Low-alpha light tint drawn under glass capsules so the material reads on
# near-black backdrops (the blur alone is barely visible against #121212).
GLASS_TINT = (255, 255, 255, 24)

# -- simulated liquid glass ----------------------------------------------------
# Native NSGlassEffectView composites ABOVE the Metal scene and blurs every
# scene glyph beneath it (live bug, round 6), so glass over scene content is
# composed in-scene: soft shadow, hairline border ring, translucent fill,
# sheen band, specular top highlight. Native glass stays behind native
# controls only (login wall, sheet buttons).
CARD_RADIUS = 14.0
GLASS_FILL = (255, 255, 255, 18)
GLASS_FILL_HOVER = (255, 255, 255, 34)
GLASS_BORDER = (255, 255, 255, 36)
GLASS_BORDER_HOVER = (255, 255, 255, 56)
# Specular top-edge peak alpha. Round 28: 68 read as a hard thin line across
# every plate; 44 with ends fading to zero keeps the light without the wire.
GLASS_HIGHLIGHT = (255, 255, 255, 44)
GLASS_SHEEN = (255, 255, 255, 12)
GLASS_SHADOW_NEAR = (0, 0, 0, 64)
GLASS_SHADOW_FAR = (0, 0, 0, 34)
# Chrome plates (sidebar): dark translucent material so scene text stays
# readable, with specular edges for depth.
# The rail is one floating liquid-glass plate — the dock pill's material
# turned vertical (Alec, round 29). Hover/selection are tint/alpha shifts
# inside the idiom, and the scrolling list dissolves at both seams.
SIDEBAR_GLASS_MARGIN = 8.0
SIDEBAR_GLASS_RADIUS = 16.0
SIDEBAR_ROW_HOVER = (255, 255, 255, 26)
SIDEBAR_SEAM_STRIPS = 6
SIDEBAR_SEAM_FADE_PX = 20.0
# Floating player pill: a centered capsule (liquid-glass music-pill
# reference), dark-frosted so scene text stays readable over content,
# flanked by circular nav buttons; playback extras live in a popup.
PILL_W = 460.0
PILL_MIN_W = 320.0
PILL_H = 64.0
PILL_FLOAT = 16.0
PILL_FILL = (16, 16, 16, 208)
PILL_BORDER = (255, 255, 255, 40)
PILL_THUMB_EMPTY = (255, 255, 255, 16)
PILL_META_RIGHT_PAD = 150.0
NAV_CIRCLE_R = 22.0
NAV_CIRCLE_GAP = 18.0
OVERFLOW_R = NAV_CIRCLE_R
# Bottom scrim (round 8b): content scrolled under the translucent pill read
# as text-on-text clashes (reported as a z-index bug; the pill was already
# topmost). Apple Music idiom: a gradient scrim behind the dock zone
# dissolves content before it reaches the pill; the pill keeps its material.
# Round 10: the fade completes SCRIM_GAP above the pill top, leaving a calm
# near-opaque band between dissolved content and the chrome.
SCRIM_FADE = 56.0
SCRIM_GAP = 12.0
SCRIM_H = PILL_FLOAT + PILL_H + SCRIM_GAP + SCRIM_FADE
SCRIM_MAX_ALPHA = 240
# Round 14: the fade renders as ~1px strips (coarse strips read as scanlines
# over album art), and the calm band below the fade is one solid rect.
SCRIM_STRIP_PX = 1.0


def pill_rect(width: float, height: float) -> tuple[float, float, float, float]:
    """Now-playing capsule, pinned to the window's TOP-RIGHT corner (Alec,
    round 30): right edge at width - PILL_FLOAT, top at the same float
    margin the dock used. Anchoring the RIGHT edge means any width change
    (window resize, or the pill shrinking below PILL_W when the content
    region can't fit it) grows the pill leftward — never a jump. The left
    edge can never cross the sidebar."""
    fit_w = width - SIDEBAR_W - 2 * PILL_FLOAT
    pill_w = min(PILL_W, max(PILL_MIN_W, fit_w))
    pill_x = max(SIDEBAR_W + PILL_FLOAT, width - PILL_FLOAT - pill_w)
    return (pill_x, PILL_FLOAT, pill_w, PILL_H)


def _layout(app, component_id: str, natural: tuple[float, float, float, float],
            width: float, height: float) -> tuple[float, float, float, float]:
    """Consult the live layout-override registry (round 31): an override wins
    over the app's own recomputation because every draw resolves through here.
    Apps without the registry (tests, older hosts) get the natural rect."""
    overrides = getattr(app, "layout_overrides", None)
    if overrides is None:
        return natural
    return overrides.resolve(component_id, natural, width=width, height=height)


def dock_cluster_rect(width: float, height: float) -> tuple[float, float, float, float]:
    """The bottom-center cluster slot the pill vacated in round 30. The
    Home/Search nav circles and the playback popup did NOT move with the
    pill — they still anchor to this slot, centered on the CONTENT REGION
    (round 10): the cluster (circles + slot) centers between SIDEBAR_W and
    the window's right edge — never the full window, so it can never cross
    the sidebar (the scrim anchors the same way). When the cluster at design
    width can't fit, the left circle pins to SIDEBAR_W + PILL_FLOAT and the
    right edge floats; only then does the slot shrink below PILL_W (floor
    PILL_MIN_W). Below ~716pt the search circle may clip the window edge —
    pathological."""
    cluster_pad = NAV_CIRCLE_GAP + 2 * NAV_CIRCLE_R
    min_x = SIDEBAR_W + PILL_FLOAT + cluster_pad
    fit_w = width - PILL_FLOAT - cluster_pad - min_x
    pill_w = min(PILL_W, max(PILL_MIN_W, fit_w))
    ideal_x = (SIDEBAR_W + width) / 2.0 - pill_w / 2.0
    max_x = width - PILL_FLOAT - cluster_pad - pill_w
    pill_x = min(max(ideal_x, min_x), max(max_x, min_x))
    return (pill_x, height - PILL_FLOAT - PILL_H, pill_w, PILL_H)

TEXT = (255, 255, 255, 255)
SUBTEXT = (179, 179, 179, 255)
FAINT = (120, 120, 120, 255)
FONT_FAMILY = "Helvetica Neue"

ACCENT = (29, 185, 84, 255)
ACCENT_DARK = (20, 140, 64, 255)
DANGER = (226, 90, 74, 255)
FIELD_BG = (36, 36, 36, 255)
FIELD_BORDER = (90, 90, 90, 255)
POPUP_BG = (34, 34, 34, 255)


@dataclass(frozen=True)
class HitRegion:
    x: float
    y: float
    w: float
    h: float
    action: str
    payload: object = None

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px <= self.x + self.w and self.y <= py <= self.y + self.h


@dataclass
class FrameOut:
    """What a view draw returns: click targets + scroll bookkeeping."""

    hits: list[HitRegion] = field(default_factory=list)
    content_height: float = 0.0

    def hit(self, x, y, w, h, action, payload=None) -> None:
        self.hits.append(HitRegion(x, y, w, h, action, payload))


def _ck(*parts: object) -> str:
    return "|".join(str(p) for p in parts)


def _fit_width(measure, text: str, *, max_w: float, size: float) -> str:
    """Truncate to a measured pixel budget — proportional fonts make char
    counts width-blind (a 40-char cap both over-truncates narrow strings and
    lets wide ones paint into neighboring chrome). An ellipsis marks the cut."""
    if measure(text, font_size_px=float(size), font_family=FONT_FAMILY) <= max_w:
        return text
    cut = text
    while cut and measure(cut + "…", font_size_px=float(size),
                          font_family=FONT_FAMILY) > max_w:
        cut = cut[:-1]
    return (cut.rstrip() + "…") if cut else "…"


def _clip_head(measure, text: str, *, max_w: float, size: float) -> str:
    """Text-field overflow clips the HEAD with a leading ellipsis so the tail
    being typed stays visible (the macOS field idiom); the caret then hugs
    the end of the shown tail inside the field."""
    if measure(text, font_size_px=float(size), font_family=FONT_FAMILY) <= max_w:
        return text
    tail = text
    while tail and measure("…" + tail, font_size_px=float(size),
                           font_family=FONT_FAMILY) > max_w:
        tail = tail[1:]
    return ("…" + tail.lstrip()) if tail else "…"


# Ink-height / font-size ratios for the Phosphor icons, measured on the
# bundled TTFs through the headless rasterizer with the same bright-ink mask
# as the TestDockIconCentering pins (text node y is the INK TOP, not the
# baseline). Used to vertically center an icon's ink box on a target point.
_ICON_INK_RATIO = {
    sl_icons.HOME: 0.765,
    sl_icons.SEARCH: 0.824,
    sl_icons.MORE: 0.062,   # three small dots: a short, thin row of ink
    sl_icons.PREV: 0.750,
    sl_icons.NEXT: 0.750,
    sl_icons.PLAY: 0.769,
    sl_icons.NOTE: 0.750,
}

# Optical-centering corrections in EM units (fraction of font size), measured
# from rendered ink-mass centroids: a right-pointing triangle's mass sits left
# of its ink-box center, the skip buttons carry a bar on one side, and thin
# outlines (house, note) have uneven mass. Each entry shifts placement so the
# measured centroid lands on the target center.
_ICON_OPTICAL_BIAS_EM = {
    sl_icons.HOME: (0.086, -0.098),
    sl_icons.SEARCH: (0.088, 0.046),
    sl_icons.MORE: (0.219, -0.032),
    sl_icons.PREV: (0.175, 0.031),
    sl_icons.NEXT: (0.262, 0.031),
    sl_icons.PLAY: (0.289, -0.021),
    sl_icons.NOTE: (0.131, -0.100),  # bottom-heavy glyph: lift ~2px at the 20px tile
}


def _centered_glyph(frame, text, *, cx, cy, size, color, z,
                    font=FONT_FAMILY) -> None:
    w = frame._ctx.measure_text(text, font_size_px=float(size), font_family=font)
    ratio = _ICON_INK_RATIO.get(text, 0.882)
    bias_x, bias_y = _ICON_OPTICAL_BIAS_EM.get(text, (0.0, 0.0))
    _text(frame, text, x=round(cx - w / 2 + bias_x * size),
          y=round(cy - ratio * size / 2 + bias_y * size), size=size, color=color,
          z=z, font=font)


def _text(frame, text, *, x, y, size=14.0, color=TEXT, z=2, max_chars=0,
          font=FONT_FAMILY) -> None:
    shown = sl_ui.truncate(text, max_chars) if max_chars else text
    if not shown:
        return
    frame.text(
        shown,
        x=x,
        y=y,
        font_size_px=size,
        color=color,
        z_index=z,
        cache_key=_ck("t", shown, size, color, font),
        font_family=font,
    )


def _art(frame, app, image_url, *, x, y, size, seed, z=2, corner_radius=0.0) -> None:
    """Draw album art from the cache, or a placeholder while the fetch lands."""
    rgba = app.art_for(image_url, int(size)) if image_url else None
    if rgba is None:
        rgba = app.art_cache.placeholder(seed, int(size))
    if corner_radius > 0.0:
        # Alpha-clip to the rounded tile (the renderer has no image clip):
        # square corners crossing a rounded silhouette read as a glitch.
        # Buffers are device-pixel sized, so the radius scales with them.
        radius_px = corner_radius * rgba.shape[0] / float(size)
        rgba = app.art_cache.masked(rgba, radius_px, key=image_url or f"placeholder:{seed}")
    # SceneFrame exposes no image primitive; CpuLayerNode carries the pixels.
    frame._ctx.add_scene_node(
        CpuLayerNode(x=float(x), y=float(y), width=float(size), height=float(size), rgba=rgba, z_index=z)
    )


def _hover(mouse, x, y, w, h) -> bool:
    mx, my = mouse
    return x <= mx <= x + w and y <= my <= y + h


def _glass_plate(frame, x, y, w, h, *, radius, z, hovering=False, shadow=True,
                 fill=None, border=None) -> None:
    """One canonical simulated-glass plate. Composed back-to-front: soft
    shadow (two stacked dark plates), hairline border ring, translucent fill
    inset 1px so the ring reads as the edge, a sheen band, and the specular
    top highlight that catches the light."""
    if shadow:
        frame.rounded_rect(x=x - 1, y=y + 5, width=w + 2, height=h, radius=radius,
                           color=GLASS_SHADOW_FAR, z_index=z)
        frame.rounded_rect(x=x, y=y + 2, width=w, height=h, radius=radius,
                           color=GLASS_SHADOW_NEAR, z_index=z)
    frame.rounded_rect(x=x, y=y, width=w, height=h, radius=radius,
                       color=border or (GLASS_BORDER_HOVER if hovering else GLASS_BORDER),
                       z_index=z)
    frame.rounded_rect(x=x + 1, y=y + 1, width=w - 2, height=h - 2,
                       radius=max(0.0, radius - 1),
                       color=fill or (GLASS_FILL_HOVER if hovering else GLASS_FILL), z_index=z)
    # The sheen is a silhouette-clipped falloff, not a square band: thin rows
    # chord-clipped inside the top corner arc (so they can never poke past
    # the rounded silhouette) with alpha ramping to zero at the bottom. One
    # hard-edged slab floats inside the plate interior and reads as a
    # rectangle behind the glyph (Alec's round-27 finding).
    band_h = max(1, int(round(h * 0.42)))
    row_h = max(1, band_h // 18)
    base_a = GLASS_SHEEN[3]
    yy = y + 2.0
    drawn = 0
    while drawn < band_h:
        rh = min(float(row_h), float(band_h - drawn))
        depth = yy + rh / 2 - y
        if depth < radius:
            chord = radius - math.sqrt(max(0.0, radius * radius - (radius - depth) ** 2))
        else:
            chord = 0.0
        inset = max(2.0, chord + 1.0)
        alpha = int(round(base_a * max(0.0, 1.0 - drawn / band_h)))
        if alpha > 0:
            frame.rect(x=x + inset, y=yy, width=max(0.0, w - inset * 2),
                       height=rh, color=(255, 255, 255, alpha), z_index=z)
        yy += rh
        drawn += int(rh)
    # Specular top highlight: one uniform full-span 1px line reads as a hard
    # artifact (Alec, round 28). Draw it as segments whose alpha falls to
    # nothing at the ends — same chord-safe span, no hard wire.
    inset = radius * 0.7
    line_x = x + inset
    line_w = max(0.0, w - inset * 2)
    segments = 16
    seg_w = line_w / segments
    for i in range(segments):
        d = abs((i + 0.5) / segments - 0.5) * 2  # 0 at the centre, ~1 at the ends
        alpha = int(round(GLASS_HIGHLIGHT[3] * max(0.0, (1.0 - d * d) ** 2)))
        if alpha > 0:
            frame.rect(x=line_x + i * seg_w, y=y + 1, width=seg_w + 0.5, height=1,
                       color=(255, 255, 255, alpha), z_index=z)


def _daypart() -> str:
    import datetime

    hour = datetime.datetime.now().hour
    if hour < 12:
        return "morning"
    if hour < 18:
        return "afternoon"
    return "evening"


# -- sidebar -------------------------------------------------------------------


def _cull_bottom(app, height: float) -> float:
    """Bottom cull edge for content views.

    The player bar is simulated glass on every host, so content flows under
    it everywhere — cull at the window bottom.
    """
    return height


def draw_sidebar(frame, app, out: FrameOut, *, width: float, height: float, mouse) -> None:
    # One floating liquid-glass rail — the dock's `_glass_plate` construction
    # (border ring, translucent fill, silhouette-clipped sheen, softened
    # specular, soft shadow) at full height. Scene-drawn: native glass here
    # blurred the nav text (live bug), and bridgeless hosts get the same
    # material. Text contrast holds by construction — only the dark window
    # backdrop sits behind the rail (content starts at SIDEBAR_W).
    # Round 31: the rail resolves through the live layout registry — an
    # override moves the plate, and everything on it shifts by the same delta
    # from the rail's natural origin.
    m = SIDEBAR_GLASS_MARGIN
    rx, ry, rw, rh = _layout(
        app, "sidebar", (m, m, SIDEBAR_W - m * 2, height - m * 2), width, height)
    _glass_plate(frame, rx, ry, rw, rh, radius=SIDEBAR_GLASS_RADIUS, z=1)
    ox, oy = rx - m, ry - m
    _text(frame, "Spotify Light", x=22 + ox, y=20 + oy, size=20, color=ACCENT, z=3)

    # Home/Search live on the glass circles flanking the player pill (round
    # 8); the sidebar keeps Library, playlists, and account.
    nav = [("library", "Your Library")]
    y = 64.0 + oy
    for view, label in nav:
        active = app.view == view
        hovering = _hover(mouse, 10 + ox, y - 6, SIDEBAR_W - 20, NAV_H - 8)
        if active:
            _glass_plate(frame, 10 + ox, y - 6, SIDEBAR_W - 20, NAV_H - 8, radius=8.0, z=2,
                         shadow=False)
        elif hovering:
            frame.rounded_rect(x=10 + ox, y=y - 6, width=SIDEBAR_W - 20, height=NAV_H - 8,
                               radius=8.0, color=SIDEBAR_ROW_HOVER, z_index=2)
        color = TEXT if (active or hovering) else SUBTEXT
        _text(frame, label, x=22 + ox, y=y + 2, size=15, color=color, z=3)
        out.hit(10 + ox, y - 6, SIDEBAR_W - 20, NAV_H - 8, "nav", view)
        y += NAV_H

    y += 10
    _text(frame, "PLAYLISTS", x=22 + ox, y=y, size=11, color=FAINT, z=3)
    y += 24

    list_top = y
    list_bottom = height - 64 + oy
    row_h = 30.0
    offset = app.sidebar_scroll
    for idx, playlist in enumerate(app.playlists):
        row_y = list_top + row_h * idx - offset
        if row_y + row_h < list_top or row_y > list_bottom:
            continue
        hovering = _hover(mouse, 10 + ox, row_y, SIDEBAR_W - 20, row_h - 4)
        if hovering:
            frame.rounded_rect(x=10 + ox, y=row_y, width=SIDEBAR_W - 20, height=row_h - 4,
                               radius=6.0, color=SIDEBAR_ROW_HOVER, z_index=2)
        _text(frame, playlist.name, x=22 + ox, y=row_y + 4, size=13,
              color=TEXT if hovering else SUBTEXT, z=3, max_chars=26)
        out.hit(10 + ox, row_y, SIDEBAR_W - 20, row_h - 4, "open_playlist", playlist.id)

    # The list scrolls under the glass: dissolve both seams with a short
    # alpha ramp (the pill scrim's idiom) instead of a hard cutoff line.
    if row_h * len(app.playlists) > list_bottom - list_top:
        strip = SIDEBAR_SEAM_FADE_PX / SIDEBAR_SEAM_STRIPS
        for i in range(SIDEBAR_SEAM_STRIPS):
            a_top = int(round(210 * (1.0 - i / SIDEBAR_SEAM_STRIPS)))
            frame.rect(x=rx + 2, y=list_top + i * strip, width=rw - 4, height=strip,
                       color=(14, 14, 14, a_top), z_index=4)
            a_bottom = int(round(210 * (i + 1) / SIDEBAR_SEAM_STRIPS))
            frame.rect(x=rx + 2, y=list_bottom - SIDEBAR_SEAM_FADE_PX + i * strip,
                       width=rw - 4, height=strip, color=(14, 14, 14, a_bottom), z_index=4)
    _draw_scrollbar(frame, app.scrollbar_sidebar, out, x=rx + rw - 9, top=list_top,
                    bottom=list_bottom, content=row_h * len(app.playlists), offset=offset,
                    tag="sidebar")

    chip_y = height - 52 + oy
    frame.rect(x=rx + 14, y=chip_y - 8, width=rw - 28, height=1,
               color=(255, 255, 255, 20), z_index=2)
    name = app.profile.display_name if app.profile and app.profile.display_name else "Account"
    _text(frame, name, x=22 + ox, y=chip_y + 4, size=13, color=SUBTEXT, z=3, max_chars=16)
    hovering = _hover(mouse, 150 + ox, chip_y, 70, 26)
    _text(frame, "Log out", x=156 + ox, y=chip_y + 4, size=13, color=TEXT if hovering else FAINT, z=3)
    out.hit(150 + ox, chip_y - 2, 74, 28, "logout")


def _draw_scrollbar(frame, controller, out: FrameOut, *, x, top, bottom, content, offset, tag) -> None:
    view = bottom - top
    if content <= view or view <= 0:
        return
    metrics = controller.metrics(
        track_extent=view, content_extent=content, viewport_extent=view, offset=offset
    )
    if metrics.thumb_extent <= 0:
        return
    frame.rounded_rect(x=x, y=top + metrics.thumb_start, width=5, height=metrics.thumb_extent,
                       radius=2.5, color=(90, 90, 90, 255), z_index=4)
    out.hit(x - 4, top, 13, view, "scrollbar", tag)


# -- shared cards ----------------------------------------------------------------


def _draw_card(frame, app, out: FrameOut, card: sl_ui.CardView, *, x, y, mouse) -> None:
    hovering = _hover(mouse, x, y, CARD_W, CARD_H)
    _glass_plate(frame, x, y, CARD_W, CARD_H, radius=CARD_RADIUS, z=2, hovering=hovering)
    _art(frame, app, card.image_url, x=x + 12, y=y + 12, size=CARD_ART - 24, seed=card.title)
    _text(frame, card.title, x=x + 12, y=y + CARD_ART + 8, size=14, z=3, max_chars=22)
    _text(frame, card.subtitle, x=x + 12, y=y + CARD_ART + 28, size=12, color=SUBTEXT, z=3,
          max_chars=26)
    if card.kind in ("playlist", "album"):
        out.hit(x, y, CARD_W, CARD_H, "open_card", card)
    elif card.kind == "track":
        out.hit(x, y, CARD_W, CARD_H, "play_card", card)
    if hovering and card.context_uri:
        frame.circle(cx=x + CARD_W - 28, cy=y + CARD_ART - 26, radius=20,
                     fill=(0, 0, 0, 90), z_index=3)
        frame.circle(cx=x + CARD_W - 28, cy=y + CARD_ART - 28, radius=20, fill=ACCENT, z_index=3)
        _centered_glyph(frame, sl_icons.PLAY, cx=x + CARD_W - 28, cy=y + CARD_ART - 28,
                        size=18, color=(0, 0, 0, 255), z=4, font=sl_icons.ICON_FONT_FILL)


def _draw_track_table(frame, app, out: FrameOut, rows, *, x0, y0, width, height, context_uri, mouse) -> float:
    table_w = width - SIDEBAR_W - CONTENT_PAD * 2
    for row in rows:
        row_y = y0 + (row.index - 1) * ROW_H
        if row_y + ROW_H < 0 or row_y > _cull_bottom(app, height):
            continue
        hovering = _hover(mouse, x0 - 8, row_y, table_w + 8, ROW_H)
        if hovering:
            frame.rounded_rect(x=x0 - 8, y=row_y + 2, width=table_w + 8, height=ROW_H - 6,
                               radius=6.0, color=ROW_HOVER_BG, z_index=1)
        now_playing = app.player is not None and app.player.track is not None and app.player.track.uri == row.uri
        _text(frame, str(row.index), x=x0, y=row_y + 14, size=13, color=FAINT, z=3)
        _text(frame, row.title, x=x0 + 40, y=row_y + 6, size=14,
              color=ACCENT if now_playing else TEXT, z=3, max_chars=38)
        _text(frame, row.artists, x=x0 + 40, y=row_y + 26, size=12, color=SUBTEXT, z=3, max_chars=42)
        if context_uri is not None:
            _text(frame, row.album, x=x0 + table_w * 0.55, y=row_y + 14, size=13, color=SUBTEXT, z=3,
                  max_chars=24)
        _text(frame, row.duration, x=x0 + table_w - 56, y=row_y + 14, size=13, color=SUBTEXT, z=3)
        if context_uri is not None:
            out.hit(x0 - 8, row_y + 2, table_w + 8, ROW_H - 6, "play_track_in_context",
                    (context_uri, row.uri))
        else:
            out.hit(x0 - 8, row_y + 2, table_w + 8, ROW_H - 6, "play_uris", [row.uri])
    return y0 + len(rows) * ROW_H


# -- home ------------------------------------------------------------------------


def draw_home(frame, app, out: FrameOut, *, width: float, height: float, mouse) -> None:
    x0 = SIDEBAR_W + CONTENT_PAD
    y = 24.0 - app.content_scroll
    view_w = width - SIDEBAR_W - CONTENT_PAD * 2
    _text(frame, "Good " + _daypart(), x=x0, y=y, size=26, z=3)
    y += 46

    if not getattr(app, "_bootstrap_done", False):
        _text(frame, "Loading your music…", x=x0, y=y, size=15, color=SUBTEXT, z=3)
        y += 30
    elif app.bootstrap_error:
        # Persistent error line (auth_error pattern): a failed bootstrap must
        # never read as eternal loading.
        _text(frame, app.bootstrap_error, x=x0, y=y, size=14, color=DANGER, z=3)
        y += 30
    elif not app.home_sections and not getattr(app, "bootstrap_notices", ()):
        _text(frame, "Nothing here yet — your playlists and listens will show up here",
              x=x0, y=y, size=15, color=SUBTEXT, z=3)
        y += 30

    # Per-section degradations (e.g. Spotify dev-mode 403s): each note names
    # the call that failed; surviving sections render below.
    for note in getattr(app, "bootstrap_notices", ()):
        _text(frame, note, x=x0, y=y, size=13, color=FAINT, z=3)
        y += 24

    cols = sl_ui.grid_columns(view_w, card_width=CARD_W, gap=CARD_GAP)
    for section in app.home_sections:
        _text(frame, section.title, x=x0, y=y, size=19, z=3)
        y += 32
        rows = math.ceil(len(section.cards) / cols)
        for idx, card in enumerate(section.cards):
            row, col = divmod(idx, cols)
            cx = x0 + col * (CARD_W + CARD_GAP)
            cy = y + row * (CARD_H + CARD_GAP)
            if cy + CARD_H > 0 and cy < _cull_bottom(app, height):
                _draw_card(frame, app, out, card, x=cx, y=cy, mouse=mouse)
        y += rows * (CARD_H + CARD_GAP) + 12

    out.content_height = y + app.content_scroll


# -- playlist detail -------------------------------------------------------------


def draw_playlist(frame, app, out: FrameOut, *, width: float, height: float, mouse) -> None:
    x0 = SIDEBAR_W + CONTENT_PAD
    y = 24.0 - app.content_scroll
    detail = app.playlist_detail
    if detail is None:
        if app.playlist_error:
            _text(frame, "Couldn't load this playlist", x=x0, y=y, size=16, z=3)
            _text(frame, f"Spotify said {app.playlist_error}", x=x0, y=y + 26, size=13,
                  color=SUBTEXT, z=3, max_chars=64)
            retry_x, retry_y, retry_w, retry_h = x0, y + 58, 96.0, 36.0
            hovering = _hover(mouse, retry_x, retry_y, retry_w, retry_h)
            frame.rounded_rect(x=retry_x, y=retry_y + 2, width=retry_w, height=retry_h,
                               radius=18, color=(0, 0, 0, 90), z_index=2)
            frame.rounded_rect(x=retry_x, y=retry_y, width=retry_w, height=retry_h,
                               radius=18, color=ACCENT if hovering else ACCENT_DARK, z_index=2)
            _text(frame, "Retry", x=retry_x + 29, y=retry_y + 10, size=14,
                  color=(0, 0, 0, 255), z=3)
            playlist_id = app.view.split(":", 1)[1] if ":" in app.view else ""
            out.hit(retry_x, retry_y, retry_w, retry_h, "retry_playlist", playlist_id)
            return
        _text(frame, "Loading playlist…", x=x0, y=y, size=16, color=SUBTEXT, z=3)
        return

    playlist, tracks = detail
    _art(frame, app, sl_models.pick_image_url(playlist.images, app._art_pick_target(160)), x=x0, y=y, size=160,
         seed=playlist.name)
    _text(frame, "PLAYLIST", x=x0 + 190, y=y + 6, size=11, color=FAINT, z=3)
    _text(frame, playlist.name, x=x0 + 190, y=y + 26, size=30, z=3, max_chars=34)
    meta = playlist.owner_name or ""
    if playlist.track_count is not None:
        meta = f"{meta} · {playlist.track_count} tracks" if meta else f"{playlist.track_count} tracks"
    _text(frame, meta, x=x0 + 190, y=y + 70, size=13, color=SUBTEXT, z=3)
    play_x = x0 + 190
    play_y = y + 108
    hovering = _hover(mouse, play_x, play_y, 120, 40)
    frame.rounded_rect(x=play_x, y=play_y + 2, width=120, height=40, radius=20,
                       color=(0, 0, 0, 90), z_index=2)
    frame.rounded_rect(x=play_x, y=play_y, width=120, height=40, radius=20,
                       color=ACCENT if hovering else ACCENT_DARK, z_index=2)
    frame.rect(x=play_x + 14, y=play_y + 1, width=92, height=1,
               color=(255, 255, 255, 70), z_index=3)
    _text(frame, "Play", x=play_x + 42, y=play_y + 11, size=15, color=(0, 0, 0, 255), z=3)
    out.hit(play_x, play_y, 120, 40, "play_context", playlist.uri)
    y += 190

    table_w = width - SIDEBAR_W - CONTENT_PAD * 2
    _text(frame, "#", x=x0, y=y, size=12, color=FAINT, z=3)
    _text(frame, "Title", x=x0 + 40, y=y, size=12, color=FAINT, z=3)
    _text(frame, "Album", x=x0 + table_w * 0.55, y=y, size=12, color=FAINT, z=3)
    _text(frame, "Time", x=x0 + table_w - 56, y=y, size=12, color=FAINT, z=3)
    y += 24
    frame.rect(x=x0, y=y - 6, width=table_w, height=1, color=(45, 45, 45, 255), z_index=2)

    rows = sl_ui.build_track_rows(tracks)
    end_y = _draw_track_table(frame, app, out, rows, x0=x0, y0=y, width=width, height=height,
                              context_uri=playlist.uri, mouse=mouse)
    out.content_height = end_y + 40 + app.content_scroll


# -- search ---------------------------------------------------------------------


def draw_search(frame, app, out: FrameOut, *, width: float, height: float, mouse) -> None:
    x0 = SIDEBAR_W + CONTENT_PAD
    y = 24.0 - app.content_scroll
    view_w = width - SIDEBAR_W - CONTENT_PAD * 2

    # The field's right cap must clear the top-right pill (round 30): at
    # narrow widths the 460pt field would slide under the glass.
    pill_x = pill_rect(width, height)[0]
    field_w = max(180.0, min(460.0, view_w, pill_x - 12.0 - x0))
    _glass_plate(frame, x0, y, field_w, 40, radius=20.0, z=2, shadow=False,
                 border=(ACCENT[0], ACCENT[1], ACCENT[2], 200) if app.search_focused else None)
    shown = app.search_query or ("What do you want to listen to?" if not app.search_focused else "")
    if app.search_query:
        # Overflow clips the head (text-field idiom): the tail being typed
        # stays visible and the caret hugs its end inside the field.
        shown = _clip_head(app.ctx.measure_text, app.search_query,
                           max_w=field_w - 18 - 14, size=14)
        _text(frame, shown, x=x0 + 18, y=y + 12, size=14, color=TEXT, z=4)
    else:
        _text(frame, shown, x=x0 + 18, y=y + 12, size=14, color=FAINT, z=4, max_chars=52)
    if app.search_focused and int(app.now_monotonic * 2) % 2 == 0:
        caret_x = x0 + 18 + app.ctx.measure_text(
            shown if app.search_query else "", font_size_px=14.0, font_family=FONT_FAMILY)
        frame.rect(x=caret_x + 2, y=y + 10, width=1.5, height=20, color=TEXT, z_index=4)
    out.hit(x0, y, field_w, 40, "focus_search")
    y += 60

    if app.search_error:
        _text(frame, app.search_error, x=x0, y=y, size=14, color=DANGER, z=3)
        return
    results = app.search_results
    if results is None:
        if app.search_query.strip():
            _text(frame, "Searching…", x=x0, y=y, size=14, color=SUBTEXT, z=3)
        return

    if results.tracks:
        _text(frame, "Songs", x=x0, y=y, size=19, z=3)
        y += 30
        rows = sl_ui.build_track_rows(list(results.tracks)[:8])
        y = _draw_track_table(frame, app, out, rows, x0=x0, y0=y, width=width, height=height,
                              context_uri=None, mouse=mouse) + 20

    cols = sl_ui.grid_columns(view_w, card_width=CARD_W, gap=CARD_GAP)
    for title, cards in (
        ("Albums", [sl_ui.album_card(a, image_target_px=app._art_pick_target(CARD_ART)) for a in results.albums]),
        ("Artists", [sl_ui.artist_card(a, image_target_px=app._art_pick_target(CARD_ART)) for a in results.artists]),
        ("Playlists", [sl_ui.playlist_card(p, image_target_px=app._art_pick_target(CARD_ART)) for p in results.playlists]),
    ):
        if not cards:
            continue
        _text(frame, title, x=x0, y=y, size=19, z=3)
        y += 32
        rows_n = math.ceil(len(cards) / cols)
        for idx, card in enumerate(cards):
            row, col = divmod(idx, cols)
            cx = x0 + col * (CARD_W + CARD_GAP)
            cy = y + row * (CARD_H + CARD_GAP)
            if cy + CARD_H > 0 and cy < _cull_bottom(app, height):
                _draw_card(frame, app, out, card, x=cx, y=cy, mouse=mouse)
        y += rows_n * (CARD_H + CARD_GAP) + 12
    out.content_height = y + app.content_scroll


# -- library ---------------------------------------------------------------------


def draw_library(frame, app, out: FrameOut, *, width: float, height: float, mouse) -> None:
    x0 = SIDEBAR_W + CONTENT_PAD
    y = 24.0 - app.content_scroll
    _text(frame, "Your Library", x=x0, y=y, size=26, z=3)
    y += 46
    view_w = width - SIDEBAR_W - CONTENT_PAD * 2
    cols = sl_ui.grid_columns(view_w, card_width=CARD_W, gap=CARD_GAP)
    cards = [sl_ui.playlist_card(p, image_target_px=app._art_pick_target(CARD_ART)) for p in app.playlists]
    if not cards:
        _text(frame, "Playlists you create or follow will show up here.", x=x0, y=y, size=14,
              color=SUBTEXT, z=3)
        return
    rows = math.ceil(len(cards) / cols)
    for idx, card in enumerate(cards):
        row, col = divmod(idx, cols)
        cx = x0 + col * (CARD_W + CARD_GAP)
        cy = y + row * (CARD_H + CARD_GAP)
        if cy + CARD_H > 0 and cy < _cull_bottom(app, height):
            _draw_card(frame, app, out, card, x=cx, y=cy, mouse=mouse)
    out.content_height = y + rows * (CARD_H + CARD_GAP) + app.content_scroll


# -- now playing bar ---------------------------------------------------------------


def draw_dock_scrim(frame, *, width: float, height: float) -> None:
    """Vertical gradient (transparent -> near-opaque backdrop) behind the
    floating pill, flanking nav circles, and overflow circle. The fade
    completes SCRIM_GAP above the pill top (round 10), so content has fully
    dissolved before reaching the chrome and a calm near-opaque band sits
    between content and pill; below that the scrim holds to the window edge.
    z=6 sits above content (z<=4) and the content scrollbar (z=5), below
    player chrome (z=10+) and the playback popup (z=20+). Starts at
    SIDEBAR_W so the sidebar's own plate and rows stay untouched."""
    top = height - SCRIM_H
    fade_span = SCRIM_FADE  # fade completes at the pill top
    fade_rows = max(1, int(round(SCRIM_FADE / SCRIM_STRIP_PX)))
    strip_h = SCRIM_FADE / fade_rows
    for i in range(fade_rows):
        strip_bottom = top + (i + 1) * strip_h
        t = min(1.0, max(0.0, (strip_bottom - top) / fade_span))
        alpha = round(SCRIM_MAX_ALPHA * t * t * (3.0 - 2.0 * t))  # smoothstep
        # Exact 1px heights, no overlap: at this pitch a fractional tail
        # double-composites a row and reads as a darker scanline.
        frame.rect(x=SIDEBAR_W, y=top + i * strip_h, width=width - SIDEBAR_W,
                   height=strip_h, color=(BG[0], BG[1], BG[2], alpha), z_index=6)
    frame.rect(x=SIDEBAR_W, y=top + SCRIM_FADE, width=width - SIDEBAR_W,
               height=SCRIM_H - SCRIM_FADE,
               color=(BG[0], BG[1], BG[2], SCRIM_MAX_ALPHA), z_index=6)


def draw_top_scrim(frame, *, width: float, height: float) -> None:
    """Mirrored dock scrim for the top-right pill (round 30): a calm
    near-opaque band caps the window top over the pill zone, then the fade
    dissolves content downward over the same smoothstep ~1px strips, so
    headers and cards scroll under the top glass exactly like they do at the
    dock. Same z=6 sandwich: above content (z<=4) and the content scrollbar
    (z=5), below the pill (z=10+)."""
    band_h = PILL_FLOAT + PILL_H + SCRIM_GAP
    frame.rect(x=SIDEBAR_W, y=0, width=width - SIDEBAR_W, height=band_h,
               color=(BG[0], BG[1], BG[2], SCRIM_MAX_ALPHA), z_index=6)
    fade_rows = max(1, int(round(SCRIM_FADE / SCRIM_STRIP_PX)))
    strip_h = SCRIM_FADE / fade_rows
    for i in range(fade_rows):
        t = min(1.0, max(0.0, ((i + 1) * strip_h) / SCRIM_FADE))
        alpha = round(SCRIM_MAX_ALPHA * (1.0 - t * t * (3.0 - 2.0 * t)))  # mirrored smoothstep
        frame.rect(x=SIDEBAR_W, y=band_h + i * strip_h, width=width - SIDEBAR_W,
                   height=strip_h, color=(BG[0], BG[1], BG[2], alpha), z_index=6)


def draw_player_bar(frame, app, out: FrameOut, *, width: float, height: float, mouse) -> None:
    # Round 8: floating glass capsule (liquid-glass music-pill reference,
    # dark-adapted); round 30 moved the capsule to the window's top-right.
    # The circular Home/Search nav buttons and the overflow circle (volume,
    # shuffle, repeat, devices popup) stayed on the bottom dock, anchored to
    # the slot the pill vacated. Scene-drawn → same on every host.
    px, py, pw, ph = _layout(app, "pill", pill_rect(width, height), width, height)
    cy = py + ph / 2
    _glass_plate(frame, px, py, pw, ph, radius=ph / 2, z=10,
                 fill=PILL_FILL, border=PILL_BORDER)

    player = app.player
    # Pre-staged at the wall-clock boundary: the queue head shows while the
    # confirming poll is still in flight (event-driven sync).
    track = app.displayed_track()

    # Album art thumb with a hairline ring, alpha-clipped to the same r8
    # tile the idle state draws — a square image sits flush at the pill's
    # left cap and its corners cross the rounded silhouette (Alec, round 28).
    frame.rounded_rect(x=px + 9, y=py + 9, width=46, height=46, radius=9,
                       color=(255, 255, 255, 24), z_index=11)
    meta_w = pw - 64 - PILL_META_RIGHT_PAD
    if track is not None:
        image_url = sl_models.pick_image_url(track.album.images if track.album else (), app._art_pick_target(44))
        _art(frame, app, image_url, x=px + 10, y=py + 10, size=44, seed=track.name, z=12,
             corner_radius=8.0)
        _text(frame, _fit_width(frame._ctx.measure_text, track.name, max_w=meta_w, size=13),
              x=px + 64, y=py + 11, size=13, z=12)
        artists = ", ".join(a.name for a in track.artists if a.name)
        _text(frame, _fit_width(frame._ctx.measure_text, artists, max_w=meta_w, size=11),
              x=px + 64, y=py + 29, size=11, color=SUBTEXT, z=12)
    else:
        # Idle thumb: a quiet neutral tile with a centered note glyph (Spotify's
        # idle idiom), not a saturated hash-colored placeholder square.
        frame.rounded_rect(x=px + 10, y=py + 10, width=44, height=44, radius=8,
                           color=PILL_THUMB_EMPTY, z_index=12)
        _centered_glyph(frame, sl_icons.NOTE, cx=px + 10 + 22, cy=py + 10 + 22,
                        size=20, color=SUBTEXT, z=12, font=sl_icons.ICON_FONT)
        _text(frame, "Nothing playing", x=px + 64, y=py + 15, size=13, color=FAINT, z=12)
        if app.authenticated:
            _text(frame, _fit_width(frame._ctx.measure_text, "Pick a device, or start something from a playlist",
                                    max_w=meta_w, size=11),
                  x=px + 64, y=py + 34, size=11, color=FAINT, z=12)

    # Transport: prev / play / next on the pill's right.
    playing = bool(player and player.is_playing)
    play_cx = px + pw - 72
    _transport_button(frame, out, mouse, sl_icons.PREV, play_cx - 48, py + 18, "prev",
                      SUBTEXT, font=sl_icons.ICON_FONT_FILL)
    play_hover = _hover(mouse, play_cx - 17, py + 15, 34, 34)
    frame.circle(cx=play_cx, cy=cy, radius=15,
                 fill=TEXT if play_hover else (225, 225, 225, 255), z_index=12)
    if playing:
        # Drawn bars: text pipes ("||") space differently per font and read broken.
        bar_w, bar_h, bar_gap = 4.0, 13.0, 5.0
        bar_y = cy - bar_h / 2
        frame.rect(x=play_cx - bar_gap / 2 - bar_w, y=bar_y, width=bar_w, height=bar_h,
                   color=(0, 0, 0, 255), z_index=13)
        frame.rect(x=play_cx + bar_gap / 2, y=bar_y, width=bar_w, height=bar_h,
                   color=(0, 0, 0, 255), z_index=13)
    else:
        _centered_glyph(frame, sl_icons.PLAY, cx=play_cx, cy=cy, size=13,
                        color=(0, 0, 0, 255), z=13, font=sl_icons.ICON_FONT_FILL)
    out.hit(play_cx - 17, py + 15, 34, 34, "toggle_play")
    _transport_button(frame, out, mouse, sl_icons.NEXT, play_cx + 48, py + 18, "next",
                      SUBTEXT, font=sl_icons.ICON_FONT_FILL)

    # Progress strip along the pill's lower interior, with tiny time labels.
    duration = track.duration_ms if track else 0
    progress = app.progress_ms()
    strip_x = px + 92
    strip_w = min(200.0, max(80.0, pw - 240.0))  # narrows with a shrunk pill
    strip_y = py + ph - 13
    if track is not None:
        _text(frame, sl_ui.format_duration_ms(progress), x=px + 64, y=py + ph - 18, size=9,
              color=FAINT, z=12)
        _text(frame, sl_ui.format_duration_ms(duration), x=strip_x + strip_w + 6,
              y=py + ph - 18, size=9, color=FAINT, z=12)
    frame.rounded_rect(x=strip_x, y=strip_y, width=strip_w, height=3, radius=1.5,
                       color=(70, 70, 70, 255), z_index=11)
    frac = sl_ui.seek_fraction(progress, duration)
    if frac > 0:
        frame.rounded_rect(x=strip_x, y=strip_y, width=max(3.0, strip_w * frac), height=3,
                           radius=1.5, color=(220, 220, 220, 255), z_index=12)
    out.hit(strip_x, strip_y - 6, strip_w, 15, "seek_bar", (strip_x, strip_w, duration))

    # Circular Home/Search nav buttons: unchanged on the bottom dock (Alec,
    # round 30), flanking the slot the pill vacated. Each circle's natural
    # rect resolves through the live layout registry (round 31).
    dpx, dpy, dpw, dph = dock_cluster_rect(width, height)
    dock_cy = dpy + dph / 2
    hx, hy, hw, hh = _layout(app, "nav_home",
                             (dpx - NAV_CIRCLE_GAP - 2 * NAV_CIRCLE_R,
                              dock_cy - NAV_CIRCLE_R,
                              2 * NAV_CIRCLE_R, 2 * NAV_CIRCLE_R), width, height)
    sx, sy, sw, sh = _layout(app, "nav_search",
                             (dpx + dpw + NAV_CIRCLE_GAP,
                              dock_cy - NAV_CIRCLE_R,
                              2 * NAV_CIRCLE_R, 2 * NAV_CIRCLE_R), width, height)
    _nav_circle(frame, app, out, mouse, cx=hx + hw / 2, cy=hy + hh / 2,
                view="home", glyph=sl_icons.HOME)
    _nav_circle(frame, app, out, mouse, cx=sx + sw / 2, cy=sy + sh / 2,
                view="search", glyph=sl_icons.SEARCH)

    # Overflow circle (bottom-right): volume / shuffle / repeat / devices.
    ox, oy, ow, oh = _layout(app, "nav_more",
                             (width - PILL_FLOAT - 2 * OVERFLOW_R,
                              dock_cy - OVERFLOW_R,
                              2 * OVERFLOW_R, 2 * OVERFLOW_R), width, height)
    ocx, ocy = ox + ow / 2, oy + oh / 2
    open_hover = _hover(mouse, ox, oy, ow, oh)
    _glass_plate(frame, ox, oy, ow, oh,
                 radius=ow / 2, z=10, hovering=open_hover or app.show_devices)
    _centered_glyph(frame, sl_icons.MORE, cx=ocx, cy=ocy, size=16,
                    color=ACCENT if app.show_devices else (TEXT if open_hover else SUBTEXT),
                    z=12, font=sl_icons.ICON_FONT)
    out.hit(ox, oy, ow, oh, "open_devices")

    if app.show_devices:
        _draw_playback_popup(frame, app, out, width=width, pill_top=dpy, mouse=mouse)


def _nav_circle(frame, app, out: FrameOut, mouse, *, cx: float, cy: float,
                view: str, glyph: str) -> None:
    hovering = _hover(mouse, cx - NAV_CIRCLE_R, cy - NAV_CIRCLE_R,
                      NAV_CIRCLE_R * 2, NAV_CIRCLE_R * 2)
    active = app.view == view
    _glass_plate(frame, cx - NAV_CIRCLE_R, cy - NAV_CIRCLE_R,
                 NAV_CIRCLE_R * 2, NAV_CIRCLE_R * 2, radius=NAV_CIRCLE_R, z=10,
                 hovering=hovering or active)
    color = ACCENT if active else (TEXT if hovering else SUBTEXT)
    _centered_glyph(frame, glyph, cx=cx, cy=cy, size=17, color=color, z=12,
                    font=sl_icons.ICON_FONT)
    out.hit(cx - NAV_CIRCLE_R, cy - NAV_CIRCLE_R, NAV_CIRCLE_R * 2, NAV_CIRCLE_R * 2,
            "nav", view)


def _transport_button(frame, out: FrameOut, mouse, glyph, cx, y, action, color,
                      *, font=FONT_FAMILY) -> None:
    hovering = _hover(mouse, cx - 12, y - 4, 34, 34)
    _centered_glyph(frame, glyph, cx=cx + 5, cy=y + 13, size=16,
                    color=TEXT if hovering else color, z=12, font=font)
    out.hit(cx - 12, y - 4, 34, 34, action)


def _draw_playback_popup(frame, app, out: FrameOut, *, width: float, pill_top: float,
                         mouse) -> None:
    popup_w = 300.0
    row_h = 40.0
    rows = max(1, len(app.devices))
    head_h = 148.0  # pad + volume/shuffle/repeat rows + divider + section title
    popup_h = head_h + row_h * rows + 12
    popup_x = width - popup_w - 16
    popup_y = pill_top - 12 - popup_h
    # Floating panels get the dark variant of the glass plate: mostly-opaque
    # fill for readability over content, same hairline/shadow language.
    _glass_plate(frame, popup_x, popup_y, popup_w, popup_h, radius=14.0, z=20,
                 fill=(18, 18, 18, 234), border=(255, 255, 255, 30))
    # Swallow clicks that land on the panel but on no control: registered
    # first so the popup's own controls (later) win the reversed hit walk,
    # while dead space no longer falls through to dismiss the popup (or bleed
    # into content hits underneath the panel).
    out.hit(popup_x, popup_y, popup_w, popup_h, "popup_plate")

    player = app.player
    y0 = popup_y + 14
    volume = (
        player.device.volume_percent
        if player and player.device and player.device.volume_percent is not None
        else app.last_volume
    )
    _text(frame, "Volume", x=popup_x + 16, y=y0 + 2, size=12, color=SUBTEXT, z=21)
    vol_x, vol_w = popup_x + 96, 180.0
    frame.rounded_rect(x=vol_x, y=y0 + 6, width=vol_w, height=4, radius=2,
                       color=(70, 70, 70, 255), z_index=21)
    if volume > 0:
        frame.rounded_rect(x=vol_x, y=y0 + 6, width=max(4.0, vol_w * volume / 100.0), height=4,
                           radius=2, color=(220, 220, 220, 255), z_index=22)
    out.hit(vol_x, y0 - 2, vol_w, 20, "volume_bar", (vol_x, vol_w))

    shuffle_on = bool(player and player.shuffle)
    repeat = player.repeat if player else "off"
    y1 = y0 + 34
    _popup_toggle_row(frame, out, mouse, popup_x, y1, popup_w, "Shuffle",
                      "On" if shuffle_on else "Off", shuffle_on, "toggle_shuffle")
    y2 = y1 + 34
    repeat_label = {"off": "Off", "context": "All", "track": "One"}.get(repeat, "Off")
    _popup_toggle_row(frame, out, mouse, popup_x, y2, popup_w, "Repeat",
                      repeat_label, repeat != "off", "cycle_repeat")

    frame.rect(x=popup_x + 16, y=y2 + 30, width=popup_w - 32, height=1,
               color=(255, 255, 255, 18), z_index=21)
    _text(frame, "Connect to a device", x=popup_x + 16, y=y2 + 42, size=14, z=21)
    if not app.devices:
        _text(frame, "No devices found.", x=popup_x + 16, y=popup_y + head_h + 8, size=12,
              color=SUBTEXT, z=21)
        _text(frame, "Open Spotify on a device, then pick it here.", x=popup_x + 16,
              y=popup_y + head_h + 26, size=12, color=SUBTEXT, z=21)
    for idx, device in enumerate(app.devices):
        row_y = popup_y + head_h + idx * row_h
        hovering = _hover(mouse, popup_x + 8, row_y, popup_w - 16, row_h)
        if hovering:
            frame.rounded_rect(x=popup_x + 8, y=row_y, width=popup_w - 16, height=row_h - 4,
                               radius=6, color=ROW_HOVER_BG, z_index=20)
        _text(frame, device.name, x=popup_x + 20, y=row_y + 5, size=13,
              color=ACCENT if device.is_active else TEXT, z=21, max_chars=26)
        _text(frame, device.kind, x=popup_x + 20, y=row_y + 22, size=11, color=FAINT, z=21)
        out.hit(popup_x + 8, row_y, popup_w - 16, row_h - 4, "pick_device", device.id)


def _popup_toggle_row(frame, out: FrameOut, mouse, x: float, y: float, w: float,
                      label: str, state: str, on: bool, action: str) -> None:
    hovering = _hover(mouse, x + 8, y - 5, w - 16, 32)
    if hovering:
        frame.rounded_rect(x=x + 8, y=y - 5, width=w - 16, height=30, radius=6,
                           color=ROW_HOVER_BG, z_index=20)
    _text(frame, label, x=x + 16, y=y + 2, size=13, z=21)
    _text(frame, state, x=x + w - 60, y=y + 2, size=12,
          color=ACCENT if on else FAINT, z=21)
    out.hit(x + 8, y - 5, w - 16, 30, action)


# -- login ---------------------------------------------------------------------

LOGIN_FIELD_W = 380.0
LOGIN_FIELD_H = 40.0


def login_field_rect(width: float, height: float) -> tuple[float, float, float, float]:
    """Where the Client ID field lives; shared by the drawn and native versions."""
    cx = width / 2
    return (cx - 190, height * 0.42 + 84, LOGIN_FIELD_W, LOGIN_FIELD_H)


def login_save_button_rect(width: float, height: float) -> tuple[float, float, float, float]:
    """Save button under the Client ID field; drawn and native versions agree."""
    _fx, fy, _fw, _fh = login_field_rect(width, height)
    return (width / 2 - 60, fy + 56, 120.0, 40.0)


def login_connect_button_rect(width: float, height: float) -> tuple[float, float, float, float]:
    """Connect Spotify CTA once a Client ID is saved; drawn and native agree."""
    return (width / 2 - 110, height * 0.42, 220.0, 48.0)


def draw_login(frame, app, out: FrameOut, *, width: float, height: float, mouse,
               native_field_active: bool = False, native_save_active: bool = False,
               native_connect_active: bool = False, embedded_active: bool = False) -> None:
    cx = width / 2
    _text(frame, "Spotify Light", x=cx - 90, y=height * 0.24, size=32, color=ACCENT, z=3)
    _text(frame, "A lightweight Spotify desktop client, native on luvatrix.",
          x=cx - 210, y=height * 0.24 + 48, size=14, color=SUBTEXT, z=3)

    y = height * 0.42
    if app.auth_error:
        _text(frame, app.auth_error, x=cx - 190, y=y - 32, size=13, color=DANGER, z=3,
              max_chars=64)
    if app.auth_working:
        if embedded_active:
            # The native web view owns the screen; a native Cancel button floats above it.
            return
        _text(frame, "Waiting for sign-in in your browser…", x=cx - 150, y=y, size=15, z=3)
        hovering = _hover(mouse, cx - 60, y + 44, 120, 40)
        frame.rounded_rect(x=cx - 60, y=y + 44, width=120, height=40, radius=20,
                           color=CARD_HOVER_BG if hovering else CARD_BG, z_index=2)
        _text(frame, "Cancel", x=cx - 26, y=y + 55, size=14, z=3)
        out.hit(cx - 60, y + 44, 120, 40, "cancel_login")
        return

    if not app.client_id:
        lines = [
            "1. Create an app at developer.spotify.com/dashboard",
            "2. Add redirect URI: http://127.0.0.1:8888/callback",
            "3. Paste your Client ID below",
        ]
        for i, line in enumerate(lines):
            _text(frame, line, x=cx - 190, y=y + i * 24, size=13, color=SUBTEXT, z=3)
        field_x, field_y, field_w, field_h = login_field_rect(width, height)
        if native_field_active:
            # Lift the native glass capsule off the near-black backdrop.
            frame.rounded_rect(x=field_x, y=field_y, width=field_w, height=field_h,
                               radius=20, color=GLASS_TINT, z_index=2)
        else:
            border = ACCENT if app.client_id_focused else FIELD_BORDER
            frame.rounded_rect(x=field_x, y=field_y, width=field_w, height=field_h, radius=8,
                               color=FIELD_BG, z_index=2)
            frame.rect(x=field_x, y=field_y, width=field_w, height=1.5, color=border, z_index=3)
            frame.rect(x=field_x, y=field_y + field_h - 1, width=field_w, height=1.5,
                       color=border, z_index=3)
            shown = app.client_id_draft or "Client ID"
            _text(frame, shown, x=field_x + 14, y=field_y + 12, size=13,
                  color=TEXT if app.client_id_draft else FAINT, z=4, max_chars=44)
            out.hit(field_x, field_y, field_w, field_h, "focus_client_id")
        save_x, save_y, save_w, save_h = login_save_button_rect(width, height)
        if native_save_active:
            frame.rounded_rect(x=save_x, y=save_y, width=save_w, height=save_h,
                               radius=20, color=GLASS_TINT, z_index=2)
        else:
            enabled = bool(app.client_id_draft.strip())
            hovering = _hover(mouse, save_x, save_y, save_w, save_h)
            frame.rounded_rect(x=save_x, y=save_y, width=save_w, height=save_h, radius=20,
                               color=(ACCENT if hovering else ACCENT_DARK) if enabled else CARD_BG,
                               z_index=2)
            _text(frame, "Save", x=cx - 24, y=save_y + 11, size=14,
                  color=(0, 0, 0, 255) if enabled else FAINT, z=3)
            if enabled:
                out.hit(save_x, save_y, save_w, save_h, "save_client_id")
        return

    con_x, con_y, con_w, con_h = login_connect_button_rect(width, height)
    if native_connect_active:
        frame.rounded_rect(x=con_x, y=con_y, width=con_w, height=con_h,
                           radius=24, color=GLASS_TINT, z_index=2)
    else:
        hovering = _hover(mouse, con_x, con_y, con_w, con_h)
        frame.rounded_rect(x=con_x, y=con_y, width=con_w, height=con_h, radius=24,
                           color=ACCENT if hovering else ACCENT_DARK, z_index=2)
        _text(frame, "Connect Spotify", x=cx - 68, y=con_y + 15, size=15,
              color=(0, 0, 0, 255), z=3)
        out.hit(con_x, con_y, con_w, con_h, "start_login")
    _text(frame, "Playback uses Spotify Connect: audio plays on a device you pick.",
          x=cx - 220, y=y + 72, size=12, color=FAINT, z=3)
    _text(frame, "Playback control requires Spotify Premium.",
          x=cx - 140, y=y + 92, size=12, color=FAINT, z=3)
