"""Pseudo-element (::before / ::after) mapping tests.

The capture orchestrator collects computed pseudo styles with an injected
`Runtime.evaluate` pass; the compiler turns those entries into child nodes.
"""

from __future__ import annotations

from typing import Any

from luvatrix_ui.figma.capture import compile_snapshots

from figma_capture_fixtures import SnapshotBuilder

# ── entry builders ───────────────────────────────────────────────────────────

_EMPTY_PARENT = {
    "padding-top": "0px",
    "padding-right": "0px",
    "padding-bottom": "0px",
    "padding-left": "0px",
    "border-top-width": "0px",
    "border-right-width": "0px",
    "border-bottom-width": "0px",
    "border-left-width": "0px",
}


def entry(
    path: str,
    pseudo: str,
    *,
    tag: str = "div",
    styles: dict[str, str] | None = None,
    parent: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "path": path,
        "tag": tag,
        "pseudo": pseudo,
        "styles": {
            "content": "none",
            "display": "inline",
            "position": "static",
            "top": "auto",
            "left": "auto",
            "right": "auto",
            "bottom": "auto",
            "width": "auto",
            "height": "auto",
            "background-color": "rgba(0, 0, 0, 0)",
            "background-image": "none",
            "color": "rgb(23, 23, 23)",
            "font-family": "Inter",
            "font-size": "16px",
            "font-weight": "400",
            "font-style": "normal",
            "line-height": "24px",
            "letter-spacing": "normal",
            "text-align": "start",
            "opacity": "1",
            "transform": "none",
            "box-shadow": "none",
            "border-top-left-radius": "0px",
            "border-top-right-radius": "0px",
            "border-bottom-right-radius": "0px",
            "border-bottom-left-radius": "0px",
            "border-top-width": "0px",
            "border-top-style": "none",
            "border-top-color": "rgb(0, 0, 0)",
            "border-right-width": "0px",
            "border-right-style": "none",
            "border-right-color": "rgb(0, 0, 0)",
            "border-bottom-width": "0px",
            "border-bottom-style": "none",
            "border-bottom-color": "rgb(0, 0, 0)",
            "border-left-width": "0px",
            "border-left-style": "none",
            "border-left-color": "rgb(0, 0, 0)",
            "padding-top": "0px",
            "padding-right": "0px",
            "padding-bottom": "0px",
            "padding-left": "0px",
            **(styles or {}),
        },
        "parent": {**_EMPTY_PARENT, **(parent or {})},
    }


def page() -> tuple[SnapshotBuilder, int]:
    b = SnapshotBuilder(title="Pseudo")
    body = b.element("BODY")
    b.layout(body, 0, 0, 393, 852, **{"background-color": "rgb(255, 255, 255)"})
    return b, body


def first_child(result: Any) -> dict[str, Any]:
    return result.file["document"]["children"][0]["children"][0]["children"][0]


# ── tests ────────────────────────────────────────────────────────────────────

def test_before_string_content_becomes_a_text_child() -> None:
    b, body = page()
    item = b.element("DIV", parent=body)
    b.layout(item, 0, 0, 393, 24)
    t = b.text("Task one", parent=item)
    li = b.layout(t, 20, 2, 80, 20)
    b.text_box(li, 20, 2, 80, 20)

    result = compile_snapshots(
        [("/", b.build())],
        pseudos=[[entry("0", "before", styles={"content": '"\\2022 "', "font-size": "16px"})]],
    )

    frame = first_child(result)
    assert frame["type"] == "FRAME"
    bullet = frame["children"][0]
    assert bullet["type"] == "TEXT"
    assert bullet["characters"] == "\u2022 "
    assert bullet["id"].endswith(":before")
    assert bullet["absoluteBoundingBox"]["x"] == 0.0
    assert bullet["style"]["fontSize"] == 16
    assert result.report["pages"][0]["PSEUDO_COUNT"] == 1
    assert result.report["PSEUDO_COUNT"] == 1


def test_before_honors_parent_padding_and_border_when_anchoring() -> None:
    b, body = page()
    item = b.element("DIV", parent=body)
    b.layout(item, 10, 0, 393, 24)
    t = b.text("Task one", parent=item)
    li = b.layout(t, 40, 2, 80, 20)
    b.text_box(li, 40, 2, 80, 20)

    result = compile_snapshots(
        [("/", b.build())],
        pseudos=[
            [
                entry(
                    "0",
                    "before",
                    styles={"content": '"\\2022 "', "font-size": "16px"},
                    parent={"padding-left": "16px", "border-left-width": "2px"},
                )
            ]
        ],
    )

    bullet = first_child(result)["children"][0]
    assert bullet["absoluteBoundingBox"]["x"] == 12.0


def test_absolute_after_anchors_from_right_and_bottom_offsets() -> None:
    b, body = page()
    card = b.element("DIV", parent=body)
    b.layout(card, 0, 0, 200, 100, **{"background-color": "rgb(255, 255, 255)"})

    result = compile_snapshots(
        [("/", b.build())],
        pseudos=[
            [
                entry(
                    "0",
                    "after",
                    styles={
                        "content": '""',
                        "position": "absolute",
                        "right": "8px",
                        "bottom": "4px",
                        "width": "10px",
                        "height": "10px",
                        "background-color": "rgb(239, 68, 68)",
                    },
                )
            ]
        ],
    )

    bar = first_child(result)["children"][0]
    assert bar["type"] == "RECTANGLE"
    assert bar["absoluteBoundingBox"] == {"x": 182.0, "y": 86.0, "width": 10.0, "height": 10.0}
    assert bar["fills"] == [{"type": "SOLID", "color": {"r": 239 / 255, "g": 68 / 255, "b": 68 / 255, "a": 1.0}}]


