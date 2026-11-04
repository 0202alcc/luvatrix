from __future__ import annotations

import numpy as np

from luvatrix_ui.figma import FigmaDocument, render_frame

from figma_fixtures import node, single_frame, solid


WHITE = (255, 255, 255, 255)


def _render(children, **frame_extra):
    doc = FigmaDocument.from_dict(single_frame(children, **frame_extra))
    return render_frame(doc, doc.start_frame_id)


def _px(img: np.ndarray, x: int, y: int) -> tuple[int, ...]:
    return tuple(int(v) for v in img[y, x][:3])


def _gray_over_red(mode: str) -> tuple[int, ...]:
    backdrop = node("0", "RECTANGLE", "Bg", 0, 0, 100, 100, fills=[solid(1, 0, 0)])
    top = node("1", "RECTANGLE", "Top", 0, 0, 100, 100, fills=[solid(0.5, 0.5, 0.5)], blendMode=mode)
    return _px(_render([backdrop, top]), 50, 50)


def test_multiply_darkens_the_backdrop() -> None:
    assert _gray_over_red("MULTIPLY") == (128, 0, 0)


def test_screen_lightens_the_backdrop() -> None:
    assert _gray_over_red("SCREEN") == (255, 128, 128)


def test_hard_light_follows_the_source() -> None:
    assert _gray_over_red("HARD_LIGHT") == (255, 0, 0)


def test_difference_subtracts_from_white() -> None:
    backdrop = node("0", "RECTANGLE", "Bg", 0, 0, 100, 100, fills=[solid(1, 1, 1)])
    top = node("1", "RECTANGLE", "Top", 0, 0, 100, 100, fills=[solid(1, 0, 0)], blendMode="DIFFERENCE")
    img = _render([backdrop, top])

    assert _px(img, 50, 50) == (0, 255, 255)


def test_paint_blend_mode_overrides_for_non_normal_paints() -> None:
    backdrop = node("0", "RECTANGLE", "Bg", 0, 0, 50, 100, fills=[solid(0.5, 0.5, 0.5)])
    top = node("1", "RECTANGLE", "Top", 0, 0, 50, 100, fills=[{**solid(1, 0, 0), "blendMode": "MULTIPLY"}])
    img = _render([backdrop, top])

    assert _px(img, 25, 50) == (128, 0, 0)


def test_normal_node_blend_is_unchanged() -> None:
    assert _gray_over_red("NORMAL") == (128, 128, 128)
    assert _gray_over_red("PASS_THROUGH") == (128, 128, 128)


def test_group_blend_composites_the_flattened_group_against_the_backdrop() -> None:
    backdrop = node("0", "RECTANGLE", "Bg", 0, 0, 100, 100, fills=[solid(0.5, 0.5, 0.5)])
    group = node(
        "g",
        "FRAME",
        "G",
        0,
        0,
        100,
        100,
        fills=[],
        blendMode="MULTIPLY",
        children=[
            node("1", "RECTANGLE", "A", 0, 0, 60, 60, fills=[solid(1, 0, 0)]),
            node("2", "RECTANGLE", "B", 40, 40, 60, 60, fills=[solid(1, 0, 0)]),
        ],
    )

    img = _render([backdrop, group])

    assert _px(img, 50, 50) == (128, 0, 0)
    assert _px(img, 10, 10) == (128, 0, 0)


def test_pass_through_group_leaves_overlap_unmultiplied() -> None:
    backdrop = node("0", "RECTANGLE", "Bg", 0, 0, 100, 100, fills=[solid(0.5, 0.5, 0.5)])
    group = node(
        "g",
        "FRAME",
        "G",
        0,
        0,
        100,
        100,
        fills=[],
        blendMode="PASS_THROUGH",
        children=[
            node("1", "RECTANGLE", "A", 0, 0, 60, 60, fills=[solid(1, 0, 0)]),
            node("2", "RECTANGLE", "B", 40, 40, 60, 60, fills=[solid(1, 0, 0)]),
        ],
    )

    img = _render([backdrop, group])

    assert _px(img, 50, 50) == (255, 0, 0)
