"""SVG mapping tests: path extraction into VECTOR nodes and the raster fallback."""

from __future__ import annotations

from typing import Any

from luvatrix_ui.figma.capture import compile_snapshots

from figma_capture_fixtures import SnapshotBuilder


def page() -> tuple[SnapshotBuilder, int]:
    b = SnapshotBuilder(title="Svg")
    body = b.element("BODY")
    b.layout(body, 0, 0, 393, 852, **{"background-color": "rgb(255, 255, 255)"})
    return b, body


def root_children(result: Any) -> list[dict[str, Any]]:
    return result.file["document"]["children"][0]["children"][0]["children"]


def icon_builder(paths: list[dict[str, str]] | None = None, *, extra_children: list[str] | None = None) -> SnapshotBuilder:
    b, body = page()
    svg = b.element("svg", parent=body, attrs={"width": "24", "height": "24"})
    b.layout(svg, 8, 8, 24, 24)
    for spec in paths or []:
        b.element("path", parent=svg, attrs=spec)
    for tag in extra_children or []:
        b.element(tag, parent=svg, attrs={})
    return b


def test_svg_paths_become_vector_nodes() -> None:
    b = icon_builder(
        [
            {"d": "M 2 2 L 22 22", "fill": "none", "stroke": "#e11d48", "stroke-width": "2"},
            {"d": "M 4 12 C 6 6 10 6 12 12", "fill": "rgb(59, 130, 246)"},
        ]
    )

    result = compile_snapshots([("/", b.build())])

    vectors = root_children(result)
    assert all(v["type"] == "VECTOR" and v["name"] == "svg:paths" for v in vectors)
    assert len(vectors) == 2
    line = vectors[0]
    assert line["strokes"] == [{"type": "SOLID", "color": {"r": 225 / 255, "g": 29 / 255, "b": 72 / 255, "a": 1.0}}]
    assert line["strokeWeight"] == 2
    assert "fills" not in line
    entry = line["vectorPaths"][0]
    assert entry["windingRule"] == "NONZERO"
    assert "L" in entry["data"]
    assert entry["data"] != entry.get("path") or "data" in entry
    curve = vectors[1]
    assert curve["fills"] == [{"type": "SOLID", "color": {"r": 59 / 255, "g": 130 / 255, "b": 246 / 255, "a": 1.0}}]
    # The vector bounding boxes stay inside the 24x24 svg box at (8, 8).
    for v in vectors:
        box = v["absoluteBoundingBox"]
        assert 8 <= box["x"] and box["x"] + box["width"] <= 32
        assert 8 <= box["y"] and box["y"] + box["height"] <= 32


def test_svg_viewbox_scales_path_coordinates() -> None:
    b, body = page()
    svg = b.element("svg", parent=body, attrs={"viewBox": "0 0 48 48", "width": "24", "height": "24"})
    b.layout(svg, 0, 0, 24, 24)
    b.element("path", parent=svg, attrs={"d": "M 0 0 L 48 48", "stroke": "black", "stroke-width": "2"})

    result = compile_snapshots([("/", b.build())])

    vector = root_children(result)[0]
    assert vector["absoluteBoundingBox"] == {"x": 0.0, "y": 0.0, "width": 24.0, "height": 24.0}
    data = vector["vectorPaths"][0]["data"]
    assert data.startswith("M 0 0 L 24 24")


def test_complex_svg_rasterizes_to_an_image_fill() -> None:
    b = icon_builder(
        [{"d": f"M {i} 0 L {i + 1} 1", "fill": "black"} for i in range(30)],
        extra_children=["filter"],
    )
    calls: list[dict[str, float]] = []

    def rasterize(box: dict[str, float]) -> bytes | None:
        calls.append(dict(box))
        return b"\x89PNG-raster"

    result = compile_snapshots([("/", b.build())], rasterize=rasterize)

    node = root_children(result)[0]
    assert node["name"] == "svg:raster"
    assert node["type"] == "RECTANGLE"
    fill = node["fills"][0]
    assert fill["type"] == "IMAGE"
    assert fill["scaleMode"] == "FILL"
    assert result.images[fill["imageRef"]]["data"] == b"\x89PNG-raster"
    assert calls == [{"x": 8.0, "y": 8.0, "width": 24.0, "height": 24.0}]
    assert result.report["pages"][0]["counts"].get("images", 0) >= 1


def test_complex_svg_without_a_rasterizer_falls_back_to_a_placeholder() -> None:
    b = icon_builder(
        [{"d": f"M {i} 0 L {i + 1} 1", "fill": "black"} for i in range(30)],
        extra_children=["filter"],
    )

    result = compile_snapshots([("/", b.build())])

    node = root_children(result)[0]
    assert node["name"] == "svg:raster"
    assert node["fills"][0]["type"] == "SOLID"
    page_report = result.report["pages"][0]
    assert page_report["counts"].get("svgPlaceholders", 0) == 1