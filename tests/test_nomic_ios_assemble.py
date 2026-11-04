"""Pure-function tests for the nomic_ios capture assembler."""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "examples" / "nomic_ios"


def _load_assemble():
    spec = importlib.util.spec_from_file_location("nomic_ios_assemble", APP_DIR / "assemble_capture.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def asm():
    return _load_assemble()


def _png_bytes(rgb) -> bytes:
    import PIL.Image

    buf = io.BytesIO()
    PIL.Image.new("RGB", (4, 4), rgb).save(buf, format="PNG")
    return buf.getvalue()


def _text_node(chars: str, box: dict | None = None) -> dict:
    return {
        "id": "9:9",
        "type": "TEXT",
        "name": "span",
        "characters": chars,
        "absoluteBoundingBox": box or {"x": 0, "y": 0, "width": 10, "height": 10},
        "fills": [],
    }


def _frame(nodes: list[dict], *, clips: bool = False, box: dict | None = None) -> dict:
    return {
        "id": "1:0",
        "type": "FRAME",
        "name": "frame",
        "absoluteBoundingBox": box or {"x": 0, "y": 0, "width": 393, "height": 852},
        "clipsContent": clips,
        "children": nodes,
    }


# ── artifact filtering ────────────────────────────────────────────────────────


def test_css_declaration_text_is_flagged_as_an_artifact(asm) -> None:
    assert asm.is_css_artifact_text("position: absolute; border: 0px;")
    assert asm.is_css_artifact_text("position:absolute;pointer-events:none")
    assert asm.is_css_artifact_text("0.5px 0.5px")
    assert not asm.is_css_artifact_text("Site Photos")
    assert not asm.is_css_artifact_text("No. A-2455")
    assert not asm.is_css_artifact_text("Section 033000 allows ±1/2\" vertical and")


def test_drop_css_artifact_texts_removes_only_artifacts(asm) -> None:
    artifact = _text_node("position: absolute; border: 0px;")
    real = _text_node("Site Photos")
    payload = {"document": {"children": [{"children": [_frame([artifact, real])]}]}}

    removed = asm.drop_css_artifact_texts(payload)

    assert removed == 1
    survivors = payload["document"]["children"][0]["children"][0]["children"]
    assert survivors == [real]


# ── clip reconciliation ───────────────────────────────────────────────────────


def _screen_with(clip: dict) -> dict:
    """Wrap a candidate clip as a screen child (the assembler's real structure)."""
    tab_bar = _frame([], box={"x": 0.0, "y": 772.0, "width": 393.0, "height": 80.0})
    tab_bar["name"] = "Tab Bar"
    return _frame([clip, tab_bar], clips=True, box={"x": 0.0, "y": 0.0, "width": 393.0, "height": 991.0})


def test_reconcile_clips_skips_the_screen_shell(asm) -> None:
    text = _text_node("Riverfront Tower — Level 3 Framing Plan (Rev C).pdf", {"x": 72.0, "y": 99, "width": 354.0, "height": 18})
    tab_bar = _frame([], box={"x": 0.0, "y": 772.0, "width": 393.0, "height": 80.0})
    tab_bar["name"] = "Tab Bar"
    screen = _frame([tab_bar], clips=True, box={"x": 0.0, "y": 0.0, "width": 393.0, "height": 991.0})
    # A loose top-level text (no inner clip between it and the screen) must not
    # grow the screen itself.
    screen["children"].insert(0, text)

    asm.reconcile_clips({"document": {"children": [{"children": [screen]}]}})

    assert screen["absoluteBoundingBox"] == {"x": 0.0, "y": 0.0, "width": 393.0, "height": 991.0}


def test_reconcile_clips_grows_a_clip_to_cover_its_text(asm) -> None:
    text = _text_node("Facade Details Set R2.dwg", {"x": 80.09, "y": 0, "width": 178.9, "height": 18})
    clip = _frame([text], clips=True, box={"x": 85.0, "y": 0, "width": 183.0, "height": 20})

    fixed = asm.reconcile_clips({"document": {"children": [{"children": [_screen_with(clip)]}]}}, max_grow=40.0)

    assert fixed == 1
    box = clip["absoluteBoundingBox"]
    assert box["x"] == pytest.approx(80.09)
    assert box["width"] == pytest.approx(183.0 + 85.0 - 80.09)
    assert text["absoluteBoundingBox"]["x"] + text["absoluteBoundingBox"]["width"] <= box["x"] + box["width"]


def test_reconcile_clips_ignores_oversized_right_overflow(asm) -> None:
    text = _text_node("A very long truncated line", {"x": 72.0, "y": 0, "width": 354.0, "height": 18})
    clip = _frame([text], clips=True, box={"x": 85.0, "y": 0, "width": 183.0, "height": 20})

    asm.reconcile_clips({"document": {"children": [{"children": [_screen_with(clip)]}]}}, max_grow=40.0)

    box = clip["absoluteBoundingBox"]
    # The small left drift is reconciled; the large right overflow (real
    # truncation) stays untouched for the paint layer to ellipsize.
    assert box["x"] == pytest.approx(72.0)
    assert box["width"] == pytest.approx(183.0 + 13.0)
    assert box["y"] == 0 and box["height"] == 20


# ── palette ───────────────────────────────────────────────────────────────────


def test_sample_palette_picks_the_dark_and_accent_clusters(asm) -> None:
    dark = asm.sample_palette([_png_bytes((12, 12, 14)), _png_bytes((250, 250, 250))])
    assert dark["dark"] == (12, 12, 14)

    accent = asm.sample_palette([_png_bytes((94, 92, 230))])
    assert accent["accent"] == (94, 92, 230)


def test_sample_palette_falls_back_when_no_accent_exists(asm) -> None:
    plain = asm.sample_palette([_png_bytes((250, 250, 250))])
    assert plain["accent"] == asm.FALLBACK_ACCENT
    assert plain["dark"] == asm.FALLBACK_DARK


# ── tab bar construction ──────────────────────────────────────────────────────


def test_svg_paths_exist_for_every_tab_and_are_wellformed(asm) -> None:
    from luvatrix_ui.figma.geometry import parse_path

    for kind in ("assistant", "drive", "projects", "profile"):
        segments = parse_path(asm.tab_icon_path(kind))
        assert segments, f"icon path for {kind} parsed to no segments"
        assert segments[0][0][0] == "M"


def test_rounded_rect_path_is_a_closed_path(asm) -> None:
    path = asm.rounded_rect_path(0, 0, 24, 24, 6)
    assert path.startswith("M")
    assert path.rstrip().endswith("Z")


def test_build_tab_bar_marks_the_current_screen_active(asm) -> None:
    bar = asm.build_tab_bar_node(
        772.0,
        (12, 12, 14),
        (94, 92, 230),
        [
            ("Assistant", "assistant", "10:0"),
            ("Drive", "drive", "20:0"),
            ("Projects", "projects", "30:0"),
            ("Profile", "profile", "40:0"),
        ],
        active="drive",
    )

    drive_tab = bar["children"][1]
    assistant_tab = bar["children"][0]
    assert drive_tab["children"][0]["strokes"][0]["color"] == {"r": 94 / 255, "g": 92 / 255, "b": 230 / 255}
    assert drive_tab["children"][1]["style"]["fontWeight"] == 600
    assert assistant_tab["children"][0]["strokes"][0]["color"] == {"r": 152 / 255, "g": 152 / 255, "b": 159 / 255}
    assert assistant_tab["children"][1]["style"]["fontWeight"] == 500


def test_build_tab_bar_creates_four_tappable_tabs(asm) -> None:
    bar = asm.build_tab_bar_node(
        y=772.0,
        dark=(12, 12, 14),
        accent=(94, 92, 230),
        tabs=[
            ("Assistant", "assistant", "10:0"),
            ("Drive", "drive", "20:0"),
            ("Projects", "projects", "30:0"),
            ("Profile", "profile", "40:0"),
        ],
    )

    assert bar["type"] == "FRAME"
    assert bar["name"] == "Tab Bar"
    assert bar["absoluteBoundingBox"] == {"x": 0.0, "y": 772.0, "width": 393.0, "height": 80.0}
    assert len(bar["children"]) == 4
    names = [child["name"] for child in bar["children"]]
    assert names == ["Assistant Tab", "Drive Tab", "Projects Tab", "Profile Tab"]
    for child in bar["children"]:
        actions = child["interactions"][0]["actions"]
        assert actions[0]["type"] == "NODE"
        assert actions[0]["navigation"] == "NAVIGATE"
    destinations = [child["interactions"][0]["actions"][0]["destinationId"] for child in bar["children"]]
    assert destinations == ["10:0", "20:0", "30:0", "40:0"]
    for child in bar["children"]:
        kinds = [grandchild["type"] for grandchild in child["children"]]
        assert "VECTOR" in kinds
        labels = [g for g in child["children"] if g["type"] == "TEXT"]
        assert labels and labels[0]["characters"] == child["name"].removesuffix(" Tab")


# ── screen assembly ───────────────────────────────────────────────────────────


def _capture_frame() -> dict:
    return {
        "id": "1:0",
        "type": "FRAME",
        "name": "Nomic",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 393, "height": 852},
        "clipsContent": True,
        "fills": [{"type": "SOLID", "color": {"r": 1, "g": 1, "b": 1}, "opacity": 1}],
        "children": [_text_node("Hello")],
    }


