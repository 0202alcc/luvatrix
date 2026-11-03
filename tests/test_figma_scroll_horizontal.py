from __future__ import annotations

import numpy as np

from luvatrix_core.core.hdi_thread import HDIEvent
from luvatrix_ui.figma import FigmaApp, FigmaDocument, render_frame

from figma_fixtures import horizontal_file
from test_figma_app import _FakeCtx, _tap, _touch


RED = (255, 0, 0, 255)
GREEN = (0, 255, 0, 255)
BLUE = (0, 0, 255, 255)
YELLOW = (255, 255, 0, 255)
WHITE = (255, 255, 255, 255)


def _app() -> tuple[_FakeCtx, FigmaApp]:
    ctx = _FakeCtx(100, 200)
    app = FigmaApp(FigmaDocument.from_dict(horizontal_file()))
    app.init(ctx)
    app.loop(ctx, 0.016)
    return ctx, app


def _drag_x(ctx: _FakeCtx, y: float, x0: float, x1: float) -> None:
    ctx.queue(
        _touch("down", x0, y),
        _touch("move", (x0 + x1) / 2, y),
        _touch("move", x1, y),
        _touch("up", x1, y),
    )


def _px(frame: np.ndarray, x: int, y: int) -> tuple[int, ...]:
    return tuple(int(v) for v in frame[y, x])


def test_document_reports_horizontal_scrolling() -> None:
    doc = FigmaDocument.from_dict(horizontal_file())

    assert doc.frame("4:1").scrolls_horizontally
    assert not doc.frame("4:1").scrolls_vertically
    assert doc.fixed_child_ids("4:1") == {"4:9"}


def test_horizontal_frame_fills_height_and_shows_the_left_edge() -> None:
    ctx, app = _app()

    frame = ctx.frames[-1]
    assert frame.shape == (200, 100, 4)
    assert _px(frame, 25, 10) == RED
    assert _px(frame, 75, 10) == RED
    assert _px(frame, 25, 100) == YELLOW


def test_dragging_scrolls_horizontally_but_keeps_fixed_children_pinned() -> None:
    ctx, app = _app()

    _drag_x(ctx, 100, 250, 50)
    app.loop(ctx, 0.016)

    assert app.scroll_x == 100
    frame = ctx.frames[-1]
    assert _px(frame, 25, 10) == GREEN
    assert _px(frame, 25, 100) == YELLOW


def test_horizontal_scroll_is_clamped_to_the_content() -> None:
    ctx, app = _app()

    _drag_x(ctx, 100, 250, 50)
    _drag_x(ctx, 100, 250, 50)
    _drag_x(ctx, 100, 250, 50)
    app.loop(ctx, 0.016)
    assert app.scroll_x == 300

    _drag_x(ctx, 100, 50, 250)
    _drag_x(ctx, 100, 50, 250)
    app.loop(ctx, 0.016)
    assert app.scroll_x == 0


def test_horizontal_wheel_scrolls() -> None:
    ctx, app = _app()

    ctx.queue(HDIEvent(1, 1, "w", "mouse", "scroll", "OK", {"x": 50, "y": 50, "delta_x": -40, "delta_y": 0}))
    app.loop(ctx, 0.016)

    assert app.scroll_x == 20


def test_taps_hit_scrolled_horizontal_content() -> None:
    ctx, app = _app()
    _drag_x(ctx, 100, 250, 50)
    app.loop(ctx, 0.016)

    _tap(ctx, 25, 10)
    app.loop(ctx, 0.016)

    assert app.current_frame_id == "5:1"


def test_renderer_can_split_horizontal_fixed_and_scrolling_layers() -> None:
    doc = FigmaDocument.from_dict(horizontal_file())

    content = render_frame(doc, "4:1", skip_ids={"4:9"})
    overlay = render_frame(doc, "4:1", only_ids={"4:9"}, transparent=True)

    assert _px(content, 220, 100) == GREEN
    assert _px(overlay, 60, 100) == YELLOW
    assert overlay[10, 60, 3] == 0


def test_navigation_resets_horizontal_scroll_and_back_restores_it() -> None:
    ctx, app = _app()
    _drag_x(ctx, 100, 250, 50)
    app.loop(ctx, 0.016)

    _tap(ctx, 25, 10)
    app.loop(ctx, 0.016)
    assert app.scroll_x == 0

    app.back()
    app.loop(ctx, 0.016)
    assert app.current_frame_id == "4:1"
    assert app.scroll_x == 100
