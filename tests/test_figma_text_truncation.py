from __future__ import annotations

import numpy as np

from luvatrix_ui.figma import FigmaDocument, render_frame

from figma_fixtures import node, single_frame, solid


def _text(chars: str, style_extra: dict, *, w: float = 60, h: float = 100):
    style = {"fontFamily": "Inter", "fontSize": 12, "lineHeightPx": 16, "textAutoResize": "HEIGHT", **style_extra}
    return node("1", "TEXT", "T", 0, 0, w, h, characters=chars, fills=[solid(0, 0, 0)], style=style)


def _render(node_dict):
    doc = FigmaDocument.from_dict(single_frame([node_dict]))
    return render_frame(doc, doc.start_frame_id)


def _ink_rows(img: np.ndarray) -> np.ndarray:
    return np.nonzero((img[:, :, 0] < 128).any(axis=1))[0]


def _ink_cols(img: np.ndarray) -> np.ndarray:
    return np.nonzero((img[:, :, 0] < 128).any(axis=0))[0]


def test_max_lines_truncates_with_an_ellipsis() -> None:
    truncated = _render(_text("aaaa\nbbbb\ncccc\ndddd", {"maxLines": 2, "textTruncation": "ENDING"}))
    plain = _render(_text("aaaa\nbbbb", {}))

    rows = _ink_rows(truncated)
    assert rows.max() - rows.min() <= 2 * 16 + 4
    assert _ink_cols(truncated).max() > _ink_cols(plain).max() + 2


def test_fixed_height_boxes_clip_overflowing_lines_with_an_ellipsis() -> None:
    clipped = _render(_text("aaaa\nbbbb\ncccc", {"textAutoResize": "NONE"}, h=34))
    plain = _render(_text("aaaa\nbbbb", {}))

    rows = _ink_rows(clipped)
    assert rows.max() <= 40
    assert _ink_cols(clipped).max() > _ink_cols(plain).max() + 2


def test_max_lines_above_the_content_adds_no_ellipsis() -> None:
    limited = _render(_text("aaaa\nbbbb", {"maxLines": 5, "textTruncation": "ENDING"}))
    plain = _render(_text("aaaa\nbbbb", {}))

    assert limited.tobytes() == plain.tobytes()
