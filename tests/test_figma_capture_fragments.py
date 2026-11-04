"""Line fragments must slice the rendered text, not the raw markup text.

Chrome's DOMSnapshot reports ``textBoxes`` ``start``/``length`` offsets into
the *rendered* text, where CSS whitespace collapsing already replaced markup
newlines and indentation runs with single spaces. Slicing the raw layout text
with those offsets grabs stray characters ("\\nin") that then paint as ghost
lines on top of the following fragments.
"""

from __future__ import annotations

from typing import Any

from luvatrix_ui.figma.capture import compile_snapshots

from figma_capture_fixtures import SnapshotBuilder


def page() -> tuple[SnapshotBuilder, int]:
    b = SnapshotBuilder(title="Frag")
    body = b.element("BODY")
    b.layout(body, 0, 0, 393, 852, **{"background-color": "rgb(255, 255, 255)"})
    return b, body


def text_nodes(result: Any) -> list[str]:
    chars: list[str] = []

    def walk(node: dict[str, Any]) -> None:
        if node.get("type") == "TEXT":
            chars.append(str(node.get("characters", "")))
        for child in node.get("children") or ():
            walk(child)

    for frame in result.file["document"]["children"][0]["children"]:
        walk(frame)
    return chars


def test_line_fragments_slice_the_rendered_text_not_the_raw_markup() -> None:
    b, body = page()
    p = b.element("P", parent=body)
    b.layout(p, 0, 0, 393, 60)
    t = b.text('±1" plan placement for\n        items in slabs today', parent=p)
    li = b.layout(t, 0, 2, 393, 40)
    rendered = '±1" plan placement for items in slabs today'
    line1 = '±1" plan placement for'
    line2_start = len('±1" plan placement for items ')
    b.text_box(li, 0, 2, 200, 20, start=0, length=len(line1))
    b.text_box(li, 0, 22, 240, 20, start=line2_start, length=len(rendered) - line2_start)

    result = compile_snapshots([("/", b.build())])

    fragments = [c for c in text_nodes(result) if c.strip()]
    assert fragments == [line1, rendered[line2_start:]], fragments