from __future__ import annotations

import numpy as np

from luvatrix_ui.figma import FigmaApp, FigmaDocument, VariantAction, render_frame

from figma_fixtures import variant_file
from test_figma_app import _FakeCtx, _tap


RED = (255, 0, 0, 255)
GREEN = (0, 255, 0, 255)
WHITE = (255, 255, 255, 255)


def _px(frame: np.ndarray, x: int, y: int) -> tuple[int, ...]:
    return tuple(int(v) for v in frame[y, x])


def test_document_parses_change_to_actions() -> None:
    doc = FigmaDocument.from_dict(variant_file())

    actions = {spot.node_name: spot.action for spot in doc.hotspots("4:1")}
    assert actions["Moisture Badge"] == VariantAction("5:2")


def test_component_sets_are_not_prototype_screens() -> None:
    doc = FigmaDocument.from_dict(variant_file())

    assert [frame.name for frame in doc.frames] == ["Detail"]


def test_variant_resolves_to_its_component_set_and_instances() -> None:
    doc = FigmaDocument.from_dict(variant_file())

    assert doc.component_set_of("5:2") == "5:0"
    instances = doc.instances_of_set("4:1", "5:0")
    assert [node.get("id") for node in instances] == ["4:2"]
    assert doc.component_set_of("4:1") is None


def test_instance_renders_its_variant_subtree() -> None:
    doc = FigmaDocument.from_dict(variant_file())

    img = render_frame(doc, "4:1")

    assert _px(img, 40, 40) == RED
    assert _px(img, 90, 90) == WHITE


def test_tapping_an_instance_swaps_the_variant_in_place() -> None:
    ctx = _FakeCtx(100, 100)
    app = FigmaApp(FigmaDocument.from_dict(variant_file()))
    app.init(ctx)
    app.loop(ctx, 0.016)

    _tap(ctx, 40, 40)
    app.loop(ctx, 0.016)

    assert app.current_frame_id == "4:1"
    assert _px(ctx.frames[-1], 40, 40) == GREEN
    assert _px(ctx.frames[-1], 5, 5) == WHITE

    app.loop(ctx, 0.016)
    assert len(ctx.frames) == 2


def test_variant_switch_is_scoped_to_one_instance() -> None:
    data = variant_file()
    frame = data["document"]["children"][0]["children"][1]
    second = dict(frame["children"][0])
    second["id"] = "4:3"
    second["name"] = "Other Badge"
    second["absoluteBoundingBox"] = {"x": 20, "y": 70, "width": 20, "height": 20}
    second.pop("interactions", None)
    frame["children"].append(second)
    ctx = _FakeCtx(100, 100)
    app = FigmaApp(FigmaDocument.from_dict(data))
    app.init(ctx)
    app.loop(ctx, 0.016)

    _tap(ctx, 40, 40)
    app.loop(ctx, 0.016)

    assert _px(ctx.frames[-1], 40, 40) == GREEN
    assert _px(ctx.frames[-1], 25, 75) == RED
