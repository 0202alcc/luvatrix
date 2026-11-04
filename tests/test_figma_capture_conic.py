"""Conic-gradient mapping tests: GRADIENT_ANGULAR, repeats, raster fallback."""

from __future__ import annotations

from typing import Any

from luvatrix_ui.figma.capture import compile_snapshots

from figma_capture_fixtures import SnapshotBuilder


def page() -> tuple[SnapshotBuilder, int]:
    b = SnapshotBuilder(title="Conic")
    body = b.element("BODY")
    b.layout(body, 0, 0, 393, 852, **{"background-color": "rgb(255, 255, 255)"})
    return b, body


def first_child(result: Any) -> dict[str, Any]:
    return result.file["document"]["children"][0]["children"][0]["children"][0]


def test_plain_conic_maps_to_gradient_angular() -> None:
    b, body = page()
    donut = b.element("DIV", parent=body)
    b.layout(donut, 0, 0, 120, 120, **{"background-image": "conic-gradient(rgb(255, 0, 0), rgb(0, 0, 255))"})

    result = compile_snapshots([("/", b.build())])

    paint = first_child(result)["fills"][0]
    assert paint["type"] == "GRADIENT_ANGULAR"
    stops = paint["gradientStops"]
    assert [(s["position"], round(s["color"]["r"], 3), round(s["color"]["b"], 3)) for s in stops] == [
        (0.0, 1.0, 0.0),
        (1.0, 0.0, 1.0),
    ]
    center, start, sweep = paint["gradientHandlePositions"]
    assert (center["x"], center["y"]) == (0.5, 0.5)
    # CSS conic starts at 12 o'clock and sweeps clockwise.
    assert (round(start["x"], 6), round(start["y"], 6)) == (0.5, 0.0)
    assert (round(sweep["x"], 6), round(sweep["y"], 6)) == (1.0, 0.5)


def test_conic_from_angle_rotates_the_start_handle() -> None:
    b, body = page()
    donut = b.element("DIV", parent=body)
    b.layout(donut, 0, 0, 120, 120, **{"background-image": "conic-gradient(from 90deg, rgb(255, 0, 0), rgb(0, 0, 255))"})

    result = compile_snapshots([("/", b.build())])

    handles = first_child(result)["fills"][0]["gradientHandlePositions"]
    _center, start, sweep = handles
    assert (round(start["x"], 6), round(start["y"], 6)) == (1.0, 0.5)
    assert (round(sweep["x"], 6), round(sweep["y"], 6)) == (0.5, 1.0)


def test_conic_from_turn_and_degree_stop_positions() -> None:
    b, body = page()
    donut = b.element("DIV", parent=body)
    b.layout(
        donut,
        0,
        0,
        120,
        120,
        **{
            "background-image": "conic-gradient(from 0.25turn, rgb(255, 0, 0) 0deg, rgb(0, 0, 255) 180deg, rgb(255, 0, 0) 360deg)"
        },
    )

    result = compile_snapshots([("/", b.build())])

    paint = first_child(result)["fills"][0]
    assert paint["type"] == "GRADIENT_ANGULAR"
    assert [round(s["position"], 6) for s in paint["gradientStops"]] == [0.0, 0.5, 1.0]
    _center, start, _sweep = paint["gradientHandlePositions"]
    assert (round(start["x"], 6), round(start["y"], 6)) == (1.0, 0.5)


def test_repeating_conic_expands_small_segment_counts() -> None:
    b, body = page()
    donut = b.element("DIV", parent=body)
    b.layout(
        donut,
        0,
        0,
        120,
        120,
        **{"background-image": "repeating-conic-gradient(rgb(255, 0, 0) 0deg, rgb(0, 0, 255) 90deg)"},
    )

    result = compile_snapshots([("/", b.build())])

    paint = first_child(result)["fills"][0]
    assert paint["type"] == "GRADIENT_ANGULAR"
    stops = paint["gradientStops"]
    assert len(stops) == 8
    assert [round(s["position"], 6) for s in stops] == [0.0, 0.25, 0.25, 0.5, 0.5, 0.75, 0.75, 1.0]
    # Segments alternate red -> blue.
    assert stops[0]["color"]["r"] == 1.0 and stops[1]["color"]["b"] == 1.0
    assert stops[2]["color"]["r"] == 1.0 and stops[7]["color"]["b"] == 1.0


def test_repeating_conic_with_too_many_segments_rasterizes() -> None:
    b, body = page()
    donut = b.element("DIV", parent=body)
    b.layout(
        donut,
        0,
        0,
        120,
        120,
        **{"background-image": "repeating-conic-gradient(rgb(255, 0, 0) 0deg, rgb(0, 0, 255) 5deg)"},
    )

    result = compile_snapshots([("/", b.build())], rasterize=lambda box: b"png-raster")

    node = first_child(result)
    assert node["fills"][0]["type"] == "IMAGE"
    ref = node["fills"][0]["imageRef"]
    assert result.images[ref]["data"] == b"png-raster"


def test_repeating_conic_without_a_browser_falls_back_and_counts() -> None:
    b, body = page()
    donut = b.element("DIV", parent=body)
    b.layout(
        donut,
        0,
        0,
        120,
        120,
        **{"background-image": "repeating-conic-gradient(rgb(255, 0, 0) 0deg, rgb(0, 0, 255) 5deg)"},
    )

    result = compile_snapshots([("/", b.build())])

    node = first_child(result)
    assert node["fills"][0]["type"] == "SOLID"  # placeholder until a browser rasterizes it
    assert result.report["pages"][0]["unsupported"]["conic-repeat"] == 1


def test_conic_interpolation_hints_are_counted_not_silently_solid() -> None:
    b, body = page()
    donut = b.element("DIV", parent=body)
    b.layout(donut, 0, 0, 120, 120, **{"background-image": "conic-gradient(rgb(255, 0, 0), 40%, rgb(0, 0, 255))"})

    result = compile_snapshots([("/", b.build())])

    node = first_child(result)
    assert all(paint.get("type") != "GRADIENT_ANGULAR" for paint in node.get("fills") or ())
    assert result.report["pages"][0]["unsupported"]["conic-hints"] == 1


def test_conic_at_position_moves_the_center() -> None:
    b, body = page()
    donut = b.element("DIV", parent=body)
    b.layout(
        donut,
        0,
        0,
        120,
        120,
        **{"background-image": "conic-gradient(at 25% 75%, rgb(255, 0, 0), rgb(0, 0, 255))"},
    )

    result = compile_snapshots([("/", b.build())])

    center, _start, _sweep = first_child(result)["fills"][0]["gradientHandlePositions"]
    assert (center["x"], center["y"]) == (0.25, 0.75)


def test_conic_double_position_stops_expand() -> None:
    b, body = page()
    donut = b.element("DIV", parent=body)
    b.layout(
        donut,
        0,
        0,
        120,
        120,
        **{"background-image": "conic-gradient(rgb(255, 0, 0) 0deg 90deg, rgb(0, 0, 255) 90deg 180deg)"},
    )

    result = compile_snapshots([("/", b.build())])

    stops = first_child(result)["fills"][0]["gradientStops"]
    assert [round(s["position"], 6) for s in stops] == [0.0, 0.25, 0.25, 0.5]