"""BACKGROUND_BLUR on fixed children blurs the scrolled content beneath them."""

from __future__ import annotations

import numpy as np
import pytest

from luvatrix_ui.figma import FigmaApp, FigmaDocument, render_frame
from luvatrix_ui.figma import app as figma_app
from luvatrix_ui.figma.render import FigmaRenderer

from figma_fixtures import node, solid
from test_figma_app import _FakeCtx

STRIPE_PT = 4
STRIPED_H = 200


def _stripes(prefix: str, height: int) -> list[dict]:
    return [
        node(f"{prefix}:{i}", "RECTANGLE", "Stripe", 0, y, 100, STRIPE_PT, fills=[solid(0, 0, 0)])
        for i, y in enumerate(range(0, height, 2 * STRIPE_PT))
    ]


def _glass_bar(node_id: str = "7:99", *, radius: float = 8.0) -> dict:
    return node(
        node_id,
        "FRAME",
        "Glass Bar",
        10,
        170,
        80,
        20,
        cornerRadius=10,
        fills=[solid(1, 1, 1, opacity=0.2)],
        effects=[{"type": "BACKGROUND_BLUR", "radius": radius, "visible": True}],
        children=[],
    )


def glass_file(*, scrolling: bool = True) -> dict:
    """A 100x400 feed: black/white stripes on top, solid red below, and a fixed glass capsule."""
    children = [
        *_stripes("7", STRIPED_H),
        node("7:90", "RECTANGLE", "Red Block", 0, STRIPED_H, 100, 400 - STRIPED_H, fills=[solid(1, 0, 0)]),
        _glass_bar(),
    ]
    feed = node(
        "7:1",
        "FRAME",
        "Feed",
        0,
        0,
        100,
        400 if scrolling else 200,
        fills=[solid(1, 1, 1)],
        clipsContent=True,
        overflowDirection="VERTICAL_SCROLLING" if scrolling else "NONE",
        numberOfFixedChildren=1,
        children=children,
    )
    return {
        "name": "Glass",
        "document": {
            "id": "0:0",
            "type": "DOCUMENT",
            "children": [{"id": "0:1", "type": "CANVAS", "name": "Page", "children": [feed]}],
        },
    }


def _app(ctx: _FakeCtx) -> FigmaApp:
    app = FigmaApp(FigmaDocument.from_dict(glass_file()))
    app.init(ctx)
    app.loop(ctx, 0.016)
    return app


def _bar_interior(frame: np.ndarray) -> np.ndarray:
    return frame[174:186, 25:75, :3].astype(np.float32)


def test_fixed_glass_bar_blurs_the_scrolled_content_beneath_it() -> None:
    ctx = _FakeCtx(100, 200)
    _app(ctx)

    interior = _bar_interior(ctx.frames[-1])
    # Unblurred stripes alternate 0 and 255 under a 20% white tint (204 apart);
    # a real backdrop blur averages them into a near-uniform gray.
    assert float(interior[..., 0].std()) < 20.0
    assert 90.0 < float(interior.mean()) < 190.0


def test_content_outside_the_capsule_stays_crisp() -> None:
    ctx = _FakeCtx(100, 200)
    _app(ctx)
    frame = ctx.frames[-1]

    beside = frame[170:190, 2:8, 0]
    assert set(np.unique(beside).tolist()) == {0, 255}
    # The bounding-box corner lies outside the capsule's rounded end.
    assert int(frame[170, 10, 0]) in (0, 255)


def test_backdrop_follows_the_current_scroll_offset() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)

    app.scroll_by(200)
    app.loop(ctx, 0.016)

    interior = _bar_interior(ctx.frames[-1])
    r, g, b = (float(interior[..., c].mean()) for c in range(3))
    # Red content under a 20% white tint: red stays high, green/blue only get the tint.
    assert r > 240 and g < 80 and b < 80


def test_backdrop_blur_is_cached_per_scroll_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[float] = []
    real = figma_app.backdrop_blur

    def counting(*args, **kwargs):
        calls.append(1.0)
        return real(*args, **kwargs)

    monkeypatch.setattr(figma_app, "backdrop_blur", counting)
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)
    first = len(calls)
    assert first == 1

    app.invalidate()
    app.loop(ctx, 0.016)
    assert len(calls) == first

    app.scroll_by(10)
    app.loop(ctx, 0.016)
    assert len(calls) == first + 1


def test_renderer_reports_backdrop_regions_for_fixed_layers() -> None:
    doc = FigmaDocument.from_dict(glass_file())
    backdrops: list = []

    overlay = FigmaRenderer(doc).render("7:1", 2.0, only_ids={"7:99"}, transparent=True, backdrops=backdrops)

    assert len(backdrops) == 1
    coverage, radius_px = backdrops[0]
    # The bar at 2x, plus at most one pixel of antialiasing on each side.
    bounds = (coverage.x0, coverage.y0, coverage.x1, coverage.y1)
    assert bounds == pytest.approx((20, 340, 180, 380), abs=1)
    assert radius_px == pytest.approx(16.0)
    # The fill is still drawn, translucent, for compositing over the blurred backdrop.
    assert 40 <= int(overlay[360, 100, 3]) <= 62


def test_background_blur_on_a_non_scrolling_frame_still_blurs_in_place() -> None:
    doc = FigmaDocument.from_dict(glass_file(scrolling=False))

    image = render_frame(doc, "7:1")

    interior = image[174:186, 25:75, 0].astype(np.float32)
    assert float(interior.std()) < 20.0
