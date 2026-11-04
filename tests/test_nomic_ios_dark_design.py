"""The nomic_ios example ships a dark design variant and wires it into FigmaApp."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "examples" / "nomic_ios"
DESIGN = APP_DIR / "design" / "figma_file.json"
DESIGN_DARK = APP_DIR / "design" / "figma_file.dark.json"


def _load_app_main():
    spec = importlib.util.spec_from_file_location("nomic_ios_app_main", APP_DIR / "app_main.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _frames_by_name(design_path: Path) -> dict[str, dict]:
    payload = json.loads(design_path.read_text(encoding="utf-8"))
    return {
        frame["name"]: frame
        for page in payload["document"]["children"]
        for frame in page["children"]
    }


def _fill(frame: dict) -> tuple[int, int, int]:
    color = frame["fills"][0]["color"]
    return tuple(round(color[channel] * 255) for channel in "rgb")


def test_dark_design_document_ships_alongside_light_with_the_same_screens() -> None:
    assert DESIGN_DARK.exists(), "run assemble_capture.py with --dark-captures"

    light = _frames_by_name(DESIGN)
    dark = _frames_by_name(DESIGN_DARK)

    assert sorted(light) == sorted(dark) == ["Assistant", "Conversation", "Drive", "Profile", "Projects"]
    # Frame ids are stable across appearances so navigation maps 1:1.
    assert {name: light[name]["id"] for name in light} == {name: dark[name]["id"] for name in dark}
    for name in light:
        light_fill = _fill(light[name])
        dark_fill = _fill(dark[name])
        assert sum(light_fill) > 3 * 200, (name, light_fill)
        assert sum(dark_fill) < 3 * 80, (name, dark_fill)


def test_create_wires_the_dark_variant(monkeypatch) -> None:
    monkeypatch.delenv("LUVATRIX_APPEARANCE", raising=False)
    monkeypatch.delenv("LUVATRIX_IOS_USER_INTERFACE_STYLE", raising=False)

    app = _load_app_main().create()

    assert app.appearance == "light"
    assert app.current_frame_name == "Assistant"
    light_document = app.document

    assert app.set_appearance("dark") is True
    assert app.appearance == "dark"
    assert app.document is not light_document
    assert app.current_frame_name == "Assistant"

    assert app.set_appearance("light") is True
    assert app.document is light_document
