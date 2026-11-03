"""2D CSS transform mapping tests: matrices, origins, nested composition."""

from __future__ import annotations

import math
from typing import Any

from luvatrix_ui.figma.capture import compile_snapshots
from luvatrix_ui.figma.geometry import Affine

from figma_capture_fixtures import SnapshotBuilder

ROTATE_90 = "matrix(0, 1, -1, 0, 0, 0)"


def page() -> tuple[SnapshotBuilder, int]:
    b = SnapshotBuilder(title="Transforms")
    body = b.element("BODY")
    b.layout(body, 0, 0, 393, 852, **{"background-color": "rgb(255, 255, 255)"})
    return b, body


def first_child(result: Any) -> dict[str, Any]:
    return result.file["document"]["children"][0]["children"][0]["children"][0]


def rows(node: dict[str, Any]) -> list[list[float]]:
    return node["relativeTransform"]


def close_rows(actual: list[list[float]], expected: list[list[float]]) -> None:
    for row_a, row_b in zip(actual, expected):
        for a, b in zip(row_a, row_b):
            assert abs(a - b) < 1e-6, (actual, expected)


def as_affine(node: dict[str, Any]) -> Affine:
    return Affine.from_figma(rows(node))


def test_rotation_recomputes_the_pre_transform_box() -> None:
    b, body = page()
    card = b.element("DIV", parent=body)
    # A 100x50 card at (10, 20) rotated 90deg has a 50x100 AABB centered on the
    # same point: [35, -5, 50, 100].
    b.layout(
        card,
        35,
        -5,
        50,
        100,
        **{"background-color": "rgb(37, 99, 235)", "transform": ROTATE_90, "transform-origin": "50px 25px"},
    )

    result = compile_snapshots([("/", b.build())])

    node = first_child(result)
    assert node["size"] == {"x": 100, "y": 50}
    assert node["absoluteBoundingBox"] == {"x": 10.0, "y": 20.0, "width": 100.0, "height": 50.0}
    # local (0,0) lands at (85, -5); local (100, 50) at (35, 95).
    close_rows(rows(node), [[0.0, -1.0, 85.0], [1.0, 0.0, -5.0]])
    assert result.report["pages"][0]["counts"]["transforms"] == 1


def test_translation_keeps_the_base_box_and_shifts_the_transform() -> None:
    b, body = page()
    card = b.element("DIV", parent=body)
    b.layout(
        card,
        10,
        20,
        100,
        50,
        **{"background-color": "rgb(37, 99, 235)", "transform": "matrix(1, 0, 0, 1, 10, 20)", "transform-origin": "0px 0px"},
    )

    result = compile_snapshots([("/", b.build())])

    node = first_child(result)
    assert node["size"] == {"x": 100, "y": 50}
    assert node["absoluteBoundingBox"] == {"x": 0.0, "y": 0.0, "width": 100.0, "height": 50.0}
    close_rows(rows(node), [[1.0, 0.0, 10.0], [0.0, 1.0, 20.0]])


def test_skew_x_recovers_the_unskewed_width() -> None:
    b, body = page()
    card = b.element("DIV", parent=body)
    # 100x50 skewed 30deg: AABB width = 100 + tan(30deg)*50 = 128.87.
    b.layout(
        card,
        0,
        0,
        128.87,
        50,
        **{"background-color": "rgb(37, 99, 235)", "transform": "matrix(1, 0, 0.57735, 1, 0, 0)", "transform-origin": "0px 0px"},
    )

    result = compile_snapshots([("/", b.build())])

    node = first_child(result)
    assert abs(node["size"]["x"] - 100.0) < 0.01
    assert abs(node["size"]["y"] - 50.0) < 1e-6
    tf = as_affine(node)
    assert abs(tf.c - 0.57735) < 1e-4
    assert abs(tf.tx) < 1e-6


def test_child_of_rotated_frame_is_expressed_in_parent_local_space() -> None:
    b, body = page()
    card = b.element("DIV", parent=body)
    # 200x100 card at (0,0) rotated 90deg: AABB [50, -50, 100, 200].
    b.layout(
        card,
        50,
        -50,
        100,
        200,
        **{"background-color": "rgb(245, 245, 245)", "transform": ROTATE_90, "transform-origin": "100px 50px"},
    )
    chip = b.element("DIV", parent=card)
    # Base-local (20, 10) 60x30 chip maps under the rotation to AABB [110, -30, 30, 60].
    b.layout(chip, 110, -30, 30, 60, **{"background-color": "rgb(37, 99, 235)"})

    result = compile_snapshots([("/", b.build())])

    frame = first_child(result)
    node = frame["children"][0]
    assert node["id"] == "1:9002"
    assert node["type"] in {"RECTANGLE", "FRAME"}
    assert node["size"] == {"x": 60, "y": 30}
    assert node["absoluteBoundingBox"] == {"x": 20.0, "y": 10.0, "width": 60.0, "height": 30.0}
    close_rows(rows(node), [[1.0, 0.0, 20.0], [0.0, 1.0, 10.0]])


