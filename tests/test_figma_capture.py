"""Tests for the DOMSnapshot-to-Figma compiler behind `luvatrix figma capture`."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import types
from typing import Any

import pytest

from luvatrix_ui.figma import capture
from luvatrix_ui.figma.capture import compile_snapshots

from figma_capture_fixtures import SnapshotBuilder


def solid(r: float, g: float, b: float, a: float = 1.0) -> dict[str, Any]:
    return {"type": "SOLID", "color": {"r": r, "g": g, "b": b, "a": a}}


def frame_of(result: Any, index: int = 0) -> dict[str, Any]:
    return result.file["document"]["children"][0]["children"][index]


def compile_one(build: Any, *, path: str = "/", **kwargs: Any) -> Any:
    return compile_snapshots([(path, build.build())], **kwargs)


def dashboard_builder() -> SnapshotBuilder:
    """body > header, main > card(bg + border + radius + child)."""
    b = SnapshotBuilder(title="Dashboard")
    body = b.element("BODY")
    b.layout(body, 0, 0, 393, 852, **{"background-color": "rgb(255, 255, 255)"})
    header = b.element("HEADER", parent=body)
    b.layout(header, 0, 0, 393, 56, **{"background-color": "rgb(17, 24, 39)"})
    main = b.element("MAIN", parent=body)
    b.layout(main, 0, 56, 393, 796)
    card = b.element("DIV", parent=main, attrs={"class": "card"})
    b.layout(
        card,
        16,
        24,
        361,
        120,
        **{
            "background-color": "rgb(255, 136, 0)",
            "border-radius": "12px",
            "border-top-left-radius": "12px",
            "border-top-right-radius": "12px",
            "border-bottom-right-radius": "12px",
            "border-bottom-left-radius": "12px",
            "width": "361px",
            "height": "120px",
        },
    )
    inner = b.element("DIV", parent=card)
    b.layout(inner, 28, 40, 337, 96, **{"background-color": "rgb(59, 130, 246)", "width": "337px", "height": "96px"})
    return b


def test_solid_boxes_become_frames_and_rectangles() -> None:
    result = compile_one(dashboard_builder())

    canvas = result.file["document"]["children"][0]
    root = canvas["children"][0]
    assert root["type"] == "FRAME"
    assert root["name"] == "Dashboard"
    assert root["absoluteBoundingBox"] == {"x": 0.0, "y": 0.0, "width": 393.0, "height": 852.0}
    assert root["fills"] == [solid(1.0, 1.0, 1.0)]
    header, main = root["children"][0], root["children"][1]
    assert header["type"] == "RECTANGLE"
    assert header["absoluteBoundingBox"] == {"x": 0.0, "y": 0.0, "width": 393.0, "height": 56.0}
    assert header["fills"] == [solid(17 / 255, 24 / 255, 39 / 255)]
    assert main["type"] == "FRAME"
    card = main["children"][0]
    assert card["type"] == "FRAME"
    assert card["name"] == "div.card"
    assert card["absoluteBoundingBox"] == {"x": 16.0, "y": 24.0, "width": 361.0, "height": 120.0}
    assert card["fills"] == [solid(1.0, 136 / 255, 0.0)]
    assert card["cornerRadius"] == 12
    assert card["rectangleCornerRadii"] == [12, 12, 12, 12]
    inner = card["children"][0]
    assert inner["type"] == "RECTANGLE"
    assert inner["absoluteBoundingBox"] == {"x": 28.0, "y": 40.0, "width": 337.0, "height": 96.0}
    assert inner["fills"] == [solid(59 / 255, 130 / 255, 246 / 255)]


def test_hidden_and_zero_size_nodes_are_skipped() -> None:
    b = SnapshotBuilder(title="Skips")
    body = b.element("BODY")
    b.layout(body, 0, 0, 100, 100, **{"background-color": "rgb(255, 255, 255)"})
    visible = b.element("DIV", parent=body)
    b.layout(visible, 0, 0, 50, 50, **{"background-color": "rgb(0, 255, 0)"})
    hidden = b.element("DIV", parent=body)
    b.layout(hidden, 0, 50, 50, 50, **{"background-color": "rgb(255, 0, 0)", "visibility": "hidden"})
    zero = b.element("DIV", parent=body)
    b.layout(zero, 0, 50, 0, 40, **{"background-color": "rgb(0, 0, 255)"})

    result = compile_one(b)

    root = frame_of(result)
    assert [c["name"] for c in root["children"]] == ["div"]
    skipped = result.report["pages"][0]["skipped"]
    assert skipped["hidden"] == 1
    assert skipped["zeroSize"] == 1


def test_frame_name_uses_the_path_when_the_title_is_empty() -> None:
    b = SnapshotBuilder(title="")
    body = b.element("BODY")
    b.layout(body, 0, 0, 393, 852, **{"background-color": "rgb(255, 255, 255)"})

    result = compile_snapshots([("/settings", b.build())])

    assert frame_of(result)["name"] == "Settings"


def test_flow_starting_points_point_at_the_first_frame() -> None:
    first = SnapshotBuilder(title="Home")
    body = first.element("BODY")
    first.layout(body, 0, 0, 393, 852, **{"background-color": "rgb(255, 255, 255)"})
    second = SnapshotBuilder(title="Detail")
    body2 = second.element("BODY")
    second.layout(body2, 0, 0, 393, 852, **{"background-color": "rgb(0, 0, 255)"})

    result = compile_snapshots([("/", first.build()), ("/detail", second.build())])

    canvas = result.file["document"]["children"][0]
    assert [c["name"] for c in canvas["children"]] == ["Home", "Detail"]
    assert canvas["flowStartingPoints"] == [{"nodeId": canvas["children"][0]["id"], "name": "Start"}]
    detail = canvas["children"][1]
    assert detail["absoluteBoundingBox"]["x"] >= 393


def test_compiled_payload_loads_with_figma_document(tmp_path: Path) -> None:
    result = compile_one(dashboard_builder())
    design = tmp_path / "figma_file.json"
    design.write_text(json.dumps(result.file), encoding="utf-8")

    from luvatrix_ui.figma.document import FigmaDocument

    doc = FigmaDocument.load(design)
    assert [f.name for f in doc.frames] == ["Dashboard"]
    assert doc.start_frame_id == doc.frames[0].id


def test_node_ids_are_unique_across_pages() -> None:
    def make() -> SnapshotBuilder:
        b = SnapshotBuilder(title="Page")
        body = b.element("BODY")
        b.layout(body, 0, 0, 393, 852, **{"background-color": "rgb(255, 255, 255)"})
        div = b.element("DIV", parent=body)
        b.layout(div, 0, 0, 10, 10, **{"background-color": "rgb(255, 0, 0)"})
        return b

    result = compile_snapshots([("/a", make().build()), ("/b", make().build())])

    ids: list[str] = []

    def collect(node: dict[str, Any]) -> None:
        ids.append(node["id"])
        for child in node.get("children") or ():
            collect(child)

    for frame in result.file["document"]["children"][0]["children"]:
        collect(frame)
    assert len(ids) == len(set(ids))

def test_title_index_and_layout_text_wire_variants() -> None:
    """Chrome encodes doc title as a string index and text content in layout.text."""
    b = SnapshotBuilder(title="Encoded")
    body = b.element("BODY")
    b.layout(body, 0, 0, 393, 852, **{"background-color": "rgb(255, 255, 255)"})
    heading = b.element("H1", parent=body)
    b.layout(heading, 0, 0, 200, 30, **{"color": "rgb(17, 24, 39)"})
    t = b.text("Orbit", parent=heading)
    li = b.layout(t, 0, 0, 80, 30)
    b.text_box(li, 0, 0, 80, 30)

    snapshot = b.build()
    snapshot["documents"][0]["nodes"]["textValue"] = {"index": [], "value": []}
    strings = snapshot["strings"]
    strings.append("Encoded")
    snapshot["documents"][0]["title"] = len(strings) - 1

    result = compile_snapshots([("/", snapshot)])

    frame = result.file["document"]["children"][0]["children"][0]
    assert frame["name"] == "Encoded"
    text = frame["children"][0]
    assert text["type"] == "TEXT"
    assert text["characters"] == "Orbit"
    assert result.report["pages"][0]["title"] == "Encoded"


# ── color scheme emulation ───────────────────────────────────────────────────


class _FakeCDPPage:
    """A CDP page double that records raw calls and serves one canned snapshot."""

    def __init__(self, snapshot: dict[str, Any]) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._snapshot = snapshot

    async def call(self, method: str, params: Any = None) -> Any:
        self.calls.append((method, params))
        return {}

    async def set_viewport(self, width: int, height: int, scale: float = 3.0) -> None:
        self.calls.append(("set_viewport", (width, height, scale)))

    async def set_cookies(self, cookies: Any, url: str) -> None:
        self.calls.append(("set_cookies", url))

    async def navigate(self, url: str) -> None:
        self.calls.append(("navigate", url))

    async def ready(self, timeout: float = 10.0, *, extra_delay: float = 0.0) -> bool:
        _ = (timeout, extra_delay)
        return True

    async def evaluate(self, expression: str) -> Any:
        _ = expression
        return None

    async def capture_snapshot(self, style_props: Any = None) -> dict[str, Any]:
        _ = style_props
        return self._snapshot


def _fake_cdp_module(monkeypatch: Any, page: _FakeCDPPage) -> None:
    class _Chrome:
        ws_url = "ws://fake"

        def close(self) -> None:
            pass

    async def _connect(ws_url: str) -> object:
        _ = ws_url
        return object()

    async def _attach(conn: object) -> _FakeCDPPage:
        _ = conn
        return page

    fake = types.ModuleType("luvatrix_ui.figma.cdp")
    fake.Chrome = type("Chrome", (), {"launch": staticmethod(lambda path=None: _Chrome())})  # type: ignore[attr-defined]
    fake.CDPConnection = type("CDPConnection", (), {"connect": staticmethod(_connect)})  # type: ignore[attr-defined]
    fake.CDPPage = type("CDPPage", (), {"attach": staticmethod(_attach)})  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "luvatrix_ui.figma.cdp", fake)
    # `from . import cdp` resolves the attribute on the already-imported package.
    import luvatrix_ui.figma

    monkeypatch.setattr(luvatrix_ui.figma, "cdp", fake)


def _one_page_snapshot() -> dict[str, Any]:
    builder = SnapshotBuilder(title="Home")
    body = builder.element("BODY")
    builder.layout(body, 0, 0, 393, 852, **{"background-color": "rgb(0, 0, 0)"})
    return builder.build()


def test_capture_design_emulates_the_requested_color_scheme(tmp_path: Path, monkeypatch: Any) -> None:
    page = _FakeCDPPage(_one_page_snapshot())
    _fake_cdp_module(monkeypatch, page)

    capture.capture_design("http://localhost:3000/", tmp_path, viewport="393x852@3", wait=0.0, color_scheme="dark")

    emulations = [params for method, params in page.calls if method == "Emulation.setEmulatedMedia"]
    assert emulations == [{"features": [{"name": "prefers-color-scheme", "value": "dark"}]}]


def test_capture_design_leaves_the_color_scheme_alone_by_default(tmp_path: Path, monkeypatch: Any) -> None:
    page = _FakeCDPPage(_one_page_snapshot())
    _fake_cdp_module(monkeypatch, page)

    capture.capture_design("http://localhost:3000/", tmp_path, viewport="393x852@3", wait=0.0)

    assert not [params for method, params in page.calls if method == "Emulation.setEmulatedMedia"]


def test_capture_design_rejects_an_unknown_color_scheme(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="color scheme"):
        capture.capture_design("http://localhost:3000/", tmp_path, color_scheme="sepia")


# ── modern CSS color functions (Chrome reports lab()/oklab() computed colors) ─


def _composite_over(color: tuple[float, float, float, float], dst: tuple[float, float, float]) -> tuple[int, int, int]:
    r, g, b, a = color
    return tuple(round((c * a + d * (1 - a)) * 255) for c, d in zip((r, g, b), dst))


def test_parse_css_color_reads_lab_colors() -> None:
    cases = {
        "lab(10.2077 -2.43652 1.36734)": (25, 29, 26),
        "lab(98.2685 -0.0967681 0.365055)": (250, 250, 249),
        "lab(94.9733 -0.904739 3.28048)": (241, 241, 234),
        "lab(16.962 -2.9885 1.82864)": (38, 43, 39),
        "lab(34.3366 -2.56333 1.01902)": (77, 82, 79),
        "lab(59.7139 -20.1565 3.34306)": (105, 154, 137),
        "lab(100 0 0)": (255, 255, 255),
        "lab(0 0 0)": (0, 0, 0),
        "lab(50% 20 -30)": (133, 108, 170),
    }
    for value, expected in cases.items():
        color = capture.parse_css_color(value)
        assert color is not None, value
        assert _composite_over(color, (0.0, 0.0, 0.0)) == pytest.approx(expected, abs=2)
        assert color[3] == pytest.approx(1.0)


def test_parse_css_color_reads_oklab_colors() -> None:
    cases = {
        "oklab(0.955998 -0.00264055 0.00862867)": (241, 241, 234),
        "oklab(1 0 0)": (255, 255, 255),
        "oklab(0 0 0)": (0, 0, 0),
        "oklab(50% 0.1 -0.1)": (129, 69, 154),
    }
    for value, expected in cases.items():
        color = capture.parse_css_color(value)
        assert color is not None, value
        assert _composite_over(color, (0.0, 0.0, 0.0)) == pytest.approx(expected, abs=2)
        assert color[3] == pytest.approx(1.0)


def test_parse_css_color_reads_lch_and_oklch_colors() -> None:
    blue = capture.parse_css_color("oklch(0.7 0.15 250)")
    assert blue is not None
    assert _composite_over(blue, (0.0, 0.0, 0.0)) == pytest.approx((75, 163, 247), abs=2)
    red = capture.parse_css_color("lch(50% 40 30)")
    assert red is not None
    assert _composite_over(red, (0.0, 0.0, 0.0)) == pytest.approx((178, 93, 87), abs=2)


def test_parse_css_color_reads_lab_and_oklab_alpha() -> None:
    color = capture.parse_css_color("lab(49.6289 -23.2687 4.76264 / 0.08)")
    assert color is not None
    assert color[3] == pytest.approx(0.08, abs=0.01)
    assert _composite_over(color, (0.0, 0.0, 0.0)) == pytest.approx((6, 10, 9), abs=2)
    assert _composite_over(color, (1.0, 1.0, 1.0)) == pytest.approx((241, 245, 244), abs=2)

    color = capture.parse_css_color("oklab(0.909741 0.0000415742 0.0000181794 / 0.2)")
    assert color is not None
    assert color[3] == pytest.approx(0.2, abs=0.01)
    assert _composite_over(color, (0.0, 0.0, 0.0)) == pytest.approx((45, 45, 45), abs=2)
    assert _composite_over(color, (1.0, 1.0, 1.0)) == pytest.approx((249, 249, 249), abs=2)