def test_assemble_screen_places_content_below_the_status_clear(asm) -> None:
    tab_bar = asm.build_tab_bar_node(772.0, (12, 12, 14), (94, 92, 230), [("Drive", "drive", "20:0")])
    screen = asm.assemble_screen(_capture_frame(), name="Drive", tab_bar=tab_bar)

    assert screen["name"] == "Drive"
    # 852pt viewport + 139pt of reachable scroll so the content clears the bar.
    assert screen["absoluteBoundingBox"] == {"x": 0.0, "y": 0.0, "width": 393.0, "height": 991.0}
    assert screen["overflowDirection"] == "VERTICAL_SCROLLING"
    # The capture frame IS the screen; its content shifts below the status clear.
    assert screen["children"][0]["absoluteBoundingBox"]["y"] == asm.STATUS_CLEAR_PT
    # The bar pins to the bottom of the 852pt viewport, not the scrollable frame.
    assert tab_bar["absoluteBoundingBox"]["y"] == 852.0 - asm.TAB_BAR_HEIGHT_PT
    assert screen["children"][-1] is tab_bar


def test_assemble_screen_marks_the_tab_bar_as_the_fixed_child(asm) -> None:
    tab_bar = asm.build_tab_bar_node(772.0, (12, 12, 14), (94, 92, 230), [("Drive", "drive", "20:0")])
    screen = asm.assemble_screen(_capture_frame(), name="Drive", tab_bar=tab_bar)

    assert screen["numberOfFixedChildren"] == 1
    assert screen["children"][-1] is tab_bar
    icon = tab_bar["children"][0]["children"][0]
    assert icon["absoluteBoundingBox"]["y"] == 772.0 + 16.0


