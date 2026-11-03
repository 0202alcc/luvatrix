from __future__ import annotations

import json
from pathlib import Path

import pytest

from luvatrix_ui.figma import BackAction, FigmaDocument, FigmaFormatError, NavigateAction

from figma_fixtures import navigate, node, single_frame, solid, two_screen_file


def test_start_frame_comes_from_flow_starting_point() -> None:
    doc = FigmaDocument.from_dict(two_screen_file())

    assert [frame.name for frame in doc.frames] == ["Detail", "Home"]
    assert doc.start_frame_id == "1:1"
    assert doc.frame("1:1").name == "Home"
    assert doc.frame_by_name("Detail").id == "2:1"


def test_start_frame_falls_back_to_first_top_level_frame() -> None:
    doc = FigmaDocument.from_dict(single_frame([]))

    assert doc.start_frame_id == "9:0"


def test_frame_geometry_is_relative_to_the_frame_origin() -> None:
    doc = FigmaDocument.from_dict(two_screen_file())
    home = doc.frame("1:1")

    assert (home.width, home.height) == (100.0, 200.0)
    hotspot = doc.hotspots("1:1")[0]
    assert hotspot.node_name == "Go Button"
    assert (hotspot.x, hotspot.y, hotspot.width, hotspot.height) == (10.0, 150.0, 80.0, 30.0)
    assert hotspot.action == NavigateAction("2:1")


def test_hotspots_include_back_and_legacy_transition_links() -> None:
    doc = FigmaDocument.from_dict(two_screen_file())

    actions = {spot.node_name: spot.action for spot in doc.hotspots("2:1")}

    assert actions == {"Back": BackAction(), "Legacy Link": NavigateAction("1:1")}


def test_hidden_nodes_are_not_hotspots() -> None:
    hidden = node("9:1", "RECTANGLE", "Ghost", 0, 0, 10, 10, visible=False, interactions=navigate("9:0"))
    doc = FigmaDocument.from_dict(single_frame([hidden]))

    assert doc.hotspots("9:0") == []


def test_hit_test_prefers_the_topmost_hotspot() -> None:
    under = node("9:1", "RECTANGLE", "Under", 0, 0, 50, 50, fills=[solid(1, 0, 0)], interactions=navigate("9:0"))
    over = node("9:2", "RECTANGLE", "Over", 10, 10, 20, 20, fills=[solid(0, 1, 0)], interactions=navigate("9:0"))
    doc = FigmaDocument.from_dict(single_frame([under, over]))

    assert doc.hit_test("9:0", 15, 15).node_name == "Over"
    assert doc.hit_test("9:0", 5, 5).node_name == "Under"
    assert doc.hit_test("9:0", 80, 80) is None


def test_navigation_to_a_child_node_resolves_to_its_top_level_frame() -> None:
    data = two_screen_file()
    home = data["document"]["children"][0]["children"][1]
    home["children"][0]["interactions"] = navigate("2:2")
    doc = FigmaDocument.from_dict(data)

    assert doc.hotspots("1:1")[0].action == NavigateAction("2:1")


def test_load_accepts_a_nodes_endpoint_payload(tmp_path: Path) -> None:
    file_payload = two_screen_file()
    home = file_payload["document"]["children"][0]["children"][1]
    payload = {"name": "Nodes", "nodes": {"1:1": {"document": home}}}
    path = tmp_path / "design.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    doc = FigmaDocument.load(path)

    assert doc.start_frame_id == "1:1"
    assert doc.base_dir == tmp_path


def test_rejects_payload_without_frames() -> None:
    with pytest.raises(FigmaFormatError, match="no top-level frames"):
        FigmaDocument.from_dict({"document": {"id": "0:0", "type": "DOCUMENT", "children": []}})


def test_rejects_unknown_start_frame() -> None:
    with pytest.raises(FigmaFormatError, match="Nope"):
        FigmaDocument.from_dict(two_screen_file(), start="Nope")


def test_start_can_be_chosen_by_name() -> None:
    doc = FigmaDocument.from_dict(two_screen_file(), start="Detail")

    assert doc.start_frame_id == "2:1"
