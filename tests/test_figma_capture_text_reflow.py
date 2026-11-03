"""Font-measured text reflow tests: wrapping, re-anchoring, overflow stats.

The compiler measures text with the same font machinery the renderer uses
(`luvatrix_ui.figma.text.FontLibrary`), so expectations below compute widths
with that same library.
"""

from __future__ import annotations

from typing import Any

from luvatrix_ui.figma.capture import compile_snapshots
from luvatrix_ui.figma.text import FontLibrary

from figma_capture_fixtures import SnapshotBuilder

_FONTS = FontLibrary()


def measured(text: str, size: float = 16.0, weight: float = 400.0) -> float:
    font = _FONTS.font(_FONTS.resolve("Inter", weight, False), size)
    return float(font.getlength(text))


def page() -> tuple[SnapshotBuilder, int]:
    b = SnapshotBuilder(title="Reflow")
    body = b.element("BODY")
    b.layout(body, 0, 0, 393, 852, **{"background-color": "rgb(255, 255, 255)"})
    return b, body


def first_child(result: Any) -> dict[str, Any]:
    return result.file["document"]["children"][0]["children"][0]["children"][0]


def paragraph(b: SnapshotBuilder, body: int, *, width: float, text: str, align: str = "start", x: float = 0.0) -> None:
    p = b.element("P", parent=body)
    b.layout(p, x, 0, width, 20, **{"text-align": align})
    t = b.text(text, parent=p)
    li = b.layout(t, x, 2, width, 20)
    b.text_box(li, x, 2, width, 20)


def test_long_link_text_wraps_to_the_captured_box_width() -> None:
    b, body = page()
    paragraph(b, body, width=200.0, text="Read the settings guide for details.")

    result = compile_snapshots([("/", b.build())])

    text = first_child(result)
    assert text["type"] == "TEXT"
    assert "\n" in text["characters"]
    lines = text["characters"].split("\n")
    wrap_width = 200.0
    for line in lines:
        assert measured(line) <= wrap_width + 1.0
    line_height = text["style"].get("lineHeightPx", 16 * 1.21)
    assert text["absoluteBoundingBox"]["height"] >= len(lines) * line_height - 1.0
    assert text["absoluteBoundingBox"]["x"] == 0.0
    assert result.report["pages"][0]["counts"].get("textOverflow", 0) == 0


def test_single_word_wider_than_the_box_is_counted_as_overflow() -> None:
    b, body = page()
    paragraph(b, body, width=80.0, text="Supercalifragilisticexpialidocious")

    result = compile_snapshots([("/", b.build())])

    text = first_child(result)
    assert "\n" not in text["characters"]
    assert measured(text["characters"]) > 80.0 * 1.10
    assert result.report["pages"][0]["counts"]["textOverflow"] == 1


def test_shrink_to_fit_badge_stays_on_one_line() -> None:
    b, body = page()
    badge = b.element("B", parent=body)
    b.layout(badge, 240, 0, 58, 20, **{"display": "inline"})
    t = b.text("$1,200", parent=badge)
    li = b.layout(t, 240, 0, 58, 20)
    b.text_box(li, 240, 0, 58, 20)

    result = compile_snapshots([("/", b.build())])

    text = first_child(result)
    assert "\n" not in text["characters"]
    box = text["absoluteBoundingBox"]
    expected = max(measured("$1,200"), 58.0)
    assert abs(box["width"] - expected) < 1.0
    center = box["x"] + box["width"] / 2
    assert abs(center - 269.0) < 2.0
    assert text["style"]["textAlignHorizontal"] == "CENTER"


def test_right_aligned_text_reanchors_by_measured_width() -> None:
    b, body = page()
    # Chrome drew the text at [250, 296]; the renderer font is wider.
    paragraph(b, body, width=200.0, text="Details here", align="right", x=100.0)
    # Overwrite the drawn bounds to simulate a right-aligned line.
    b._text_boxes[-1] = (b._text_boxes[-1][0], 250.0, 2, 46.0, 20, 0, -1)

    result = compile_snapshots([("/", b.build())])

    text = first_child(result)
    box = text["absoluteBoundingBox"]
    width = max(measured("Details here"), 46.0)
    assert abs(box["width"] - width) < 1.0
    assert abs((box["x"] + box["width"]) - 296.0) < 1.0


def test_center_aligned_text_keeps_its_center() -> None:
    b, body = page()
    paragraph(b, body, width=200.0, text="Details here", align="center", x=0.0)
    b._text_boxes[-1] = (b._text_boxes[-1][0], 77.0, 2, 46.0, 20, 0, -1)

    result = compile_snapshots([("/", b.build())])

    box = first_child(result)["absoluteBoundingBox"]
    center = box["x"] + box["width"] / 2
    assert abs(center - 100.0) < 1.5


def test_multi_run_text_measures_each_run_style() -> None:
    b, body = page()
    p = b.element("P", parent=body)
    b.layout(p, 0, 0, 120, 40)
    t1 = b.text("Hello ", parent=p)
    li1 = b.layout(t1, 0, 2, 59, 20)
    b.text_box(li1, 0, 2, 59, 20)
    bold = b.element("B", parent=p)
    b.layout(bold, 60, 0, 60, 20, **{"display": "inline", "font-weight": "700"})
    t2 = b.text("bold world", parent=bold)
    li2 = b.layout(t2, 60, 2, 60, 20)
    b.text_box(li2, 60, 2, 60, 20)

    result = compile_snapshots([("/", b.build())])

    text = first_child(result)
    # Union width is 120 (fills the 120px box); measured single-line width with
    # the bold run exceeds it, so the compiler wraps.
    assert "\n" in text["characters"]
    lines = text["characters"].split("\n")
    assert all(measured(line) <= 120.0 + 1.0 for line in lines)


def test_existing_line_breaks_are_preserved() -> None:
    b, body = page()
    p = b.element("P", parent=body)
    b.layout(p, 0, 0, 200, 60)
    first = b.text("First line", parent=p)
    li1 = b.layout(first, 0, 2, 90, 20)
    b.text_box(li1, 0, 2, 90, 20)
    br = b.element("BR", parent=p)
    b.layout(br, 0, 22, 1, 20, **{"display": "inline"})
    second = b.text("Second line", parent=p)
    li2 = b.layout(second, 1, 22, 100, 20)
    b.text_box(li2, 1, 22, 100, 20)

    result = compile_snapshots([("/", b.build())])

    frame = result.file["document"]["children"][0]["children"][0]
    texts = [child for child in frame["children"] if child["type"] == "TEXT"]
    assert sorted(t["characters"] for t in texts) == ["First line", "Second line"]
    ys = sorted(t["absoluteBoundingBox"]["y"] for t in texts)
    assert ys[1] - ys[0] >= 18.0  # the <br> break is preserved as stacked lines