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

import sl_models
import sl_ui

# -- layout ------------------------------------------------------------------
SIDEBAR_W = 240.0
PLAYER_H = 96.0
CONTENT_PAD = 28.0
CARD_W = 180.0
CARD_H = 236.0
CARD_GAP = 24.0
CARD_ART = 180.0
ROW_H = 48.0
NAV_H = 44.0

# -- theme (Spotify desktop palette) ------------------------------------------
BG = (18, 18, 18, 255)
SIDEBAR_BG = (9, 9, 9, 255)
CARD_BG = (26, 26, 26, 255)
CARD_HOVER_BG = (42, 42, 42, 255)
ROW_HOVER_BG = (30, 30, 30, 255)
BAR_BG = (24, 24, 24, 255)
TEXT = (255, 255, 255, 255)
SUBTEXT = (179, 179, 179, 255)
FAINT = (120, 120, 120, 255)
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


def _text(frame, text, *, x, y, size=14.0, color=TEXT, z=2, max_chars=0) -> None:
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
        cache_key=_ck("t", shown, size, color),
    )


def _art(frame, app, image_url, *, x, y, size, seed, z=2) -> None:
    """Draw album art from the cache, or a placeholder while the fetch lands."""
    rgba = app.art_for(image_url, int(size)) if image_url else None
    if rgba is None:
        rgba = app.art_cache.placeholder(seed, int(size))
    # SceneFrame exposes no image primitive; CpuLayerNode carries the pixels.
    frame._ctx.add_scene_node(
        CpuLayerNode(x=float(x), y=float(y), width=float(size), height=float(size), rgba=rgba, z_index=z)
    )


def _hover(mouse, x, y, w, h) -> bool:
    mx, my = mouse
    return x <= mx <= x + w and y <= my <= y + h


def _daypart() -> str:
    import datetime

    hour = datetime.datetime.now().hour
    if hour < 12:
        return "morning"
    if hour < 18:
        return "afternoon"
    return "evening"


# -- sidebar -------------------------------------------------------------------