def test_matrix3d_falls_back_to_the_projected_aabb() -> None:
    b, body = page()
    card = b.element("DIV", parent=body)
    b.layout(
        card,
        0,
        0,
        120,
        80,
        **{
            "background-color": "rgb(37, 99, 235)",
            "transform": "matrix3d(0.866, 0.5, 0, 0, -0.5, 0.866, 0, 0, 0, 0, 1, 0, 10, 20, 0, 1)",
        },
    )

    result = compile_snapshots([("/", b.build())])

    node = first_child(result)
    assert "relativeTransform" not in node
    assert "size" not in node
    assert node["absoluteBoundingBox"] == {"x": 0.0, "y": 0.0, "width": 120.0, "height": 80.0}
    assert result.report["pages"][0]["unsupported"]["transform3d"] == 1


def test_singular_45deg_rotation_falls_back_to_the_aabb() -> None:
    b, body = page()
    card = b.element("DIV", parent=body)
    s = math.sqrt(0.5)
    b.layout(
        card,
        0,
        0,
        141.42,
        141.42,
        **{"background-color": "rgb(37, 99, 235)", "transform": f"matrix({s}, {s}, {-s}, {s}, 0, 0)"},
    )

    result = compile_snapshots([("/", b.build())])

    node = first_child(result)
    assert "relativeTransform" not in node
    assert node["absoluteBoundingBox"]["width"] == 141.42
    assert result.report["pages"][0]["unsupported"]["transform-aabb"] == 1


def test_transformed_text_node_keeps_its_rotation() -> None:
    b, body = page()
    label = b.element("DIV", parent=body)
    b.layout(
        label,
        35,
        -5,
        50,
        100,
        **{"transform": ROTATE_90, "transform-origin": "50px 25px", "color": "rgb(23, 23, 23)"},
    )
    t = b.text("Vertical", parent=label)
    li = b.layout(t, 35, 20, 50, 20)
    b.text_box(li, 35, 20, 50, 20)

    result = compile_snapshots([("/", b.build())])

    text = first_child(result)
    assert text["type"] == "TEXT"
    assert "relativeTransform" in text
    tf = as_affine(text)
    assert abs(tf.b - 1.0) < 1e-6  # text inherits the parent's 90deg rotation
    assert text["style"]["fontSize"] == 16


def test_identity_transform_is_not_decorated() -> None:
    b, body = page()
    card = b.element("DIV", parent=body)
    b.layout(
        card,
        0,
        0,
        100,
        50,
        **{"background-color": "rgb(37, 99, 235)", "transform": "matrix(1, 0, 0, 1, 0, 0)"},
    )

    result = compile_snapshots([("/", b.build())])

    node = first_child(result)
    assert "relativeTransform" not in node
    assert "size" not in node
    assert result.report["pages"][0]["counts"].get("transforms", 0) == 0


def test_renderer_rotates_a_captured_node() -> None:
    from luvatrix_ui.figma.document import FigmaDocument
    from luvatrix_ui.figma.render import FigmaRenderer

    b, body = page()
    card = b.element("DIV", parent=body)
    b.layout(
        card,
        35,
        -5,
        50,
        100,
        **{"background-color": "rgb(255, 0, 0)", "transform": ROTATE_90, "transform-origin": "50px 25px"},
    )
    result = compile_snapshots([("/", b.build())])

    import json
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "file.json"
        path.write_text(json.dumps(result.file), encoding="utf-8")
        doc = FigmaDocument.load(path)
        frame_id = doc.frames[0].id
        image = FigmaRenderer(doc).render(frame_id, 1.0, background=(1, 1, 1, 1), only_ids={frame_id, "1:9001"})

    # The red 100x50 card rotated 90deg covers a 50x100 region centered at (60, 45).
    center = image[45, 60]
    assert center[0] > 200 and center[3] > 200  # red, opaque
    corner = image[5, 5]
    assert corner[1] > 240 and corner[2] > 240  # white background, not the red card