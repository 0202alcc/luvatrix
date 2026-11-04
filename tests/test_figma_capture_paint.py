"""Paint mapping tests: gradients, images, borders, effects, blend, overflow."""

from __future__ import annotations

from typing import Any

from luvatrix_ui.figma.capture import compile_snapshots

from figma_capture_fixtures import SnapshotBuilder


def page() -> tuple[SnapshotBuilder, int]:
    b = SnapshotBuilder(title="Paint")
    body = b.element("BODY")
    b.layout(body, 0, 0, 393, 852, **{"background-color": "rgb(255, 255, 255)"})
    return b, body


def first_child(result: Any) -> dict[str, Any]:
    return result.file["document"]["children"][0]["children"][0]["children"][0]


def test_linear_gradient_maps_angle_and_stops() -> None:
    b, body = page()
    card = b.element("DIV", parent=body)
    b.layout(
        card,
        0,
        0,
        200,
        100,
        **{
            "background-image": "linear-gradient(135deg, rgb(255, 0, 0), rgb(0, 0, 255))",
            "background-color": "rgb(255, 255, 255)",
        },
    )

    result = compile_snapshots([("/", b.build())])

    fills = first_child(result)["fills"]
    assert fills[0]["type"] == "SOLID"
    gradient = fills[1]
    assert gradient["type"] == "GRADIENT_LINEAR"
    stops = gradient["gradientStops"]
    assert [(s["position"], round(s["color"]["r"], 3), round(s["color"]["b"], 3)) for s in stops] == [
        (0.0, 1.0, 0.0),
        (1.0, 0.0, 1.0),
    ]
    p0, p1, _width = gradient["gradientHandlePositions"]
    assert (round(p0["x"], 3), round(p0["y"], 3)) == (0.125, -0.25)
    assert (round(p1["x"], 3), round(p1["y"], 3)) == (0.875, 1.25)


def test_gradient_stops_with_explicit_positions() -> None:
    b, body = page()
    card = b.element("DIV", parent=body)
    b.layout(
        card,
        0,
        0,
        100,
        100,
        **{"background-image": "linear-gradient(90deg, rgb(255, 0, 0) 0%, rgb(255, 255, 0) 50%, rgb(0, 0, 255) 100%)"},
    )

    result = compile_snapshots([("/", b.build())])

    gradient = first_child(result)["fills"][0]
    assert [s["position"] for s in gradient["gradientStops"]] == [0.0, 0.5, 1.0]


def test_radial_gradient_maps_to_radial_paint() -> None:
    b, body = page()
    card = b.element("DIV", parent=body)
    b.layout(card, 0, 0, 100, 100, **{"background-image": "radial-gradient(circle, rgb(255, 0, 0), rgb(0, 0, 255))"})

    result = compile_snapshots([("/", b.build())])

    gradient = first_child(result)["fills"][0]
    assert gradient["type"] == "GRADIENT_RADIAL"
    handles = gradient["gradientHandlePositions"]
    assert (handles[0]["x"], handles[0]["y"]) == (0.5, 0.5)


def test_img_and_background_url_become_image_fills(tmp_path: Any) -> None:
    b, body = page()
    pic = b.element("IMG", parent=body, attrs={"src": "https://cdn.test/pic.png"})
    b.layout(pic, 0, 0, 64, 64)
    banner = b.element("DIV", parent=body)
    b.layout(banner, 0, 80, 393, 80, **{"background-image": 'url("https://cdn.test/banner.jpg")'})

    fetched: list[str] = []

    def fetcher(url: str) -> bytes | None:
        fetched.append(url)
        return b"\x89PNG-fake-" + url.encode()

    result = compile_snapshots([("/", b.build())], fetcher=fetcher)

    assert sorted(fetched) == ["https://cdn.test/banner.jpg", "https://cdn.test/pic.png"]
    children = result.file["document"]["children"][0]["children"][0]["children"]
    pic_fill = children[0]["fills"][0]
    assert pic_fill["type"] == "IMAGE"
    assert pic_fill["scaleMode"] == "FILL"
    ref = pic_fill["imageRef"]
    assert ref.startswith("img-")
    assert result.images[ref]["url"] == "https://cdn.test/pic.png"
    assert result.images[ref]["data"] == b"\x89PNG-fake-https://cdn.test/pic.png"
    assert children[1]["fills"][0]["type"] == "IMAGE"
    banner_ref = children[1]["fills"][0]["imageRef"]
    assert result.images[banner_ref]["url"] == "https://cdn.test/banner.jpg"


def test_failed_image_download_is_reported() -> None:
    b, body = page()
    pic = b.element("IMG", parent=body, attrs={"src": "https://cdn.test/missing.png"})
    b.layout(pic, 0, 0, 64, 64)

    result = compile_snapshots([("/", b.build())], fetcher=lambda url: None)

    node = first_child(result)
    assert node.get("fills") in (None, [])
    assert result.report["images"]["failed"] == ["https://cdn.test/missing.png"]


