from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from luvatrix_ui.figma import FigmaDocument, render_frame

from figma_fixtures import node, single_frame, solid, two_screen_file

WHITE = (255, 255, 255, 255)
RED = (255, 0, 0, 255)


def _render(children, *, scale: float = 1.0, base_dir: Path | None = None, **frame_extra):
    doc = FigmaDocument.from_dict(single_frame(children, **frame_extra), base_dir=base_dir)
    return render_frame(doc, doc.start_frame_id, scale=scale)


def _px(img: np.ndarray, x: int, y: int) -> tuple[int, ...]:
    return tuple(int(v) for v in img[y, x])


def _close(actual, expected, tol: int = 3) -> bool:
    return all(abs(int(a) - int(e)) <= tol for a, e in zip(actual, expected))


def test_frame_renders_its_background_at_frame_size() -> None:
    img = _render([])

    assert img.shape == (100, 100, 4)
    assert img.dtype == np.uint8
    assert _px(img, 50, 50) == WHITE


def test_scale_multiplies_output_resolution() -> None:
    img = _render([node("1", "RECTANGLE", "R", 10, 10, 20, 20, fills=[solid(1, 0, 0)])], scale=2.0)

    assert img.shape == (200, 200, 4)
    assert _px(img, 40, 40) == RED
    assert _px(img, 15, 15) == WHITE


def test_two_screen_frames_render_relative_to_their_canvas_position() -> None:
    doc = FigmaDocument.from_dict(two_screen_file())

    img = render_frame(doc, "1:1")

    assert img.shape == (200, 100, 4)
    assert _px(img, 50, 165) == RED
    assert _px(img, 50, 100) == WHITE


def test_rounded_corners_leave_the_corner_pixel_uncovered() -> None:
    img = _render([node("1", "RECTANGLE", "R", 10, 10, 60, 60, fills=[solid(1, 0, 0)], cornerRadius=20)])

    assert _px(img, 11, 11) == WHITE
    assert _px(img, 40, 11) == RED
    assert _px(img, 40, 40) == RED


def test_per_corner_radii_are_respected() -> None:
    img = _render(
        [node("1", "RECTANGLE", "R", 10, 10, 60, 60, fills=[solid(1, 0, 0)], rectangleCornerRadii=[20, 0, 0, 0])]
    )

    assert _px(img, 11, 11) == WHITE
    assert _px(img, 68, 11) == RED


def test_edges_are_antialiased() -> None:
    img = _render([node("1", "ELLIPSE", "E", 10, 10, 80, 80, fills=[solid(0, 0, 0)])])
    values = {int(v) for v in img[50, :, 0]}

    assert any(0 < v < 255 for v in values)


def test_ellipse_covers_center_but_not_bounding_box_corner() -> None:
    img = _render([node("1", "ELLIPSE", "E", 10, 10, 80, 80, fills=[solid(1, 0, 0)])])

    assert _px(img, 50, 50) == RED
    assert _px(img, 12, 12) == WHITE


def test_node_and_paint_opacity_blend_over_the_background() -> None:
    img = _render(
        [
            node("1", "RECTANGLE", "A", 0, 0, 50, 50, fills=[solid(1, 0, 0)], opacity=0.5),
            node("2", "RECTANGLE", "B", 50, 0, 50, 50, fills=[solid(1, 0, 0, opacity=0.5)]),
        ]
    )

    assert _close(_px(img, 25, 25), (255, 128, 128, 255))
    assert _close(_px(img, 75, 25), (255, 128, 128, 255))


def test_group_opacity_applies_to_the_flattened_group() -> None:
    group = node(
        "g",
        "GROUP",
        "G",
        0,
        0,
        100,
        100,
        opacity=0.5,
        children=[
            node("1", "RECTANGLE", "A", 0, 0, 60, 60, fills=[solid(1, 0, 0)]),
            node("2", "RECTANGLE", "B", 40, 40, 60, 60, fills=[solid(1, 0, 0)]),
        ],
    )

    img = _render([group])

    assert _close(_px(img, 50, 50), _px(img, 20, 20))


