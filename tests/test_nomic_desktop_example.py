from __future__ import annotations

from pathlib import Path
import tomllib
import unittest

from luvatrix.app import validate_app_install
from luvatrix_ui.figma import FigmaDocument


APP_DIR = Path(__file__).resolve().parents[1] / "examples" / "nomic_desktop"
DESIGN = APP_DIR / "design" / "figma_file.json"


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

    def test_design_loads_with_desktop_frames(self) -> None:
        doc = FigmaDocument.load(DESIGN)

        self.assertGreaterEqual(len(doc.frames), 1)
        self.assertIn(doc.start_frame_id, {frame.id for frame in doc.frames})
        for frame in doc.frames:
            self.assertEqual((frame.width, frame.height), (1440.0, 900.0)), frame.name

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