def test_screen_height_grows_only_when_content_needs_scrolling(asm) -> None:
    tab_bar = asm.build_tab_bar_node(772.0, (12, 12, 14), (94, 92, 230), [("Profile", "profile", "40:0")])
    short = _capture_frame()
    short["absoluteBoundingBox"]["height"] = 500

    screen = asm.assemble_screen(short, name="Profile", tab_bar=tab_bar)

    assert screen["absoluteBoundingBox"]["height"] == 852.0
    assert screen.get("overflowDirection", "NONE") == "NONE"
    # A short screen keeps the tab bar pinned to the viewport bottom.
    assert tab_bar["absoluteBoundingBox"]["y"] == 852.0 - asm.TAB_BAR_HEIGHT_PT


def test_session_row_hotspot_gets_a_friendly_name_and_navigation(asm) -> None:
    capture = _capture_frame()
    capture["children"].append(_text_node("Concrete spec questions", {"x": 24, "y": 400, "width": 200, "height": 20}))
    assistant = asm.assemble_screen(
        capture,
        name="Assistant",
        tab_bar=asm.build_tab_bar_node(772.0, (12, 12, 14), (94, 92, 230), [("Conversation", "assistant", "5:0")]),
    )
    wired = asm.wire_content_hotspot(assistant, "Concrete spec questions", "Conversation Link", "99:0")

    assert wired
    text = next(node for node in assistant["children"] if "Concrete spec" in node.get("characters", ""))
    actions = text["interactions"][0]["actions"]
    assert text["name"] == "Conversation Link"
    assert actions[0]["destinationId"] == "99:0"