def test_linear_gradient_interpolates_between_stops() -> None:
    gradient = {
        "type": "GRADIENT_LINEAR",
        "gradientHandlePositions": [{"x": 0, "y": 0.5}, {"x": 1, "y": 0.5}, {"x": 0, "y": 1}],
        "gradientStops": [
            {"position": 0, "color": {"r": 0, "g": 0, "b": 0, "a": 1}},
            {"position": 1, "color": {"r": 1, "g": 1, "b": 1, "a": 1}},
        ],
    }
    img = _render([node("1", "RECTANGLE", "G", 0, 0, 100, 100, fills=[gradient])])

    assert img[50, 1, 0] < 10
    assert img[50, 98, 0] > 245
    assert abs(int(img[50, 50, 0]) - 128) < 6


def test_radial_gradient_is_brightest_at_center() -> None:
    gradient = {
        "type": "GRADIENT_RADIAL",
        "gradientHandlePositions": [{"x": 0.5, "y": 0.5}, {"x": 1, "y": 0.5}, {"x": 0.5, "y": 1}],
        "gradientStops": [
            {"position": 0, "color": {"r": 1, "g": 1, "b": 1, "a": 1}},
            {"position": 1, "color": {"r": 0, "g": 0, "b": 0, "a": 1}},
        ],
    }
    img = _render([node("1", "RECTANGLE", "G", 0, 0, 100, 100, fills=[gradient])])

    assert img[50, 50, 0] > 245
    assert img[50, 99, 0] < 10


def test_vector_fill_geometry_is_filled() -> None:
    triangle = node(
        "1",
        "VECTOR",
        "Tri",
        0,
        0,
        100,
        100,
        fills=[solid(1, 0, 0)],
        fillGeometry=[{"path": "M0 100L50 0L100 100Z", "windingRule": "NONZERO"}],
    )

    img = _render([triangle])

    assert _px(img, 50, 80) == RED
    assert _px(img, 10, 10) == WHITE


def test_vector_paths_support_curves_and_relative_commands() -> None:
    blob = node(
        "1",
        "VECTOR",
        "Blob",
        0,
        0,
        100,
        100,
        fills=[solid(1, 0, 0)],
        fillGeometry=[{"path": "M10 50 C10 0 90 0 90 50 q0 40 -40 40 t-40 -40 z", "windingRule": "NONZERO"}],
    )

    img = _render([blob])

    assert _px(img, 50, 40) == RED
    assert _px(img, 2, 2) == WHITE


def test_evenodd_winding_cuts_holes() -> None:
    ring = node(
        "1",
        "VECTOR",
        "Ring",
        0,
        0,
        100,
        100,
        fills=[solid(1, 0, 0)],
        fillGeometry=[{"path": "M0 0H100V100H0Z M30 30H70V70H30Z", "windingRule": "EVENODD"}],
    )

    img = _render([ring])

    assert _px(img, 10, 10) == RED
    assert _px(img, 50, 50) == WHITE


def test_nonzero_winding_with_reversed_subpath_cuts_holes() -> None:
    ring = node(
        "1",
        "VECTOR",
        "Ring",
        0,
        0,
        100,
        100,
        fills=[solid(1, 0, 0)],
        fillGeometry=[{"path": "M0 0H100V100H0Z M30 30V70H70V30Z", "windingRule": "NONZERO"}],
    )

    img = _render([ring])

    assert _px(img, 10, 10) == RED
    assert _px(img, 50, 50) == WHITE


def test_clips_content_hides_overflowing_children() -> None:
    inner = node(
        "2",
        "FRAME",
        "Clip",
        0,
        0,
        50,
        50,
        fills=[],
        clipsContent=True,
        children=[node("3", "RECTANGLE", "Big", 0, 0, 100, 100, fills=[solid(1, 0, 0)])],
    )

    img = _render([inner])

    assert _px(img, 25, 25) == RED
    assert _px(img, 75, 75) == WHITE