def draw_sidebar(frame, app, out: FrameOut, *, width: float, height: float, mouse) -> None:
    frame.rect(x=0, y=0, width=SIDEBAR_W, height=height, color=SIDEBAR_BG, z_index=1)
    _text(frame, "Spotify Light", x=22, y=20, size=20, color=ACCENT, z=3)

    nav = [("home", "Home"), ("search", "Search"), ("library", "Your Library")]
    y = 64.0
    for view, label in nav:
        active = app.view == view
        hovering = _hover(mouse, 10, y - 6, SIDEBAR_W - 20, NAV_H - 8)
        if active:
            frame.rounded_rect(x=10, y=y - 6, width=SIDEBAR_W - 20, height=NAV_H - 8, radius=6.0,
                               color=CARD_BG, z_index=2)
        color = TEXT if (active or hovering) else SUBTEXT
        _text(frame, label, x=22, y=y + 2, size=15, color=color, z=3)
        out.hit(10, y - 6, SIDEBAR_W - 20, NAV_H - 8, "nav", view)
        y += NAV_H

    y += 10
    _text(frame, "PLAYLISTS", x=22, y=y, size=11, color=FAINT, z=3)
    y += 24

    list_top = y
    list_bottom = height - PLAYER_H - 64
    row_h = 30.0
    offset = app.sidebar_scroll
    for idx, playlist in enumerate(app.playlists):
        row_y = list_top + row_h * idx - offset
        if row_y + row_h < list_top or row_y > list_bottom:
            continue
        hovering = _hover(mouse, 10, row_y, SIDEBAR_W - 20, row_h - 4)
        if hovering:
            frame.rounded_rect(x=10, y=row_y, width=SIDEBAR_W - 20, height=row_h - 4,
                               radius=4.0, color=ROW_HOVER_BG, z_index=2)
        _text(frame, playlist.name, x=22, y=row_y + 4, size=13,
              color=TEXT if hovering else SUBTEXT, z=3, max_chars=26)
        out.hit(10, row_y, SIDEBAR_W - 20, row_h - 4, "open_playlist", playlist.id)
    _draw_scrollbar(frame, app.scrollbar_sidebar, out, x=SIDEBAR_W - 6, top=list_top,
                    bottom=list_bottom, content=row_h * len(app.playlists), offset=offset,
                    tag="sidebar")

    chip_y = height - PLAYER_H - 52
    frame.rect(x=0, y=chip_y - 8, width=SIDEBAR_W, height=1, color=(40, 40, 40, 255), z_index=2)
    name = app.profile.display_name if app.profile and app.profile.display_name else "Account"
    _text(frame, name, x=22, y=chip_y + 4, size=13, color=SUBTEXT, z=3, max_chars=16)
    hovering = _hover(mouse, 150, chip_y, 70, 26)
    _text(frame, "Log out", x=156, y=chip_y + 4, size=13, color=TEXT if hovering else FAINT, z=3)
    out.hit(150, chip_y - 2, 74, 28, "logout")


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
    frame.rounded_rect(x=x, y=y, width=CARD_W, height=CARD_H, radius=10.0,
                       color=CARD_HOVER_BG if hovering else CARD_BG, z_index=2)
    _art(frame, app, card.image_url, x=x + 12, y=y + 12, size=CARD_ART - 24, seed=card.title)
    _text(frame, card.title, x=x + 12, y=y + CARD_ART + 8, size=14, z=3, max_chars=22)
    _text(frame, card.subtitle, x=x + 12, y=y + CARD_ART + 28, size=12, color=SUBTEXT, z=3,
          max_chars=26)
    if card.kind in ("playlist", "album"):
        out.hit(x, y, CARD_W, CARD_H, "open_card", card)
    elif card.kind == "track":
        out.hit(x, y, CARD_W, CARD_H, "play_card", card)
    if hovering and card.context_uri:
        frame.circle(cx=x + CARD_W - 28, cy=y + CARD_ART - 16, radius=20, fill=ACCENT, z_index=3)
        _text(frame, ">", x=x + CARD_W - 35, y=y + CARD_ART - 27, size=18, color=(0, 0, 0, 255), z=4)


def _draw_track_table(frame, app, out: FrameOut, rows, *, x0, y0, width, height, context_uri, mouse) -> float:
    table_w = width - SIDEBAR_W - CONTENT_PAD * 2
    for row in rows:
        row_y = y0 + (row.index - 1) * ROW_H
        if row_y + ROW_H < 0 or row_y > height - PLAYER_H:
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

    if not app.home_sections:
        _text(frame, "Loading your music…", x=x0, y=y, size=15, color=SUBTEXT, z=3)
        y += 30

    cols = sl_ui.grid_columns(view_w, card_width=CARD_W, gap=CARD_GAP)
    for section in app.home_sections:
        _text(frame, section.title, x=x0, y=y, size=19, z=3)
        y += 32
        rows = math.ceil(len(section.cards) / cols)
        for idx, card in enumerate(section.cards):
            row, col = divmod(idx, cols)
            cx = x0 + col * (CARD_W + CARD_GAP)
            cy = y + row * (CARD_H + CARD_GAP)
            if cy + CARD_H > 0 and cy < height - PLAYER_H:
                _draw_card(frame, app, out, card, x=cx, y=cy, mouse=mouse)
        y += rows * (CARD_H + CARD_GAP) + 12

    out.content_height = y + app.content_scroll


# -- playlist detail -------------------------------------------------------------


