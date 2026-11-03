from __future__ import annotations

import copy

import numpy as np

from luvatrix_ui.figma import FigmaApp, FigmaDocument, render_frame

from figma_fixtures import smart_animate_file
from test_figma_app import _FakeCtx, _tap


WHITE = (255, 255, 255, 255)
RED = (255, 0, 0, 255)
BLUE = (0, 0, 255, 255)


def _app(data=None) -> tuple[_FakeCtx, FigmaApp]:
    ctx = _FakeCtx(100, 100)
    app = FigmaApp(FigmaDocument.from_dict(data or smart_animate_file()))
    app.init(ctx)
    app.loop(ctx, 0.016)
    return ctx, app


def _px(frame: np.ndarray, x: int, y: int) -> tuple[int, ...]:
    return tuple(int(v) for v in frame[y, x])


def _close(actual: tuple[int, ...], expected: tuple[int, ...], tol: int = 4) -> bool:
    return all(abs(int(a) - int(e)) <= tol for a, e in zip(actual, expected))


def test_smart_animate_tweens_the_matched_layer_instead_of_crossfading() -> None:
    ctx, app = _app()

    _tap(ctx, 10, 10)
    app.loop(ctx, 0.1)

    frame = ctx.frames[-1]
    assert _px(frame, 10, 10) == WHITE
    assert _px(frame, 40, 40) == RED
    assert _px(frame, 70, 5) == BLUE

    app.loop(ctx, 0.1)
    app.loop(ctx, 0.1)

    frame = ctx.frames[-1]
    expected = render_frame(app.document, "2:1")
    assert frame.tobytes() == expected.tobytes()


def test_smart_animate_interpolates_opacity() -> None:
    data = smart_animate_file()
    for frame in data["document"]["children"][0]["children"]:
        if frame["name"] == "B":
            frame["children"][0]["opacity"] = 0.0
    ctx, app = _app(data)

    _tap(ctx, 10, 10)
    app.loop(ctx, 0.1)

    frame = ctx.frames[-1]
    assert _close(_px(frame, 70, 70), (255, 128, 128, 255))


def test_smart_animate_restores_the_document_after_the_transition() -> None:
    ctx, app = _app()
    doc = app.document
    before = copy.deepcopy(doc.node("2:2"))

    _tap(ctx, 10, 10)
    app.loop(ctx, 0.1)
    app.loop(ctx, 0.1)
    app.loop(ctx, 0.1)

    assert doc.node("2:2") == before
    settled = len(ctx.frames)
    app.loop(ctx, 0.1)
    assert len(ctx.frames) == settled


def test_smart_animate_without_matching_layers_crossfades() -> None:
    data = smart_animate_file()
    for frame in data["document"]["children"][0]["children"]:
        if frame["name"] == "B":
            for child in frame["children"]:
                child["name"] = "Unrelated " + child["name"]
    ctx, app = _app(data)

    _tap(ctx, 10, 10)
    app.loop(ctx, 0.1)

    frame = ctx.frames[-1]
    assert _close(_px(frame, 10, 10), (255, 128, 128, 255))