def test_absolute_after_uses_left_when_given() -> None:
    b, body = page()
    card = b.element("DIV", parent=body)
    b.layout(card, 0, 0, 200, 100)
    result = compile_snapshots(
        [("/", b.build())],
        pseudos=[
            [
                entry(
                    "0",
                    "after",
                    styles={
                        "content": '""',
                        "position": "absolute",
                        "left": "12px",
                        "top": "0px",
                        "width": "4px",
                        "height": "100px",
                        "background-color": "rgb(37, 99, 235)",
                    },
                )
            ]
        ],
    )

    bar = first_child(result)["children"][0]
    assert bar["absoluteBoundingBox"] == {"x": 12.0, "y": 0.0, "width": 4.0, "height": 100.0}


def test_badge_pill_pseudo_becomes_a_frame_with_text() -> None:
    b, body = page()
    card = b.element("DIV", parent=body)
    b.layout(card, 0, 0, 200, 60)
    result = compile_snapshots(
        [("/", b.build())],
        pseudos=[
            [
                entry(
                    "0",
                    "before",
                    styles={
                        "content": '"NEW"',
                        "display": "inline-block",
                        "width": "44px",
                        "height": "20px",
                        "background-color": "rgb(37, 99, 235)",
                        "color": "rgb(255, 255, 255)",
                        "border-top-left-radius": "999px",
                        "border-top-right-radius": "999px",
                        "border-bottom-right-radius": "999px",
                        "border-bottom-left-radius": "999px",
                        "font-size": "11px",
                    },
                )
            ]
        ],
    )

    pill = first_child(result)["children"][0]
    assert pill["type"] == "FRAME"
    assert pill["cornerRadius"] == 999
    assert pill["fills"][0]["type"] == "SOLID"
    text = pill["children"][0]
    assert text["type"] == "TEXT"
    assert text["characters"] == "NEW"


def test_icon_font_glyph_keeps_its_font_family() -> None:
    b, body = page()
    card = b.element("DIV", parent=body)
    b.layout(card, 0, 0, 200, 40)
    result = compile_snapshots(
        [("/", b.build())],
        pseudos=[
            [
                entry(
                    "0",
                    "before",
                    styles={"content": '"\\f007"', "font-family": '"Font Awesome 6 Free"', "font-size": "18px"},
                )
            ]
        ],
    )

    glyph = first_child(result)["children"][0]
    assert glyph["type"] == "TEXT"
    assert glyph["characters"] == "\uf007"
    assert glyph["style"]["fontFamily"] == "Font Awesome 6 Free"


def test_empty_content_with_no_paint_is_skipped_but_content_none_never_emits() -> None:
    b, body = page()
    card = b.element("DIV", parent=body)
    b.layout(card, 0, 0, 200, 40)
    result = compile_snapshots(
        [("/", b.build())],
        pseudos=[[entry("0", "before", styles={"content": '""'}), entry("0", "after", styles={"content": "none"})]],
    )

    frame = first_child(result)
    assert frame["children"] == []
    assert result.report["PSEUDO_COUNT"] == 0


def test_counter_content_is_counted_as_unsupported() -> None:
    b, body = page()
    item = b.element("DIV", parent=body)
    b.layout(item, 0, 0, 200, 40)
    result = compile_snapshots(
        [("/", b.build())],
        pseudos=[[entry("0", "before", styles={"content": 'counter(item) ". "'})]],
    )

    assert first_child(result)["children"] == []
    assert result.report["pages"][0]["unsupported"]["pseudo-counter"] == 1
    assert result.report["PSEUDO_COUNT"] == 0


def test_entries_with_unknown_paths_or_mismatched_tags_are_ignored() -> None:
    b, body = page()
    card = b.element("DIV", parent=body)
    b.layout(card, 0, 0, 200, 40)
    result = compile_snapshots(
        [("/", b.build())],
        pseudos=[[entry("9.9", "before", styles={"content": '"x"'}), entry("0", "before", tag="span", styles={"content": '"y"'})]],
    )

    assert first_child(result)["children"] == []
    assert result.report["PSEUDO_COUNT"] == 0


def test_pseudo_without_layout_or_hidden_display_is_skipped() -> None:
    b, body = page()
    card = b.element("DIV", parent=body)
    b.layout(card, 0, 0, 200, 40)
    result = compile_snapshots(
        [("/", b.build())],
        pseudos=[
            [
                entry("0", "before", styles={"content": '"x"', "display": "none"}),
                entry("0", "after", styles={"content": '"y"', "opacity": "0"}),
            ]
        ],
    )

    assert first_child(result)["children"] == []
    assert result.report["PSEUDO_COUNT"] == 0


def test_before_and_after_order_around_existing_children() -> None:
    b, body = page()
    row = b.element("DIV", parent=body)
    b.layout(row, 0, 0, 300, 40, **{"background-color": "rgb(240, 240, 240)"})
    left = b.element("DIV", parent=row)
    b.layout(left, 0, 0, 100, 40, **{"background-color": "rgb(200, 200, 200)"})
    result = compile_snapshots(
        [("/", b.build())],
        pseudos=[
            [
                entry("0", "before", styles={"content": '""', "width": "8px", "height": "8px", "background-color": "rgb(255, 0, 0)"}),
                entry("0", "after", styles={"content": '""', "width": "8px", "height": "8px", "background-color": "rgb(0, 0, 255)"}),
            ]
        ],
    )

    frame = first_child(result)
    kinds = [(child["id"].endswith(":before"), child["id"].endswith(":after")) for child in frame["children"]]
    assert kinds == [(True, False), (False, False), (False, True)]