def test_children_overflow_when_clipping_is_off() -> None:
    inner = node(
        "2",
        "FRAME",
        "NoClip",
        0,
        0,
        50,
        50,
        fills=[],
        clipsContent=False,
        children=[node("3", "RECTANGLE", "Big", 0, 0, 100, 100, fills=[solid(1, 0, 0)])],
    )

    img = _render([inner])

    assert _px(img, 75, 75) == RED


def test_inside_stroke_draws_a_border_without_fill() -> None:
    img = _render(
        [
            node(
                "1",
                "RECTANGLE",
                "Border",
                10,
                10,
                80,
                80,
                fills=[],
                strokes=[solid(1, 0, 0)],
                strokeWeight=4,
                strokeAlign="INSIDE",
            )
        ]
    )

    assert _px(img, 12, 50) == RED
    assert _px(img, 8, 50) == WHITE
    assert _px(img, 50, 50) == WHITE


def test_stroke_geometry_is_used_when_present() -> None:
    line = node(
        "1",
        "LINE",
        "Line",
        0,
        50,
        100,
        0,
        strokes=[solid(1, 0, 0)],
        strokeWeight=4,
        strokeGeometry=[{"path": "M0 -2H100V2H0Z", "windingRule": "NONZERO"}],
    )

    img = _render([line])

    assert _px(img, 50, 50) == RED
    assert _px(img, 50, 40) == WHITE


def test_line_without_stroke_geometry_is_still_drawn() -> None:
    line = node("1", "LINE", "Line", 0, 50, 100, 0, strokes=[solid(1, 0, 0)], strokeWeight=4)

    img = _render([line])

    assert _px(img, 50, 50) == RED
    assert _px(img, 50, 40) == WHITE


def test_drop_shadow_darkens_pixels_beside_the_shape() -> None:
    card = node(
        "1",
        "RECTANGLE",
        "Card",
        20,
        20,
        40,
        40,
        fills=[solid(1, 1, 1)],
        effects=[
            {
                "type": "DROP_SHADOW",
                "visible": True,
                "color": {"r": 0, "g": 0, "b": 0, "a": 0.5},
                "offset": {"x": 0, "y": 10},
                "radius": 4,
            }
        ],
    )

    img = _render([card])

    assert img[65, 40, 0] < 200
    assert _px(img, 40, 40) == WHITE
    assert _px(img, 90, 10) == WHITE


def test_relative_transform_rotates_nodes() -> None:
    bar = node("1", "RECTANGLE", "Bar", 0, 0, 10, 60, fills=[solid(1, 0, 0)])
    bar["size"] = {"x": 60, "y": 10}
    bar["relativeTransform"] = [[0, -1, 55], [1, 0, 20]]

    img = _render([bar])

    assert _px(img, 50, 50) == RED
    assert _px(img, 80, 25) == WHITE


def test_group_children_position_relative_to_the_containing_frame() -> None:
    child = node("2", "RECTANGLE", "Child", 60, 60, 20, 20, fills=[solid(1, 0, 0)])
    child["size"] = {"x": 20, "y": 20}
    child["relativeTransform"] = [[1, 0, 60], [0, 1, 60]]
    group = node("g", "GROUP", "G", 60, 60, 20, 20, children=[child])
    group["size"] = {"x": 20, "y": 20}
    group["relativeTransform"] = [[1, 0, 60], [0, 1, 60]]

    img = _render([group])

    assert _px(img, 70, 70) == RED
    assert _px(img, 30, 30) == WHITE


def test_text_draws_ink_inside_its_box_in_the_fill_color() -> None:
    text = node(
        "1",
        "TEXT",
        "Label",
        10,
        40,
        80,
        20,
        characters="Hello",
        fills=[solid(1, 0, 0)],
        style={"fontFamily": "Inter", "fontWeight": 700, "fontSize": 16, "lineHeightPx": 20, "textAlignHorizontal": "LEFT"},
    )

    img = _render([text])
    ink = (img[:, :, 1] < 128) & (img[:, :, 0] > 200)
    ys, xs = np.nonzero(ink)

    assert len(xs) > 30
    assert xs.min() >= 10 and xs.max() < 90
    assert ys.min() >= 40 and ys.max() < 60