def test_borders_shadows_blend_and_opacity_map_to_figma_fields() -> None:
    b, body = page()
    card = b.element("DIV", parent=body)
    b.layout(
        card,
        0,
        0,
        200,
        100,
        **{
            "background-color": "rgb(255, 255, 255)",
            "border-top-width": "2px",
            "border-top-style": "dashed",
            "border-top-color": "rgb(0, 255, 0)",
            "border-right-width": "2px",
            "border-right-style": "dashed",
            "border-right-color": "rgb(0, 255, 0)",
            "border-bottom-width": "2px",
            "border-bottom-style": "dashed",
            "border-bottom-color": "rgb(0, 255, 0)",
            "border-left-width": "2px",
            "border-left-style": "dashed",
            "border-left-color": "rgb(0, 255, 0)",
            "box-shadow": "rgba(0, 0, 0, 0.3) 0px 4px 8px 0px",
            "opacity": "0.9",
            "mix-blend-mode": "multiply",
        },
    )

    result = compile_snapshots([("/", b.build())])

    node = first_child(result)
    assert node["strokes"] == [{"type": "SOLID", "color": {"r": 0.0, "g": 1.0, "b": 0.0, "a": 1.0}}]
    assert node["strokeWeight"] == 2
    assert node["strokeAlign"] == "INSIDE"
    assert node["strokeDashes"] == [6, 4]
    shadow = node["effects"][0]
    assert shadow["type"] == "DROP_SHADOW"
    assert shadow["offset"] == {"x": 0, "y": 4}
    assert shadow["radius"] == 8
    assert shadow["spread"] == 0
    assert shadow["color"]["a"] == 0.3
    assert node["opacity"] == 0.9
    assert node["blendMode"] == "MULTIPLY"


def test_per_side_borders_use_individual_stroke_weights() -> None:
    b, body = page()
    card = b.element("DIV", parent=body)
    b.layout(
        card,
        0,
        0,
        200,
        100,
        **{
            "border-top-width": "3px",
            "border-top-style": "solid",
            "border-top-color": "rgb(255, 0, 0)",
            "border-bottom-width": "3px",
            "border-bottom-style": "solid",
            "border-bottom-color": "rgb(255, 0, 0)",
        },
    )

    result = compile_snapshots([("/", b.build())])

    node = first_child(result)
    assert node["individualStrokeWeights"] == {
        "strokeTopWeight": 3,
        "strokeRightWeight": 0,
        "strokeBottomWeight": 3,
        "strokeLeftWeight": 0,
    }
    assert "strokeWeight" not in node


def test_inset_shadow_and_blur_filters_map_to_effects() -> None:
    b, body = page()
    panel = b.element("DIV", parent=body)
    b.layout(
        panel,
        0,
        0,
        200,
        100,
        **{
            "box-shadow": "inset 0px 2px 6px rgba(0, 0, 0, 0.2)",
            "backdrop-filter": "blur(4px)",
            "filter": "blur(2px)",
        },
    )

    result = compile_snapshots([("/", b.build())])

    effects = first_child(result)["effects"]
    kinds = {e["type"]: e for e in effects}
    assert kinds["INNER_SHADOW"]["offset"] == {"x": 0, "y": 2}
    assert kinds["INNER_SHADOW"]["radius"] == 6
    assert kinds["BACKGROUND_BLUR"]["radius"] == 4
    assert kinds["LAYER_BLUR"]["radius"] == 2


def test_scroll_containers_get_overflow_direction() -> None:
    b, body = page()
    feed = b.element("DIV", parent=body)
    b.layout(feed, 0, 0, 393, 400, **{"overflow-y": "auto", "overflow-x": "hidden"})
    for i in range(3):
        row = b.element("DIV", parent=feed)
        b.layout(row, 0, i * 200, 393, 200, **{"background-color": "rgb(240, 240, 240)"})

    result = compile_snapshots([("/", b.build())])

    node = first_child(result)
    assert node["overflowDirection"] == "VERTICAL_SCROLLING"
    assert node["clipsContent"] is True


def test_sticky_children_become_fixed_children() -> None:
    b, body = page()
    scroller = b.element("DIV", parent=body)
    b.layout(scroller, 0, 0, 393, 400, **{"overflow-y": "auto"})
    row = b.element("DIV", parent=scroller)
    b.layout(row, 0, 100, 393, 500, **{"background-color": "rgb(240, 240, 240)"})
    bar = b.element("DIV", parent=scroller)
    b.layout(bar, 0, 0, 393, 40, **{"position": "sticky", "background-color": "rgb(0, 0, 0)"})

    result = compile_snapshots([("/", b.build())])

    node = first_child(result)
    assert node["numberOfFixedChildren"] == 1
    assert node["children"][-1]["id"] == node["children"][-1]["id"]
    assert node["children"][-1]["absoluteBoundingBox"]["y"] == 0.0
    assert node["children"][0]["absoluteBoundingBox"]["y"] == 100.0