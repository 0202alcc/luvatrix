"""Clickable hotspot manifest and click-map interaction tests."""

from __future__ import annotations

from typing import Any

from luvatrix_ui.figma.capture import compile_snapshots

from figma_capture_fixtures import SnapshotBuilder


def nav_page(path: str, *, testid: str | None = None, title: str = "Nav") -> dict[str, Any]:
    b = SnapshotBuilder(title=title)
    body = b.element("BODY")
    b.layout(body, 0, 0, 393, 852, **{"background-color": "rgb(255, 255, 255)"})
    attrs = {"data-testid": testid} if testid else {}
    button = b.element("BUTTON", parent=body, attrs=attrs, clickable=True)
    b.layout(button, 12, 12, 120, 40, **{"background-color": "rgb(37, 99, 235)"})
    t = b.text("Settings", parent=button)
    li = b.layout(t, 30, 24, 84, 16)
    b.text_box(li, 30, 24, 84, 16)
    return b.build()


def test_interactive_elements_are_recorded_in_clickables() -> None:
    b = SnapshotBuilder(title="Clicks")
    body = b.element("BODY")
    b.layout(body, 0, 0, 393, 852, **{"background-color": "rgb(255, 255, 255)"})
    link = b.element("A", parent=body, attrs={"href": "/pricing"}, clickable=True)
    b.layout(link, 0, 0, 100, 20, **{"display": "inline", "color": "rgb(0, 0, 102)"})
    t = b.text("Pricing", parent=link)
    li = b.layout(t, 0, 0, 60, 20)
    b.text_box(li, 0, 0, 60, 20)
    role_button = b.element("DIV", parent=body, attrs={"role": "button", "class": "cta"}, clickable=True)
    b.layout(role_button, 0, 40, 80, 30, **{"background-color": "rgb(20, 20, 20)"})
    plain = b.element("DIV", parent=body)
    b.layout(plain, 0, 100, 50, 50, **{"background-color": "rgb(240, 240, 240)"})

    result = compile_snapshots([("/", b.build())])

    names = [entry["name"] for entry in result.clickables]
    assert "Pricing" in names
    assert "cta" in [entry["selector"] for entry in result.clickables]
    assert len(result.clickables) == 2
    entry = next(e for e in result.clickables if e["name"] == "Pricing")
    assert entry["page"] == "/"
    assert entry["selector"] == "a[href=/pricing]"
    assert entry["x"] == 50.0 and entry["y"] == 10.0
    assert entry["nodeId"].startswith("1:")


def test_link_text_stays_in_its_own_node() -> None:
    b = SnapshotBuilder(title="Links")
    body = b.element("BODY")
    b.layout(body, 0, 0, 393, 852, **{"background-color": "rgb(255, 255, 255)"})
    paragraph = b.element("P", parent=body)
    b.layout(paragraph, 0, 0, 300, 40, **{"color": "rgb(0, 0, 0)"})
    t1 = b.text("See ", parent=paragraph)
    li1 = b.layout(t1, 0, 10, 30, 20)
    b.text_box(li1, 0, 10, 30, 20)
    link = b.element("A", parent=paragraph, attrs={"href": "/x"}, clickable=True)
    b.layout(link, 30, 10, 60, 20, **{"display": "inline", "color": "rgb(0, 0, 238)"})
    t2 = b.text("details", parent=link)
    li2 = b.layout(t2, 30, 10, 60, 20)
    b.text_box(li2, 30, 10, 60, 20)

    result = compile_snapshots([("/", b.build())])

    root = result.file["document"]["children"][0]["children"][0]
    kinds = [c["type"] for c in root["children"]]
    assert kinds == ["TEXT", "FRAME"]
    assert root["children"][0]["characters"] == "See"
    link_frame = root["children"][1]
    assert link_frame["name"] == "a"
    assert link_frame["children"][0]["characters"] == "details"
    assert link_frame["children"][0]["fills"][0]["color"]["b"] == 238 / 255


def test_click_map_adds_navigate_interactions(tmp_path: Any) -> None:
    click_map = {"/ -> [data-testid=nav-settings]": "/settings"}

    result = compile_snapshots(
        [("/", nav_page("/", testid="nav-settings")), ("/settings", nav_page("/settings", title="Settings"))],
        click_map=click_map,
    )

    frames = result.file["document"]["children"][0]["children"]
    home, settings = frames[0], frames[1]
    source = next(node for node in _flatten(home) if node["name"] == "BUTTON")
    interactions = source["interactions"]
    assert interactions[0]["trigger"]["type"] == "ON_CLICK"
    action = interactions[0]["actions"][0]
    assert action["type"] == "NODE"
    assert action["navigation"] == "NAVIGATE"
    assert action["destinationId"] == settings["id"]
    assert result.report["interactions"]["mapped"] == 1
    assert result.report["interactions"]["unmatched"] == []


def test_unmatched_click_map_selectors_are_reported() -> None:
    result = compile_snapshots(
        [("/", nav_page("/"))],
        click_map={"/ -> [data-testid=missing]": "/gone"},
    )

    assert result.report["interactions"]["mapped"] == 0
    unmatched = result.report["interactions"]["unmatched"]
    assert len(unmatched) == 1
    assert unmatched[0]["selector"] == "[data-testid=missing]"


def _flatten(node: dict[str, Any]) -> list[dict[str, Any]]:
    out = [node]
    for child in node.get("children") or ():
        out.extend(_flatten(child))
    return out