"""Text mapping tests: characters, base style, span overrides, and boxes."""

from __future__ import annotations

from typing import Any

from luvatrix_ui.figma.capture import compile_snapshots

from figma_capture_fixtures import SnapshotBuilder


def page(**body_styles: str) -> tuple[SnapshotBuilder, int]:
    b = SnapshotBuilder(title="Text")
    body = b.element("BODY")
    b.layout(body, 0, 0, 393, 852, **{"background-color": "rgb(255, 255, 255)", **body_styles})
    return b, body


def test_text_element_becomes_a_text_node_with_span_overrides() -> None:
    b, body = page()
    p = b.element("P", parent=body)
    b.layout(p, 0, 0, 200, 50, **{"color": "rgb(51, 51, 51)", "font-size": "16px"})
    t1 = b.text("Hello ", parent=p)
    li1 = b.layout(t1, 0, 2, 59, 20)
    b.text_box(li1, 0, 2, 59, 20)
    bold = b.element("B", parent=p)
    b.layout(bold, 60, 0, 50, 20, **{"display": "inline", "font-weight": "700", "color": "rgb(255, 0, 0)"})
    t2 = b.text("bold", parent=bold)
    li2 = b.layout(t2, 60, 2, 50, 20)
    b.text_box(li2, 60, 2, 50, 20)
    t3 = b.text(" tail", parent=p)
    li3 = b.layout(t3, 110, 2, 49, 20)
    b.text_box(li3, 110, 2, 49, 20)

    result = compile_snapshots([("/", b.build())])

    text = result.file["document"]["children"][0]["children"][0]["children"][0]
    assert text["type"] == "TEXT"
    assert text["characters"] == "Hello bold tail"
    assert text["style"]["fontSize"] == 16
    assert text["style"]["fontFamily"] == "sans-serif"
    assert text["fills"] == [{"type": "SOLID", "color": {"r": 51 / 255, "g": 51 / 255, "b": 51 / 255, "a": 1.0}}]
    assert text["absoluteBoundingBox"] == {"x": 0.0, "y": 2.0, "width": 200.0, "height": 20.0}
    overrides = text["characterStyleOverrides"]
    assert len(overrides) == len(text["characters"])
    bold_keys = {overrides[i] for i in range(6, 10)}
    plain_keys = {overrides[i] for i in (0, 4, 10)}
    assert bold_keys.isdisjoint(plain_keys)
    for key in bold_keys:
        assert key != 0
        entry = text["styleOverrideTable"][str(key)]
        assert entry["fontWeight"] == 700
        assert entry["fills"] == [{"type": "SOLID", "color": {"r": 1.0, "g": 0.0, "b": 0.0, "a": 1.0}}]


def test_text_style_maps_css_typography_to_figma_style() -> None:
    b, body = page()
    label = b.element("DIV", parent=body)
    b.layout(
        label,
        0,
        0,
        200,
        40,
        **{
            "color": "rgb(10, 20, 30)",
            "font-family": '"Inter", sans-serif',
            "font-size": "20px",
            "font-weight": "600",
            "font-style": "italic",
            "line-height": "30px",
            "letter-spacing": "1.5px",
            "text-transform": "uppercase",
            "text-decoration": "underline",
            "text-align": "center",
        },
    )
    t = b.text("Settings", parent=label)
    li = b.layout(t, 4, 4, 120, 30)
    b.text_box(li, 4, 4, 120, 30)

    result = compile_snapshots([("/", b.build())])

    node = result.file["document"]["children"][0]["children"][0]["children"][0]
    style = node["style"]
    assert style["fontFamily"] == "Inter"
    assert style["fontSize"] == 20
    assert style["fontWeight"] == 600
    assert style["italic"] is True
    assert style["lineHeightPx"] == 30
    assert style["lineHeightUnit"] == "PIXELS"
    assert style["letterSpacing"] == 1.5
    assert style["textCase"] == "UPPER"
    assert style["textDecoration"] == "UNDERLINE"
    assert style["textAlignHorizontal"] == "CENTER"
    assert node["characters"] == "Settings"


def test_text_with_background_is_wrapped_in_a_frame() -> None:
    b, body = page()
    button = b.element("BUTTON", parent=body)
    b.layout(
        button,
        10,
        10,
        120,
        40,
        **{"background-color": "rgb(37, 99, 235)", "color": "rgb(255, 255, 255)", "border-radius": "8px"},
    )
    t = b.text("Save", parent=button)
    li = b.layout(t, 40, 20, 60, 20)
    b.text_box(li, 40, 20, 60, 20)

    result = compile_snapshots([("/", b.build())])

    frame = result.file["document"]["children"][0]["children"][0]["children"][0]
    assert frame["type"] == "FRAME"
    assert frame["fills"] == [{"type": "SOLID", "color": {"r": 37 / 255, "g": 99 / 255, "b": 235 / 255, "a": 1.0}}]
    assert [child["type"] for child in frame["children"]] == ["TEXT"]
    assert frame["children"][0]["absoluteBoundingBox"] == {"x": 40.0, "y": 20.0, "width": 90.0, "height": 20.0}

def test_shrink_to_fit_text_boxes_widen_symmetrically() -> None:
    b, body = page()
    row = b.element("DIV", parent=body)
    b.layout(row, 0, 0, 300, 20)
    amount = b.element("B", parent=row)
    b.layout(amount, 240, 0, 58, 20, **{"display": "inline"})
    t = b.text("$1,200", parent=amount)
    li = b.layout(t, 240, 0, 58, 20)
    b.text_box(li, 240, 0, 58, 20)

    result = compile_snapshots([("/", b.build())])

    text = result.file["document"]["children"][0]["children"][0]["children"][0]["children"][0]
    box = text["absoluteBoundingBox"]
    # Content-sized box: widened symmetrically around the Chrome text center.
    center = box["x"] + box["width"] / 2
    assert abs(center - 269.0) < 2.0
    assert box["width"] >= 58 * 1.12
    assert text["style"]["textAlignHorizontal"] == "LEFT"


def test_input_values_become_text() -> None:
    b, body = page()
    field = b.element("INPUT", parent=body, attrs={"value": "Orbit", "type": "text"})
    b.layout(field, 20, 40, 260, 36, **{"border-top-width": "1px", "border-top-style": "solid", "border-top-color": "rgb(209, 213, 219)"})
    b.set_input_value(field, "Orbit")

    result = compile_snapshots([("/", b.build())])

    frame = result.file["document"]["children"][0]["children"][0]["children"][0]
    assert frame["type"] == "FRAME"
    text = frame["children"][0]
    assert text["characters"] == "Orbit"
