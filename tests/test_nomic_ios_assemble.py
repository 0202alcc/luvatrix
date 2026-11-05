"""Pure-function tests for the nomic_ios capture assembler."""

from __future__ import annotations

import importlib.util
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
        "absoluteBoundingBox": box or {"x": 0, "y": 0, "width": 402, "height": 874},
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


def test_sr_only_text_is_dropped(asm) -> None:
    # Screen-reader-only spans render as clipped ink fragments inside their
    # tiny buttons (the "..." blob under the sidebar toggle): the web hides
    # them, so the assembler must too.
    sr = _text_node("Toggle Sidebar")
    sr["name"] = "span.sr-only"
    real = _text_node("Home")
    payload = {"document": {"children": [{"children": [_frame([sr, real])]}]}}

    removed = asm.drop_sr_only_texts(payload)

    assert removed == 1
    survivors = payload["document"]["children"][0]["children"][0]["children"]
    assert survivors == [real]


# ── dark icon recolor ─────────────────────────────────────────────────────────


def _black_icon(box: dict | None = None) -> dict:
    return {
        "id": "8:8",
        "type": "VECTOR",
        "name": "svg:paths",
        "absoluteBoundingBox": box or {"x": 20, "y": 80, "width": 13, "height": 11},
        "fills": [{"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0}, "opacity": 1}],
        "strokes": [],
    }


def test_dark_icon_recolor_turns_black_glyphs_light(asm) -> None:
    # The dark capture leaves currentColor svg glyphs pure black, which is
    # invisible on the gray-900 canvas (measured 1.1:1). They map to the same
    # gray-100 the capture uses for dark foreground text.
    icon = _black_icon()
    screen = _frame([icon])

    assert asm.recolor_dark_icons(screen) == 1
    assert _rgb(icon["fills"][0]) == (241, 241, 234)


def test_dark_icon_recolor_keeps_glyphs_on_colorful_surfaces_black(asm) -> None:
    # Glyphs on teal buttons (Dictate, Upload) are black on both appearances on
    # the real site; recoloring them white would break the button.
    mic = _black_icon()
    button = _frame([mic], box={"x": 300, "y": 250, "width": 40, "height": 40})
    button["fills"] = [{"type": "SOLID", "color": {"r": 72 / 255, "g": 129 / 255, "b": 109 / 255}, "opacity": 1}]
    screen = _frame([button])

    assert asm.recolor_dark_icons(screen) == 0
    assert _rgb(mic["fills"][0]) == (0, 0, 0)


def test_dark_icon_recolor_leaves_themed_gray_glyphs_alone(asm) -> None:
    icon = _black_icon()
    icon["fills"] = [{"type": "SOLID", "color": {"r": 145 / 255, "g": 148 / 255, "b": 146 / 255}, "opacity": 1}]
    screen = _frame([icon])

    assert asm.recolor_dark_icons(screen) == 0
    assert _rgb(icon["fills"][0]) == (145, 148, 146)


def test_dark_icon_recolor_sees_through_fill_free_wrappers(asm) -> None:
    # Header icons sit inside borderless buttons; only a colorful ancestor
    # suppresses the recolor.
    icon = _black_icon()
    wrapper = _frame([icon], box={"x": 16, "y": 78, "width": 28, "height": 32})
    screen = _frame([wrapper])

    assert asm.recolor_dark_icons(screen) == 1
    assert _rgb(icon["fills"][0]) == (241, 241, 234)


# ── clip reconciliation ───────────────────────────────────────────────────────


def _screen_with(clip: dict) -> dict:
    """Wrap a candidate clip as a screen child (the assembler's real structure)."""
    tab_bar = _frame([], box={"x": 16.0, "y": 778.0, "width": 370.0, "height": 62.0})
    tab_bar["name"] = "Tab Bar"
    return _frame([clip, tab_bar], clips=True, box={"x": 0.0, "y": 0.0, "width": 402.0, "height": 1032.0})


def test_reconcile_clips_skips_the_screen_shell(asm) -> None:
    text = _text_node("Riverfront Tower — Level 3 Framing Plan (Rev C).pdf", {"x": 72.0, "y": 99, "width": 354.0, "height": 18})
    tab_bar = _frame([], box={"x": 16.0, "y": 778.0, "width": 370.0, "height": 62.0})
    tab_bar["name"] = "Tab Bar"
    screen = _frame([tab_bar], clips=True, box={"x": 0.0, "y": 0.0, "width": 402.0, "height": 1032.0})
    # A loose top-level text (no inner clip between it and the screen) must not
    # grow the screen itself.
    screen["children"].insert(0, text)

    asm.reconcile_clips({"document": {"children": [{"children": [screen]}]}})

    assert screen["absoluteBoundingBox"] == {"x": 0.0, "y": 0.0, "width": 402.0, "height": 1032.0}


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


# ── tab bar construction ──────────────────────────────────────────────────────

TABS = [
    ("Assistant", "assistant", "10:0"),
    ("Drive", "drive", "20:0"),
    ("Projects", "projects", "30:0"),
    ("Profile", "profile", "40:0"),
]


def _bar(asm, active: str | None = "drive", **kwargs) -> dict:
    return asm.build_tab_bar_node(TABS, active=active, **kwargs)


def _box(node: dict) -> tuple[float, float, float, float]:
    b = node["absoluteBoundingBox"]
    return b["x"], b["y"], b["width"], b["height"]


def _tab_parts(tab: dict) -> dict[str, dict]:
    return {child["name"]: child for child in tab["children"]}


def _rgb(paint: dict) -> tuple[int, int, int]:
    c = paint["color"]
    return round(c["r"] * 255), round(c["g"] * 255), round(c["b"] * 255)


def test_frame_matches_the_iphone_17_viewport_and_safe_areas(asm) -> None:
    assert (asm.FRAME_W, asm.VIEWPORT_H) == (402.0, 874.0)
    assert asm.STATUS_CLEAR_PT == 62.0
    assert asm.HOME_INDICATOR_PT == 34.0


def test_svg_paths_exist_for_every_tab_and_are_wellformed(asm) -> None:
    from luvatrix_ui.figma.geometry import parse_path

    for kind in ("assistant", "drive", "projects", "profile"):
        segments = parse_path(asm.tab_icon_path(kind))
        assert segments, f"icon path for {kind} parsed to no segments"
        assert segments[0][0][0] == "M"
    with pytest.raises(ValueError):
        asm.tab_icon_path("settings")


def test_rounded_rect_path_is_a_closed_path(asm) -> None:
    path = asm.rounded_rect_path(0, 0, 24, 24, 6)
    assert path.startswith("M")
    assert path.rstrip().endswith("Z")


def test_tab_bar_is_a_floating_capsule_above_the_home_indicator(asm) -> None:
    bar = _bar(asm)
    x, y, w, h = _box(bar)

    assert x > 0 and x + w < asm.FRAME_W
    assert x == pytest.approx(asm.FRAME_W - (x + w))
    assert bar["cornerRadius"] == pytest.approx(h / 2)
    assert y + h <= asm.VIEWPORT_H - asm.HOME_INDICATOR_PT
    for node in asm._walk_all(bar):
        nx, ny, nw, nh = _box(node)
        assert ny + nh <= asm.VIEWPORT_H - asm.HOME_INDICATOR_PT, node["name"]


def test_tab_bar_approximates_regular_liquid_glass(asm) -> None:
    bar = _bar(asm)

    fills = bar["fills"]
    assert len(fills) == 1 and fills[0]["type"] == "SOLID"
    assert _rgb(fills[0]) == (250, 250, 249), "light glass tint is the Nomic gray-50 canvas"
    assert 0.0 < fills[0]["opacity"] < 1.0
    blurs = [e for e in bar["effects"] if e["type"] == "BACKGROUND_BLUR"]
    assert blurs and blurs[0]["radius"] > 0
    assert bar["strokes"], "glass needs a highlight edge to separate it from light content"


def test_build_tab_bar_creates_four_tappable_tabs(asm) -> None:
    bar = _bar(asm, active=None)

    assert bar["type"] == "FRAME"
    assert bar["name"] == "Tab Bar"
    names = [child["name"] for child in bar["children"]]
    assert names == ["Assistant Tab", "Drive Tab", "Projects Tab", "Profile Tab"]
    destinations = [child["interactions"][0]["actions"][0]["destinationId"] for child in bar["children"]]
    assert destinations == ["10:0", "20:0", "30:0", "40:0"]
    for tab in bar["children"]:
        action = tab["interactions"][0]["actions"][0]
        assert action["type"] == "NODE" and action["navigation"] == "NAVIGATE"
        _x, _y, w, h = _box(tab)
        assert w >= 44 and h >= 44
        label = _tab_parts(tab)["label"]
        assert label["characters"] == tab["name"].removesuffix(" Tab")


def test_tabs_share_the_capsule_without_overlapping(asm) -> None:
    bar = _bar(asm)
    bx, by, bw, bh = _box(bar)
    edges = []
    for tab in bar["children"]:
        x, y, w, h = _box(tab)
        assert bx <= x and x + w <= bx + bw + 1e-6
        assert by <= y and y + h <= by + bh + 1e-6
        edges.append((x, x + w))
    for (_, right), (left, _) in zip(edges, edges[1:]):
        assert right <= left + 1e-6


def test_tab_icons_are_filled_glyphs(asm) -> None:
    for tab in _bar(asm)["children"]:
        icon = _tab_parts(tab)["icon"]
        assert icon["type"] == "VECTOR"
        assert icon["fills"] and not icon.get("strokes")
        assert icon["vectorPaths"][0]["windingRule"] in {"NONZERO", "EVENODD"}


def test_tab_labels_meet_the_ios_minimum_size(asm) -> None:
    for tab in _bar(asm)["children"]:
        assert _tab_parts(tab)["label"]["style"]["fontSize"] >= 11


def test_selected_tab_uses_the_teal_accent_and_unselected_stays_gray(asm) -> None:
    # Apple's tab bars carry selection with a single accent tint on the symbol
    # and label [S-TABBARS], [S-COLOR]. The light accent is teal-600, the same
    # token the product uses for its active sidebar item on a light canvas
    # (oklch(55.8% 0.068 169) = sRGB 73,129,109; 4.3:1 on gray-50, on par with
    # Apple's own system-blue labels). Unselected tabs stay monochrome gray-500.
    bar = _bar(asm, active="drive")
    colors = set()
    for tab in bar["children"]:
        parts = _tab_parts(tab)
        icon_rgb = _rgb(parts["icon"]["fills"][0])
        label_rgb = _rgb(parts["label"]["fills"][0])
        assert icon_rgb == label_rgb, "one color per tab state"
        colors.add(icon_rgb)
    assert colors == {(73, 129, 109), (77, 82, 79)}
    selected = _rgb(_tab_parts(bar["children"][1])["icon"]["fills"][0])
    unselected = _rgb(_tab_parts(bar["children"][0])["icon"]["fills"][0])
    assert selected == (73, 129, 109)
    assert unselected == (77, 82, 79)


def test_selection_is_the_accent_tint_not_a_pill(asm) -> None:
    # iOS tab bars have no selection pill; tint and label weight carry the
    # state [S-TABBARS].
    bar = _bar(asm, active="drive")
    tabs = {tab["name"]: _tab_parts(tab) for tab in bar["children"]}

    for parts in tabs.values():
        assert "selection" not in parts, "no selection pill in an iOS tab bar"
    assert tabs["Drive Tab"]["label"]["style"]["fontWeight"] > tabs["Assistant Tab"]["label"]["style"]["fontWeight"]


# ── dark appearance ───────────────────────────────────────────────────────────


def test_dark_tab_bar_keeps_the_light_geometry(asm) -> None:
    light = _bar(asm)
    dark = _bar(asm, appearance="dark")

    assert _box(dark) == _box(light)
    assert dark["cornerRadius"] == light["cornerRadius"]
    for light_tab, dark_tab in zip(light["children"], dark["children"]):
        assert _box(dark_tab) == _box(light_tab)
        for light_part, dark_part in zip(light_tab["children"], dark_tab["children"]):
            assert _box(dark_part) == _box(light_part)


def test_dark_tab_bar_uses_a_dark_translucent_tint(asm) -> None:
    bar = _bar(asm, appearance="dark")

    fills = bar["fills"]
    assert len(fills) == 1 and fills[0]["type"] == "SOLID"
    assert _rgb(fills[0]) == (25, 29, 26), "dark glass tint is the teal-leaning Nomic gray-900, never blue or black"
    assert max(_rgb(fills[0])) < 80, "dark glass tints the bar, not lightens it"
    assert 0.0 < fills[0]["opacity"] < 1.0
    blurs = [e for e in bar["effects"] if e["type"] == "BACKGROUND_BLUR"]
    assert blurs and blurs[0]["radius"] > 0


def test_dark_selected_tab_uses_teal_400_and_unselected_stays_gray(asm) -> None:
    # The dark accent is teal-400 (122, 167, 151): 6.3:1 on the gray-900 glass,
    # well past the 4.5:1 text minimum [S-ACCESSIBILITY]. Unselected tabs keep
    # the gray-400 token; both grays lean teal, never neutral.
    bar = _bar(asm, active="drive", appearance="dark")
    colors = set()
    for tab in bar["children"]:
        parts = _tab_parts(tab)
        icon_rgb = _rgb(parts["icon"]["fills"][0])
        label_rgb = _rgb(parts["label"]["fills"][0])
        assert icon_rgb == label_rgb, "one color per tab state"
        colors.add(icon_rgb)
    assert colors == {(122, 167, 151), (145, 148, 146)}
    assert min(rgb[0] for rgb in colors) >= 120, "dark-mode bar symbols stay legible on dark glass"
    selected = _rgb(_tab_parts(bar["children"][1])["icon"]["fills"][0])
    unselected = _rgb(_tab_parts(bar["children"][0])["icon"]["fills"][0])
    assert selected == (122, 167, 151)
    assert unselected == (145, 148, 146)


def test_dark_selection_is_also_pill_free(asm) -> None:
    for appearance in ("light", "dark"):
        bar = _bar(asm, active="drive", appearance=appearance)
        for tab in bar["children"]:
            parts = _tab_parts(tab)
            assert "selection" not in parts, appearance


def test_dark_scroll_edge_fades_from_the_dark_screen_background(asm) -> None:
    capture = _capture_frame()
    capture["fills"] = [{"type": "SOLID", "color": {"r": 0.06, "g": 0.06, "b": 0.07}, "opacity": 1}]
    screen = asm.assemble_screen(capture, name="Drive", tab_bar=_bar(asm, appearance="dark"), appearance="dark")

    edge = screen["children"][-2]
    paint = edge["fills"][0]
    assert paint["type"] == "GRADIENT_LINEAR"
    first = paint["gradientStops"][0]["color"]
    assert max(first["r"], first["g"], first["b"]) < 0.2, "the fade matches the dark background"
    assert first["a"] == 1.0
    assert paint["gradientStops"][-1]["color"]["a"] == 0.0


def test_scroll_edge_falls_back_to_the_theme_canvas_without_a_screen_fill(asm) -> None:
    screen = _capture_frame()
    screen["fills"] = []
    for appearance, expected in (("light", (0.980, 0.980, 0.976)), ("dark", (0.098, 0.114, 0.102))):
        edge = asm.build_scroll_edge_node(screen, appearance=appearance)
        first = edge["fills"][0]["gradientStops"][0]["color"]
        assert (first["r"], first["g"], first["b"]) == (
            pytest.approx(expected[0], abs=1e-3),
            pytest.approx(expected[1], abs=1e-3),
            pytest.approx(expected[2], abs=1e-3),
        ), appearance


def test_main_writes_light_and_dark_design_documents(asm, tmp_path, monkeypatch) -> None:
    import json
    import sys

    keys = [key for key, _name, _height in asm.SCREEN_SPECS]
    for variant in ("light", "dark"):
        for key in keys:
            capture_dir = tmp_path / f"{variant}-{key}"
            capture_dir.mkdir()
            payload = {"document": {"children": [{"children": [_capture_frame()]}]}}
            (capture_dir / "figma_file.json").write_text(json.dumps(payload), encoding="utf-8")
    out = tmp_path / "design"
    argv = ["assemble_capture.py"]
    argv += [f"--captures={key}={tmp_path / f'light-{key}'}" for key in keys]
    argv += [f"--dark-captures={key}={tmp_path / f'dark-{key}'}" for key in keys]
    argv += [f"--out={out}"]
    monkeypatch.setattr(sys, "argv", argv)

    asm.main()

    light = json.loads((out / "figma_file.json").read_text(encoding="utf-8"))
    dark = json.loads((out / "figma_file.dark.json").read_text(encoding="utf-8"))
    for payload, dark_mode in ((light, False), (dark, True)):
        canvas = payload["document"]["children"][0]
        assert [f["name"] for f in canvas["children"]] == [name for _k, name, _h in asm.SCREEN_SPECS]
        bar = canvas["children"][0]["children"][-1]
        assert bar["name"] == "Tab Bar"
        tint = max(_rgb(bar["fills"][0]))
        assert tint < 80 if dark_mode else tint > 200
    # Light stays the default document; dark rides alongside. The canvas is the
    # Nomic token canvas, never pure white or pure black.
    light_bg = light["document"]["children"][0]["backgroundColor"]
    assert (light_bg["r"], light_bg["g"], light_bg["b"]) == (
        pytest.approx(0.980, abs=1e-3),
        pytest.approx(0.980, abs=1e-3),
        pytest.approx(0.976, abs=1e-3),
    )
    dark_bg = dark["document"]["children"][0]["backgroundColor"]
    assert (dark_bg["r"], dark_bg["g"], dark_bg["b"]) == (
        pytest.approx(0.098, abs=1e-3),
        pytest.approx(0.114, abs=1e-3),
        pytest.approx(0.102, abs=1e-3),
    )


# ── screen assembly ───────────────────────────────────────────────────────────


def _capture_frame(height: float = 874) -> dict:
    return {
        "id": "1:0",
        "type": "FRAME",
        "name": "Nomic",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 402, "height": height},
        "clipsContent": True,
        "fills": [{"type": "SOLID", "color": {"r": 1, "g": 1, "b": 1}, "opacity": 1}],
        "children": [_text_node("Hello")],
    }


def test_assemble_screen_places_content_below_the_status_clear(asm) -> None:
    tab_bar = _bar(asm)
    screen = asm.assemble_screen(_capture_frame(), name="Drive", tab_bar=tab_bar)

    assert screen["name"] == "Drive"
    assert screen["overflowDirection"] == "VERTICAL_SCROLLING"
    assert screen["children"][0]["absoluteBoundingBox"]["y"] == asm.STATUS_CLEAR_PT
    assert screen["children"][-1] is tab_bar
    assert screen["numberOfFixedChildren"] == 2


def test_top_scroll_edge_fades_content_under_the_status_bar(asm) -> None:
    tab_bar = _bar(asm)
    screen = asm.assemble_screen(_capture_frame(), name="Drive", tab_bar=tab_bar)

    edge = screen["children"][-2]
    assert edge["name"] == "Scroll Edge"
    x, y, w, h = _box(edge)
    assert (x, y, w) == (0.0, 0.0, asm.FRAME_W)
    assert h > asm.STATUS_CLEAR_PT
    paint = edge["fills"][0]
    assert paint["type"] == "GRADIENT_LINEAR"
    alphas = [stop["color"]["a"] for stop in paint["gradientStops"]]
    assert alphas[0] == 1.0 and alphas[-1] == 0.0
    # Opaque through the status bar, fading out below it.
    opaque_until = max(stop["position"] for stop in paint["gradientStops"] if stop["color"]["a"] == 1.0)
    assert opaque_until * h >= asm.STATUS_CLEAR_PT - 12


def test_content_scrolls_edge_to_edge_under_the_floating_bar(asm) -> None:
    tab_bar = _bar(asm)
    _x, bar_y, _w, _h = _box(tab_bar)
    screen = asm.assemble_screen(_capture_frame(), name="Drive", tab_bar=tab_bar)

    height = screen["absoluteBoundingBox"]["height"]
    assert screen["absoluteBoundingBox"]["width"] == asm.FRAME_W
    # Fully scrolled, the end of the content sits just above the floating bar,
    # and the frame (with its background) still reaches the screen bottom.
    max_scroll = height - asm.VIEWPORT_H
    content_bottom = asm.STATUS_CLEAR_PT + 874
    assert content_bottom - max_scroll == pytest.approx(bar_y)


def test_screen_height_grows_only_when_content_needs_scrolling(asm) -> None:
    tab_bar = _bar(asm)
    screen = asm.assemble_screen(_capture_frame(500), name="Profile", tab_bar=tab_bar)

    assert screen["absoluteBoundingBox"]["height"] == asm.VIEWPORT_H
    assert screen.get("overflowDirection", "NONE") == "NONE"


def test_session_row_hotspot_gets_a_friendly_name_and_navigation(asm) -> None:
    capture = _capture_frame()
    capture["children"].append(_text_node("Concrete spec questions", {"x": 24, "y": 400, "width": 200, "height": 20}))
    assistant = asm.assemble_screen(capture, name="Assistant", tab_bar=_bar(asm, active="assistant"))
    wired = asm.wire_content_hotspot(assistant, "Concrete spec questions", "Conversation Link", "99:0")

    assert wired
    text = next(node for node in assistant["children"] if "Concrete spec" in node.get("characters", ""))
    actions = text["interactions"][0]["actions"]
    assert text["name"] == "Conversation Link"
    assert actions[0]["destinationId"] == "99:0"


def test_composer_mode_chip_gets_a_tappable_name(asm) -> None:
    capture = _capture_frame()
    capture["children"].append(_text_node("Auto", {"x": 300, "y": 745, "width": 40, "height": 18}))
    screen = asm.assemble_screen(capture, name="Assistant", tab_bar=_bar(asm, active="assistant"))

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
    screen = asm.assemble_screen(capture, name="Drive", tab_bar=_bar(asm))

    assert asm.drop_misplaced_header_widgets(screen) == 1
    assert all(node is not switcher for node in asm._walk_all(screen))


def test_select_controls_below_the_header_survive_widget_cleanup(asm) -> None:
    capture = _capture_frame()
    theme = {
        "id": "1:8",
        "type": "FRAME",
        "name": "button.data-[placeholder]:text-muted-foreground",
        "absoluteBoundingBox": {"x": 221, "y": 524, "width": 144, "height": 32},
        "children": [_text_node("System")],
    }
    capture["children"].append(theme)
    screen = asm.assemble_screen(capture, name="Profile", tab_bar=_bar(asm, active="profile"))

    assert asm.drop_misplaced_header_widgets(screen) == 0
    assert any(node is theme for node in asm._walk_all(screen))


def _composer_capture() -> tuple[dict, dict, dict]:
    capture = _capture_frame()
    label = _text_node("Integrations/MCPs", {"x": 85, "y": 807, "width": 105, "height": 15})
    composer = {
        "id": "1:358",
        "type": "FRAME",
        "name": "div.relative",
        "absoluteBoundingBox": {"x": 16, "y": 744, "width": 370, "height": 114},
        "children": [label],
    }
    thread = {
        "id": "1:337",
        "type": "FRAME",
        "name": "div.flex",
        "clipsContent": True,
        "absoluteBoundingBox": {"x": 0, "y": 114, "width": 402, "height": 760},
        "children": [_text_node("Cure requirements", {"x": 24, "y": 130, "width": 300, "height": 20}), composer],
    }
    capture["children"].append(thread)
    return capture, thread, composer


def test_conversation_composer_pins_above_the_floating_tab_bar(asm) -> None:
    capture, thread, composer = _composer_capture()
    bar = _bar(asm, active="assistant")
    screen = asm.assemble_screen(capture, name="Conversation", tab_bar=bar)

    assert asm.pin_composer_above_tab_bar(screen, "Integrations/MCPs")

    assert screen["numberOfFixedChildren"] == 3
    assert screen["children"][-3] is composer and screen["children"][-1] is bar
    assert composer not in thread["children"]
    _x, y, _w, h = _box(composer)
    # Two floating controls never touch: the composer hovers a clear gap above
    # the glass capsule.
    assert y + h == pytest.approx(asm.TAB_BAR_Y - asm.COMPOSER_BAR_GAP_PT)
    assert asm.COMPOSER_BAR_GAP_PT >= 8.0
    label_y = composer["children"][0]["absoluteBoundingBox"]["y"]
    assert label_y - y == pytest.approx(807 - 744)


def test_pinning_reports_a_missing_composer(asm) -> None:
    screen = asm.assemble_screen(_capture_frame(), name="Conversation", tab_bar=_bar(asm))

    assert not asm.pin_composer_above_tab_bar(screen, "Integrations/MCPs")
    assert screen["numberOfFixedChildren"] == 2


def test_merge_captures_renames_and_orders_frames(asm) -> None:
    frames = [
        ({"id": "S0:1:0", "type": "FRAME", "name": "Nomic", "absoluteBoundingBox": {"x": 0, "y": 0, "width": 402, "height": 874}, "children": []}, "Assistant"),
        ({"id": "S1:1:0", "type": "FRAME", "name": "Nomic", "absoluteBoundingBox": {"x": 0, "y": 0, "width": 402, "height": 874}, "children": []}, "Drive"),
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


def test_conversation_screen_keeps_the_assistant_tab_selected(asm, tmp_path) -> None:
    # Conversation is a detail flow inside the Assistant tab, not a tab itself;
    # iOS keeps the originating tab selected [S-TABBARS].
    import json

    captures = {}
    for key, _name, _height in asm.SCREEN_SPECS:
        capture_dir = tmp_path / key
        capture_dir.mkdir()
        payload = {"document": {"children": [{"children": [_capture_frame()]}]}}
        (capture_dir / "figma_file.json").write_text(json.dumps(payload), encoding="utf-8")
        captures[key] = capture_dir

    payload = asm.assemble_design(captures)

    convo = next(f for f in payload["document"]["children"][0]["children"] if f["name"] == "Conversation")
    bar = convo["children"][-1]
    tabs = {tab["name"]: _tab_parts(tab) for tab in bar["children"]}
    assert _rgb(tabs["Assistant Tab"]["icon"]["fills"][0]) == (73, 129, 109)
    for name in ("Drive Tab", "Projects Tab", "Profile Tab"):
        assert _rgb(tabs[name]["icon"]["fills"][0]) == (77, 82, 79), name


# ── generated design ──────────────────────────────────────────────────────────


def test_generated_design_matches_the_app_viewport(asm) -> None:
    import json
    import tomllib

    display = tomllib.loads((APP_DIR / "app.toml").read_text(encoding="utf-8"))["display"]
    payload = json.loads((APP_DIR / "design" / "figma_file.json").read_text(encoding="utf-8"))
    screens = payload["document"]["children"][0]["children"]

    assert (display["native_width"], display["native_height"]) == (asm.FRAME_W, asm.VIEWPORT_H)
    assert screens
    for screen in screens:
        assert screen["absoluteBoundingBox"]["width"] == asm.FRAME_W
        assert screen["absoluteBoundingBox"]["height"] >= asm.VIEWPORT_H
        bar = screen["children"][-1]
        assert bar["name"] == "Tab Bar" and screen["numberOfFixedChildren"] >= 2
        for node in asm._walk_all(bar):
            if node["type"] == "TEXT":
                assert node["style"]["fontSize"] >= 11


def _committed_designs() -> dict[str, dict]:
    import json

    return {
        appearance: json.loads((APP_DIR / "design" / filename).read_text(encoding="utf-8"))
        for appearance, filename in (("light", "figma_file.json"), ("dark", "figma_file.dark.json"))
    }


def test_committed_designs_have_no_sr_only_text(asm) -> None:
    for appearance, payload in _committed_designs().items():
        for node in asm._walk_all(payload["document"]):
            assert "sr-only" not in str(node.get("name", "")), (appearance, node.get("name"))


def test_committed_dark_design_has_no_invisible_black_icons(asm) -> None:
    payload = _committed_designs()["dark"]

    def walk(node: dict, colorful_ancestor: bool, screen_name: str) -> None:
        colorful = colorful_ancestor
        for paint in node.get("fills") or ():
            if paint.get("type") == "SOLID":
                rgb = _rgb(paint)
                if max(rgb) - min(rgb) > 24:
                    colorful = True
                if node["type"] == "VECTOR":
                    assert colorful or max(rgb) > 12, (screen_name, node.get("name"), rgb)
        for child in node.get("children") or ():
            walk(child, colorful, screen_name)

    for screen in payload["document"]["children"][0]["children"]:
        walk(screen, False, screen["name"])


def test_committed_conversation_composer_clears_the_tab_bar(asm) -> None:
    for appearance, payload in _committed_designs().items():
        convo = next(f for f in payload["document"]["children"][0]["children"] if f["name"] == "Conversation")
        bar = convo["children"][-1]
        composer = convo["children"][-3]
        _x, cy, _w, ch = _box(composer)
        _x, by, _w, _h = _box(bar)
        assert by - (cy + ch) == pytest.approx(asm.COMPOSER_BAR_GAP_PT), appearance
