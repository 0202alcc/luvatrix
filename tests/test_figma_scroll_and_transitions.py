from __future__ import annotations

import numpy as np

from luvatrix_core.core.hdi_thread import HDIEvent
from luvatrix_ui.figma import FigmaApp, FigmaDocument, render_frame

from figma_fixtures import scrolling_file
from test_figma_app import _FakeCtx, _tap, _touch

RED = (255, 0, 0, 255)
GREEN = (0, 255, 0, 255)
BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)
BLUE = (0, 0, 255, 255)


def _app(ctx: _FakeCtx, transition=None) -> FigmaApp:
    app = FigmaApp(FigmaDocument.from_dict(scrolling_file(transition)))
    app.init(ctx)
    app.loop(ctx, 0.016)
    return app


def _drag(ctx: _FakeCtx, x: float, y0: float, y1: float) -> None:
    ctx.queue(_touch("down", x, y0), _touch("move", x, (y0 + y1) / 2), _touch("move", x, y1), _touch("up", x, y1))


def _px(frame: np.ndarray, x: int, y: int) -> tuple[int, ...]:
    return tuple(int(v) for v in frame[y, x])


def test_document_reports_scrolling_and_fixed_children() -> None:
    doc = FigmaDocument.from_dict(scrolling_file())
    feed = doc.frame("4:1")

    assert feed.scrolls_vertically
    assert doc.fixed_child_ids("4:1") == {"4:4"}
    assert not doc.frame("5:1").scrolls_vertically


def test_renderer_can_split_fixed_and_scrolling_layers() -> None:
    doc = FigmaDocument.from_dict(scrolling_file())

    content = render_frame(doc, "4:1", skip_ids={"4:4"})
    overlay = render_frame(doc, "4:1", only_ids={"4:4"}, transparent=True)

    assert _px(content, 50, 190) == WHITE
    assert _px(overlay, 50, 190) == BLACK
    assert overlay[50, 50, 3] == 0


def test_tall_scrolling_frame_fits_width_and_shows_the_top() -> None:
    ctx = _FakeCtx(100, 200)
    _app(ctx)

    frame = ctx.frames[-1]
    assert frame.shape == (200, 100, 4)
    assert _px(frame, 50, 50) == RED
    assert _px(frame, 50, 190) == BLACK


def test_dragging_scrolls_content_but_keeps_fixed_children_pinned() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)

    _drag(ctx, 50, 150, 50)
    app.loop(ctx, 0.016)

    assert app.scroll_y == 100
    frame = ctx.frames[-1]
    assert _px(frame, 50, 160) == GREEN
    assert _px(frame, 50, 50) == WHITE
    assert _px(frame, 50, 190) == BLACK


def test_scroll_is_clamped_to_the_content() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)

    _drag(ctx, 50, 190, 0)
    _drag(ctx, 50, 190, 0)
    app.loop(ctx, 0.016)
    assert app.scroll_y == 200

    _drag(ctx, 50, 0, 190)
    _drag(ctx, 50, 0, 190)
    app.loop(ctx, 0.016)
    assert app.scroll_y == 0


def test_a_drag_is_not_a_tap() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)
    _drag(ctx, 50, 150, 50)
    app.loop(ctx, 0.016)

    _drag(ctx, 50, 160, 150)
    app.loop(ctx, 0.016)

    assert app.current_frame_id == "4:1"


def test_taps_hit_scrolled_content_at_its_scrolled_position() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)
    _drag(ctx, 50, 150, 50)
    app.loop(ctx, 0.016)

    _tap(ctx, 50, 160)
    app.loop(ctx, 0.016)

    assert app.current_frame_id == "5:1"


def test_fixed_children_hide_scrolled_content_from_taps() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)
    _drag(ctx, 50, 190, 120)
    app.loop(ctx, 0.016)

    _tap(ctx, 50, 190)
    app.loop(ctx, 0.016)

    assert app.current_frame_id == "4:1"


def test_mouse_wheel_scrolls() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)

    ctx.queue(HDIEvent(1, 1, "w", "mouse", "scroll", "OK", {"x": 50, "y": 50, "delta_x": 0, "delta_y": -40}))
    app.loop(ctx, 0.016)

    assert app.scroll_y == 40


def test_navigation_resets_scroll_and_back_restores_it() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)
    _drag(ctx, 50, 150, 50)
    app.loop(ctx, 0.016)

    _tap(ctx, 50, 160)
    app.loop(ctx, 0.016)
    assert app.scroll_y == 0

    app.back()
    app.loop(ctx, 0.016)
    assert app.current_frame_id == "4:1"
    assert app.scroll_y == 100


def test_dissolve_transition_crossfades_then_settles() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx, transition={"type": "DISSOLVE", "duration": 0.2, "easing": {"type": "LINEAR"}})
    _drag(ctx, 50, 150, 50)
    app.loop(ctx, 0.016)

    _tap(ctx, 50, 160)
    app.loop(ctx, 0.1)
    mid = _px(ctx.frames[-1], 50, 50)
    assert 60 < mid[0] < 200

    app.loop(ctx, 0.1)
    app.loop(ctx, 0.1)
    assert _px(ctx.frames[-1], 50, 50) == BLUE
    settled = len(ctx.frames)
    app.loop(ctx, 0.1)
    assert len(ctx.frames) == settled


def test_push_transition_slides_the_destination_in_from_the_right() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx, transition={"type": "PUSH", "direction": "LEFT", "duration": 0.2, "easing": {"type": "LINEAR"}})
    _drag(ctx, 50, 150, 50)
    app.loop(ctx, 0.016)

    _tap(ctx, 50, 160)
    app.loop(ctx, 0.1)

    frame = ctx.frames[-1]
    assert _px(frame, 75, 100) == BLUE
    assert _px(frame, 25, 100) != BLUE