def draw_playlist(frame, app, out: FrameOut, *, width: float, height: float, mouse) -> None:
    x0 = SIDEBAR_W + CONTENT_PAD
    y = 24.0 - app.content_scroll
    detail = app.playlist_detail
    if detail is None:
        _text(frame, "Loading playlist…", x=x0, y=y, size=16, color=SUBTEXT, z=3)
        return

    playlist, tracks = detail
    _art(frame, app, sl_models.pick_image_url(playlist.images, 300), x=x0, y=y, size=160,
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
    frame.rounded_rect(x=play_x, y=play_y, width=120, height=40, radius=20,
                       color=ACCENT if hovering else ACCENT_DARK, z_index=2)
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

    field_w = min(460.0, view_w)
    border = ACCENT if app.search_focused else FIELD_BORDER
    frame.rounded_rect(x=x0, y=y, width=field_w, height=40, radius=20, color=FIELD_BG, z_index=2)
    frame.rect(x=x0, y=y, width=field_w, height=1.5, color=border, z_index=3)
    frame.rect(x=x0, y=y + 39, width=field_w, height=1.5, color=border, z_index=3)
    shown = app.search_query or ("What do you want to listen to?" if not app.search_focused else "")
    _text(frame, shown, x=x0 + 18, y=y + 12, size=14,
          color=TEXT if app.search_query else FAINT, z=4, max_chars=52)
    if app.search_focused and int(app.now_monotonic * 2) % 2 == 0:
        caret_x = x0 + 18 + len(app.search_query) * 14 * 0.52
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
        ("Albums", [sl_ui.album_card(a) for a in results.albums]),
        ("Artists", [sl_ui.artist_card(a) for a in results.artists]),
        ("Playlists", [sl_ui.playlist_card(p) for p in results.playlists]),
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
            if cy + CARD_H > 0 and cy < height - PLAYER_H:
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
    cards = [sl_ui.playlist_card(p) for p in app.playlists]
    if not cards:
        _text(frame, "Playlists you create or follow will show up here.", x=x0, y=y, size=14,
              color=SUBTEXT, z=3)
        return
    rows = math.ceil(len(cards) / cols)
    for idx, card in enumerate(cards):
        row, col = divmod(idx, cols)
        cx = x0 + col * (CARD_W + CARD_GAP)
        cy = y + row * (CARD_H + CARD_GAP)
        if cy + CARD_H > 0 and cy < height - PLAYER_H:
            _draw_card(frame, app, out, card, x=cx, y=cy, mouse=mouse)
    out.content_height = y + rows * (CARD_H + CARD_GAP) + app.content_scroll


# -- now playing bar ---------------------------------------------------------------


def draw_player_bar(frame, app, out: FrameOut, *, width: float, height: float, mouse) -> None:
    bar_y = height - PLAYER_H
    frame.rect(x=0, y=bar_y, width=width, height=PLAYER_H, color=BAR_BG, z_index=10)
    frame.rect(x=0, y=bar_y, width=width, height=1, color=(45, 45, 45, 255), z_index=10)

    player = app.player
    track = player.track if player else None

    if track is not None:
        image_url = sl_models.pick_image_url(track.album.images if track.album else (), 128)
        _art(frame, app, image_url, x=16, y=bar_y + 16, size=64, seed=track.name, z=11)
        _text(frame, track.name, x=92, y=bar_y + 22, size=14, z=12, max_chars=30)
        artists = ", ".join(a.name for a in track.artists if a.name)
        _text(frame, artists, x=92, y=bar_y + 44, size=12, color=SUBTEXT, z=12, max_chars=36)
    else:
        _text(frame, "Nothing playing", x=92, y=bar_y + 34, size=13, color=FAINT, z=12)
        if app.authenticated:
            _text(frame, "Pick a device, or start something from a playlist", x=92, y=bar_y + 54,
                  size=11, color=FAINT, z=12)

    cx = width / 2
    btn_y = bar_y + 14
    playing = bool(player and player.is_playing)
    shuffle_on = bool(player and player.shuffle)
    repeat = player.repeat if player else "off"

    _transport_button(frame, out, mouse, "S", cx - 120, btn_y, "toggle_shuffle",
                      ACCENT if shuffle_on else SUBTEXT)
    _transport_button(frame, out, mouse, "<<", cx - 76, btn_y, "prev", SUBTEXT)
    play_hover = _hover(mouse, cx - 33, btn_y - 3, 34, 34)
    frame.circle(cx=cx - 16, cy=btn_y + 14, radius=17,
                 fill=TEXT if play_hover else (225, 225, 225, 255), z_index=12)
    _text(frame, "||" if playing else ">", x=cx - 25, y=btn_y + 5, size=15, color=(0, 0, 0, 255), z=13)
    out.hit(cx - 33, btn_y - 3, 34, 34, "toggle_play")
    _transport_button(frame, out, mouse, ">>", cx + 24, btn_y, "next", SUBTEXT)
    _transport_button(frame, out, mouse, "R1" if repeat == "track" else "R", cx + 68, btn_y,
                      "cycle_repeat", ACCENT if repeat != "off" else SUBTEXT)

    duration = track.duration_ms if track else 0
    progress = app.progress_ms()
    seek_w = min(420.0, width * 0.36)
    seek_x = cx - seek_w / 2 - 16
    seek_y = bar_y + 62
    _text(frame, sl_ui.format_duration_ms(progress), x=seek_x - 46, y=seek_y - 5, size=11,
          color=FAINT, z=12)
    frame.rounded_rect(x=seek_x, y=seek_y, width=seek_w, height=4, radius=2, color=(70, 70, 70, 255),
                       z_index=11)
    frac = sl_ui.seek_fraction(progress, duration)
    if frac > 0:
        frame.rounded_rect(x=seek_x, y=seek_y, width=max(4.0, seek_w * frac), height=4, radius=2,
                           color=(220, 220, 220, 255), z_index=12)
    _text(frame, sl_ui.format_duration_ms(duration), x=seek_x + seek_w + 10, y=seek_y - 5, size=11,
          color=FAINT, z=12)
    out.hit(seek_x, seek_y - 7, seek_w, 18, "seek_bar", (seek_x, seek_w, duration))

    vol_w = 100.0
    vol_x = width - vol_w - 24
    vol_y = bar_y + 46
    device_label = player.device.name if player and player.device else "Devices"
    hovering = _hover(mouse, vol_x - 130, bar_y + 30, 120, 32)
    _text(frame, device_label, x=vol_x - 130, y=bar_y + 40, size=12,
          color=TEXT if hovering else SUBTEXT, z=12, max_chars=16)
    out.hit(vol_x - 130, bar_y + 30, 120, 32, "open_devices")
    volume = (
        player.device.volume_percent
        if player and player.device and player.device.volume_percent is not None
        else app.last_volume
    )
    frame.rounded_rect(x=vol_x, y=vol_y, width=vol_w, height=4, radius=2, color=(70, 70, 70, 255),
                       z_index=11)
    if volume > 0:
        frame.rounded_rect(x=vol_x, y=vol_y, width=max(4.0, vol_w * volume / 100.0), height=4,
                           radius=2, color=(220, 220, 220, 255), z_index=12)
    out.hit(vol_x, vol_y - 8, vol_w, 20, "volume_bar", (vol_x, vol_w))

    if app.show_devices:
        _draw_device_popup(frame, app, out, width=width, bar_y=bar_y, mouse=mouse)


def _transport_button(frame, out: FrameOut, mouse, glyph, cx, y, action, color) -> None:
    hovering = _hover(mouse, cx - 12, y - 4, 34, 34)
    _text(frame, glyph, x=cx - 8, y=y + 5, size=16, color=TEXT if hovering else color, z=12)
    out.hit(cx - 12, y - 4, 34, 34, action)


def _draw_device_popup(frame, app, out: FrameOut, *, width: float, bar_y: float, mouse) -> None:
    popup_w = 300.0
    row_h = 40.0
    rows = max(1, len(app.devices))
    popup_h = 52 + row_h * rows + 12
    popup_x = width - popup_w - 16
    popup_y = bar_y - popup_h - 12
    frame.rounded_rect(x=popup_x, y=popup_y, width=popup_w, height=popup_h, radius=10,
                       color=POPUP_BG, z_index=20)
    _text(frame, "Connect to a device", x=popup_x + 16, y=popup_y + 14, size=14, z=21)
    if not app.devices:
        _text(frame, "No devices found.", x=popup_x + 16, y=popup_y + 44, size=12, color=SUBTEXT, z=21)
        _text(frame, "Open Spotify on a device, then pick it here.", x=popup_x + 16,
              y=popup_y + 62, size=12, color=SUBTEXT, z=21)
    for idx, device in enumerate(app.devices):
        row_y = popup_y + 44 + idx * row_h
        hovering = _hover(mouse, popup_x + 8, row_y, popup_w - 16, row_h)
        if hovering:
            frame.rounded_rect(x=popup_x + 8, y=row_y, width=popup_w - 16, height=row_h - 4,
                               radius=6, color=ROW_HOVER_BG, z_index=20)
        _text(frame, device.name, x=popup_x + 20, y=row_y + 5, size=13,
              color=ACCENT if device.is_active else TEXT, z=21, max_chars=26)
        _text(frame, device.kind, x=popup_x + 20, y=row_y + 22, size=11, color=FAINT, z=21)
        out.hit(popup_x + 8, row_y, popup_w - 16, row_h - 4, "pick_device", device.id)


# -- login ---------------------------------------------------------------------

LOGIN_FIELD_W = 380.0
LOGIN_FIELD_H = 40.0


def login_field_rect(width: float, height: float) -> tuple[float, float, float, float]:
    """Where the Client ID field lives; shared by the drawn and native versions."""
    cx = width / 2
    return (cx - 190, height * 0.42 + 84, LOGIN_FIELD_W, LOGIN_FIELD_H)


def draw_login(frame, app, out: FrameOut, *, width: float, height: float, mouse,
               native_field_active: bool = False) -> None:
    cx = width / 2
    _text(frame, "Spotify Light", x=cx - 90, y=height * 0.24, size=32, color=ACCENT, z=3)
    _text(frame, "A lightweight Spotify desktop client, native on luvatrix.",
          x=cx - 210, y=height * 0.24 + 48, size=14, color=SUBTEXT, z=3)

    y = height * 0.42
    if app.auth_error:
        _text(frame, app.auth_error, x=cx - 190, y=y - 32, size=13, color=DANGER, z=3,
              max_chars=64)
    if app.auth_working:
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
        if not native_field_active:
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
        save_y = field_y + 56
        enabled = bool(app.client_id_draft.strip())
        hovering = _hover(mouse, cx - 60, save_y, 120, 40)
        frame.rounded_rect(x=cx - 60, y=save_y, width=120, height=40, radius=20,
                           color=(ACCENT if hovering else ACCENT_DARK) if enabled else CARD_BG,
                           z_index=2)
        _text(frame, "Save", x=cx - 24, y=save_y + 11, size=14,
              color=(0, 0, 0, 255) if enabled else FAINT, z=3)
        if enabled:
            out.hit(cx - 60, save_y, 120, 40, "save_client_id")
        return

    hovering = _hover(mouse, cx - 110, y, 220, 48)
    frame.rounded_rect(x=cx - 110, y=y, width=220, height=48, radius=24,
                       color=ACCENT if hovering else ACCENT_DARK, z_index=2)
    _text(frame, "Connect Spotify", x=cx - 68, y=y + 15, size=15, color=(0, 0, 0, 255), z=3)
    out.hit(cx - 110, y, 220, 48, "start_login")
    _text(frame, "Playback uses Spotify Connect: audio plays on a device you pick.",
          x=cx - 220, y=y + 72, size=12, color=FAINT, z=3)
    _text(frame, "Playback control requires Spotify Premium.",
          x=cx - 140, y=y + 92, size=12, color=FAINT, z=3)
