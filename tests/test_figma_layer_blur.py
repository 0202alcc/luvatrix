from __future__ import annotations

import numpy as np

from luvatrix_ui.figma import FigmaDocument, render_frame

from figma_fixtures import node, single_frame, solid


RED = (255, 0, 0, 255)
WHITE = (255, 255, 255, 255)


def _render(children, **frame_extra):
    doc = FigmaDocument.from_dict(single_frame(children, **frame_extra))
    return render_frame(doc, doc.start_frame_id)


def _px(img: np.ndarray, x: int, y: int) -> tuple[int, ...]:
    return tuple(int(v) for v in img[y, x])


def test_layer_blur_softens_the_node_edges() -> None:
    card = node(
        "1",
        "RECTANGLE",
        "Card",
        30,
        30,
        40,
        40,
        fills=[solid(1, 0, 0)],
        effects=[{"type": "LAYER_BLUR", "radius": 8, "visible": True}],
    )

    img = _render([card])

    assert _px(img, 50, 50) == RED
    edge = int(img[30, 50, 1])
    assert 40 < edge < 210
    assert _px(img, 10, 50) == WHITE


def test_layer_blur_applies_to_the_whole_subtree() -> None:
    group = node(
        "g",
        "FRAME",
        "G",
        20,
        20,
        60,
        60,
        fills=[],
        effects=[{"type": "LAYER_BLUR", "radius": 6, "visible": True}],
        children=[
            node("1", "RECTANGLE", "A", 20, 20, 20, 20, fills=[solid(1, 0, 0)]),
            node("2", "RECTANGLE", "B", 50, 20, 20, 20, fills=[solid(1, 0, 0)]),
        ],
    )

    img = _render([group])

    gap = int(img[30, 45, 1])
    assert 40 < gap < 250
    assert _px(img, 5, 30) == WHITE


def test_layer_blur_leaves_the_backdrop_sharp() -> None:
    backdrop = node("0", "RECTANGLE", "Backdrop", 0, 0, 50, 100, fills=[solid(0, 1, 0)])
    glass = node(
        "1",
        "RECTANGLE",
        "Glass",
        25,
        25,
        50,
        50,
        fills=[solid(1, 1, 1, opacity=0.5)],
        effects=[{"type": "LAYER_BLUR", "radius": 10, "visible": True}],
    )

    img = _render([backdrop, glass])

    left, right = int(img[50, 48, 0]), int(img[50, 52, 0])
    assert abs(left - right) > 100