def test_text_alignment_centers_the_line() -> None:
    def ink_center(align: str) -> float:
        text = node(
            "1",
            "TEXT",
            "Label",
            0,
            40,
            100,
            20,
            characters="Hi",
            fills=[solid(0, 0, 0)],
            style={"fontFamily": "Inter", "fontSize": 16, "lineHeightPx": 20, "textAlignHorizontal": align},
        )
        img = _render([text])
        xs = np.nonzero(img[:, :, 0] < 128)[1]
        return float(xs.mean())

    assert ink_center("LEFT") < 25
    assert abs(ink_center("CENTER") - 50) < 4
    assert ink_center("RIGHT") > 75


def test_text_wraps_to_the_box_width() -> None:
    text = node(
        "1",
        "TEXT",
        "Para",
        0,
        0,
        60,
        100,
        characters="one two three four five six",
        fills=[solid(0, 0, 0)],
        style={"fontFamily": "Inter", "fontSize": 12, "lineHeightPx": 16, "textAutoResize": "HEIGHT"},
    )

    img = _render([text])
    rows = np.nonzero((img[:, :, 0] < 128).any(axis=1))[0]

    assert np.nonzero((img[:, :, 0] < 128).any(axis=0))[0].max() < 62
    assert rows.max() - rows.min() > 30


def test_image_fill_is_loaded_from_the_images_directory(tmp_path: Path) -> None:
    (tmp_path / "images").mkdir()
    Image.new("RGBA", (8, 8), (0, 0, 255, 255)).save(tmp_path / "images" / "abc123.png")
    photo = node(
        "1",
        "RECTANGLE",
        "Photo",
        10,
        10,
        50,
        50,
        fills=[{"type": "IMAGE", "imageRef": "abc123", "scaleMode": "FILL"}],
    )

    img = _render([photo], base_dir=tmp_path)

    assert _px(img, 30, 30) == (0, 0, 255, 255)
    assert _px(img, 80, 80) == WHITE


def test_missing_image_renders_a_placeholder_instead_of_failing(tmp_path: Path) -> None:
    photo = node("1", "RECTANGLE", "Photo", 10, 10, 50, 50, fills=[{"type": "IMAGE", "imageRef": "missing"}])

    img = _render([photo], base_dir=tmp_path)

    assert _px(img, 30, 30) != WHITE


def test_invisible_paints_and_nodes_are_skipped() -> None:
    img = _render(
        [
            node("1", "RECTANGLE", "Hidden", 0, 0, 50, 50, visible=False, fills=[solid(1, 0, 0)]),
            node("2", "RECTANGLE", "HiddenPaint", 50, 50, 50, 50, fills=[{**solid(1, 0, 0), "visible": False}]),
        ]
    )

    assert _px(img, 25, 25) == WHITE
    assert _px(img, 75, 75) == WHITE


def test_mask_node_clips_following_siblings() -> None:
    mask = node("m", "ELLIPSE", "Mask", 0, 0, 100, 100, fills=[solid(0, 0, 0)], isMask=True)
    content = node("c", "RECTANGLE", "Content", 0, 0, 100, 100, fills=[solid(1, 0, 0)])
    group = node("g", "GROUP", "G", 0, 0, 100, 100, children=[mask, content])

    img = _render([group])

    assert _px(img, 50, 50) == RED
    assert _px(img, 2, 2) == WHITE


@pytest.mark.parametrize("bad", ["M0 0 X 10", "M0 0 L 10"])
def test_malformed_paths_are_ignored_not_fatal(bad: str) -> None:
    vec = node("1", "VECTOR", "Bad", 0, 0, 10, 10, fills=[solid(1, 0, 0)], fillGeometry=[{"path": bad}])

    img = _render([vec])

    assert img.shape == (100, 100, 4)
    assert math.isfinite(float(img.mean()))
