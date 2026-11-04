from __future__ import annotations

import numpy as np

from luvatrix_ui.figma import FigmaApp, FigmaDocument, OverlayAction

from figma_fixtures import overlay_file
from test_figma_app import _FakeCtx, _tap, _touch


RED = (255, 0, 0, 255)
GREEN = (0, 255, 0, 255)
BLUE = (0, 0, 255, 255)
YELLOW = (255, 255, 0, 255)
WHITE = (255, 255, 255, 255)


def _app(interaction: str | None = None) -> tuple[_FakeCtx, FigmaApp]:
    ctx = _FakeCtx(100, 200)
    app = FigmaApp(FigmaDocument.from_dict(overlay_file(interaction=interaction)))
    app.init(ctx)
    app.loop(ctx, 0.016)
    return ctx, app


def _px(frame: np.ndarray, x: int, y: int) -> tuple[int, ...]:
    return tuple(int(v) for v in frame[y, x])


def test_document_parses_overlay_actions_from_the_destination_frame() -> None:
    doc = FigmaDocument.from_dict(overlay_file())
    actions = {spot.node_name: spot.action for spot in doc.hotspots("1:1")}

    assert actions["Open Sheet"] == OverlayAction("3:1")


def test_document_reads_overlay_settings_from_the_destination_frame() -> None:
    doc = FigmaDocument.from_dict(overlay_file(interaction="CLOSE_ON_CLICK_OUTSIDE"))
    actions = {spot.node_name: spot.action for spot in doc.hotspots("1:1")}

    assert actions["Open Sheet"] == OverlayAction("3:1", position="CENTER", background=(0.0, 0.0, 0.0, 0.5), dismiss_on_click_outside=True)


def test_opening_an_overlay_composites_it_over_the_current_frame() -> None:
    ctx, app = _app()

    app.tap("Open Sheet")
    app.loop(ctx, 0.016)

    assert app.current_frame_id == "1:1"
    assert app.overlay_frame_name == "Sheet"
    frame = ctx.frames[-1]
    assert _px(frame, 50, 55) == YELLOW
    assert _px(frame, 50, 90) == BLUE
    assert _px(frame, 50, 150) == BLUE
    assert _px(frame, 50, 180) == (153, 153, 153, 255)
    assert _px(frame, 50, 10) == (0, 153, 0, 255)


def test_back_on_an_overlay_closes_it_and_preserves_the_base_scroll() -> None:
    ctx, app = _app()
    ctx.queue(_touch("down", 50, 150), _touch("move", 50, 100), _touch("move", 50, 50), _touch("up", 50, 50))
    app.loop(ctx, 0.016)
    assert app.scroll_y == 100

    app.tap("Open Sheet")
    app.loop(ctx, 0.016)
    app.tap("Close")
    app.loop(ctx, 0.016)

    assert app.current_frame_id == "1:1"
    assert app.overlay_frame_name is None
    assert app.scroll_y == 100
    frame = ctx.frames[-1]
    assert _px(frame, 50, 60) == RED
    assert _px(frame, 50, 5) == WHITE
    assert _px(frame, 50, 190) == WHITE


def test_base_taps_are_blocked_while_an_overlay_is_open() -> None:
    ctx, app = _app()

    app.tap("Open Sheet")
    app.loop(ctx, 0.016)
    _tap(ctx, 50, 25)
    app.loop(ctx, 0.016)

    assert app.current_frame_id == "1:1"
    assert app.overlay_frame_name == "Sheet"


def test_dragging_scrolls_the_overlay_not_the_base_frame() -> None:
    ctx, app = _app()
    overlay_file_scroll = overlay_file(sheet_height=300)
    app2 = FigmaApp(FigmaDocument.from_dict(overlay_file_scroll))
    app2.init(ctx)
    app2.loop(ctx, 0.016)

    app2.tap("Open Sheet")
    app2.loop(ctx, 0.016)
    ctx.queue(_touch("down", 50, 150), _touch("move", 50, 90), _touch("move", 50, 50), _touch("up", 50, 50))
    app2.loop(ctx, 0.016)

    assert app2.current_frame_id == "1:1"
    assert app2.overlay_frame_name == "Sheet"
    assert app2.scroll_y == 0
    assert app2.overlay_scroll_y == 100


def test_click_outside_closes_when_the_overlay_allows_it() -> None:
    ctx, app = _app(interaction="CLOSE_ON_CLICK_OUTSIDE")

    app.tap("Open Sheet")
    app.loop(ctx, 0.016)
    _tap(ctx, 10, 10)
    app.loop(ctx, 0.016)

    assert app.overlay_frame_name is None
    assert _px(ctx.frames[-1], 50, 10) == GREEN


def test_click_outside_is_blocked_when_the_overlay_does_not_allow_it() -> None:
    ctx, app = _app()

    app.tap("Open Sheet")
    app.loop(ctx, 0.016)
    _tap(ctx, 10, 10)
    app.loop(ctx, 0.016)

    assert app.overlay_frame_name == "Sheet"
    assert app.current_frame_id == "1:1"