def test_composer_mode_chip_gets_a_tappable_name(asm) -> None:
    capture = _capture_frame()
    capture["children"].append(_text_node("Auto", {"x": 300, "y": 745, "width": 40, "height": 18}))
    screen = asm.assemble_screen(
        capture,
        name="Assistant",
        tab_bar=asm.build_tab_bar_node(772.0, (12, 12, 14), (94, 92, 230), [("Drive", "drive", "20:0")]),
    )

    assert asm.rename_composer_chip(screen)

    chip = next(node for node in screen["children"] if node.get("characters") == "Auto")
    assert chip["name"] == "Mode Chip"


def test_org_switcher_button_is_dropped_from_the_drive_header(asm) -> None:
    capture = _capture_frame()
    switcher = {
        "id": "1:7",
        "type": "FRAME",
        "name": "button.data-[placeholder]:text-muted-foreground",
        "absoluteBoundingBox": {"x": 81, "y": 130, "width": 60, "height": 32},
        "children": [_text_node("Direct Upload logo")],
    }
    capture["children"].append(switcher)
    screen = asm.assemble_screen(
        capture,
        name="Drive",
        tab_bar=asm.build_tab_bar_node(772.0, (12, 12, 14), (94, 92, 230), [("Drive", "drive", "20:0")], active="drive"),
    )

    assert asm.drop_misplaced_header_widgets(screen) == 1
    assert all(node is not switcher for node in asm._walk_all(screen))


def test_merge_captures_renames_and_orders_frames(asm) -> None:
    frames = [
        ({"id": "S0:1:0", "type": "FRAME", "name": "Nomic", "absoluteBoundingBox": {"x": 0, "y": 0, "width": 393, "height": 852}, "children": []}, "Assistant"),
        ({"id": "S1:1:0", "type": "FRAME", "name": "Nomic", "absoluteBoundingBox": {"x": 0, "y": 0, "width": 393, "height": 852}, "children": []}, "Drive"),
    ]
    payload = asm.merge_captures(frames, title="Nomic iOS")

    canvas = payload["document"]["children"][0]
    assert canvas["name"] == "Nomic iOS"
    assert [f["name"] for f in canvas["children"]] == ["Assistant", "Drive"]
    assert canvas["flowStartingPoints"] == [{"nodeId": "S0:1:0", "name": "Start"}]


def test_remap_ids_makes_nested_nodes_unique_and_rewires_interactions(asm) -> None:
    node = {
        "id": "1:0",
        "type": "FRAME",
        "name": "Nomic",
        "children": [
            {
                "id": "1:5",
                "type": "TEXT",
                "name": "row",
                "interactions": [
                    {"trigger": {"type": "ON_CLICK"}, "actions": [{"type": "NODE", "destinationId": "2:0", "navigation": "NAVIGATE", "transition": None}]}
                ],
            }
        ],
    }

    asm.remap_ids(node, "A:")

    assert node["id"] == "A:1:0"
    assert node["children"][0]["id"] == "A:1:5"
    assert node["children"][0]["interactions"][0]["actions"][0]["destinationId"] == "A:2:0"