from __future__ import annotations

import gzip
import json
from pathlib import Path
import tomllib
from typing import Any
import unittest

from luvatrix.app import validate_app_install
from luvatrix_ui.figma import FigmaDocument


APP_DIR = Path(__file__).resolve().parents[1] / "examples" / "nomic_desktop"
DESIGN = APP_DIR / "design" / "figma_file.json"


def _destination_ids(node: dict[str, Any]) -> list[tuple[str, str]]:
    destinations: list[tuple[str, str]] = []
    for interaction in node.get("interactions") or []:
        for action in interaction.get("actions") or []:
            destination = action.get("destinationId")
            if destination:
                destinations.append((str(destination), str(action.get("navigation", ""))))
    for child in node.get("children") or []:
        destinations.extend(_destination_ids(child))
    return destinations


class NomicDesktopExampleTests(unittest.TestCase):
    def test_manifest_declares_macos_support(self) -> None:
        manifest = tomllib.loads((APP_DIR / "app.toml").read_text(encoding="utf-8"))

        self.assertIn("macos", manifest["platform_support"])
        self.assertEqual(manifest["entrypoint"], "app_main:create")
        self.assertEqual(manifest["display"]["native_width"], 1440)
        self.assertEqual(manifest["display"]["native_height"], 900)
        self.assertEqual(manifest["display"]["title"], "Nomic")

    def test_validates_for_ios_simulator_and_device(self) -> None:
        for render in ("ios-simulator", "ios-device"):
            with self.subTest(render=render):
                validation = validate_app_install(APP_DIR, render=render)
                self.assertTrue(validation.ok)

    def test_design_loads_complete_desktop_flow(self) -> None:
        doc = FigmaDocument.load(DESIGN)

        payload = json.loads(gzip.decompress(DESIGN.read_bytes()))
        user_flows = next(
            entry["document"]
            for entry in payload["nodes"].values()
            if entry["document"]["name"] == "User Flows"
        )
        # The Figma page has 68 top-level nodes: 64 screen frames and four
        # section-label text nodes ("Files & Context", "Workflows", etc.).
        self.assertEqual(len(user_flows["children"]), 68)
        self.assertEqual(len(doc.frames), 64)
        self.assertIn(doc.start_frame_id, {frame.id for frame in doc.frames})
        frames_by_name = {frame.name: frame for frame in doc.frames}
        for name in (
            "Main page",
            "Filled input",
            "Reasoning",
            "Answer ready",
            "Questions & Answers",
        ):
            with self.subTest(frame=name):
                frame = frames_by_name[name]
                self.assertEqual((frame.width, frame.height), (1440.0, 900.0))

    def test_design_has_no_dead_screen_navigation(self) -> None:
        doc = FigmaDocument.load(DESIGN)

        frame_ids = {frame.id for frame in doc.frames}
        destinations = [
            destination
            for frame in doc.frames
            for destination in _destination_ids(frame.node)
        ]
        self.assertGreater(len(destinations), 0)
        # This source design uses component CHANGE_TO interactions for hover
        # and active states; it contains no inter-frame prototype navigation.
        # Only actual screen-navigation actions should resolve to frame ids.
        self.assertEqual({navigation for _, navigation in destinations}, {"CHANGE_TO"})
        dead_screen_links = {
            destination
            for destination, navigation in destinations
            if navigation in {"NAVIGATE", "SWAP", "OVERLAY"} and destination not in frame_ids
        }
        self.assertEqual(dead_screen_links, set())

    def test_manifest_opts_into_mcp(self) -> None:
        # The desktop run workflow launches this app with --mcp; without the
        # manifest gate the runtime refuses to start MCP and the launch fails.
        manifest = tomllib.loads((APP_DIR / "app.toml").read_text(encoding="utf-8"))

        self.assertTrue(manifest["mcp"]["enabled"])

    def test_display_icon_is_the_nomic_mark(self) -> None:
        manifest = tomllib.loads((APP_DIR / "app.toml").read_text(encoding="utf-8"))

        # The Dock icon must be the curated Nomic mark at the app root, not a
        # content image from the design (a photo fill once shipped as the icon).
        self.assertEqual(manifest["display"]["icon"], "icon.png")
        icon_path = APP_DIR / "icon.png"
        self.assertTrue(icon_path.is_file(), "Dock icon missing: icon.png")
        self.assertGreater(icon_path.stat().st_size, 1024, "Dock icon looks like a placeholder")
        with icon_path.open("rb") as f:
            from PIL import Image

            image = Image.open(f)
            self.assertEqual(image.size[0], image.size[1], "Dock icon should be square")
            self.assertGreaterEqual(image.size[0], 256, "Dock icon should be at least 256px")


if __name__ == "__main__":
    unittest.main()
