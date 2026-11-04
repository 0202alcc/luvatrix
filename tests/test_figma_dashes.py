from __future__ import annotations

import numpy as np

from luvatrix_ui.figma import FigmaDocument, render_frame

from figma_fixtures import node, single_frame, solid


def _render(children, *, scale: float = 1.0):
    doc = FigmaDocument.from_dict(single_frame(children))
    return render_frame(doc, doc.start_frame_id, scale=scale)


def _dashed(**extra):
    return node(
        "1",
        "RECTANGLE",
        "R",
        10,
        10,
        80,
        80,
        fills=[],
        strokes=[solid(1, 0, 0)],
        strokeWeight=2,
        **extra,
    )


def _top_edge_runs(img: np.ndarray, scale: float = 1.0) -> list[int]:
    """Run lengths of red-ink pixels along the stroke's top edge."""
    row = img[int(11 * scale), :, 1] < 128
    runs, current = [], 0
    for value in row:
        if value:
            current += 1
        elif current:
            runs.append(current)
            current = 0
    if current:
        runs.append(current)
    return runs


def test_solid_strokes_have_no_gaps() -> None:
    img = _render([_dashed()])

    assert len(_top_edge_runs(img)) == 1


def test_stroke_dashes_leave_gaps_along_the_outline() -> None:
    img = _render([_dashed(strokeDashes=[6, 4])])

    runs = _top_edge_runs(img)
    assert len(runs) > 1
    assert all(4 <= run <= 9 for run in runs[:-1])


def test_dash_pattern_key_is_honored_too() -> None:
    img = _render([_dashed(dashPattern=[6, 4])])

    assert len(_top_edge_runs(img)) > 1


def test_dash_lengths_scale_with_the_render_scale() -> None:
    small = _top_edge_runs(_render([_dashed(strokeDashes=[6, 4])], scale=1.0), scale=1.0)
    large = _top_edge_runs(_render([_dashed(strokeDashes=[6, 4])], scale=2.0), scale=2.0)

    assert small and large
    assert abs(large[0] - 2 * small[0]) <= 4


def test_vector_lines_can_be_dashed() -> None:
    line = node(
        "1",
        "LINE",
        "Line",
        10,
        50,
        80,
        0,
        strokes=[solid(1, 0, 0)],
        strokeWeight=2,
        strokeDashes=[10, 10],
    )

    img = _render([line])

    row = img[50, :, 1] < 128
    gaps, current = 0, 0
    for value in row:
        if not value:
            current += 1
        elif current:
            gaps += 1
            current = 0
    assert gaps >= 2
