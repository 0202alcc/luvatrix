from __future__ import annotations

import unittest

from examples.demo_app.app_main import PAGE_JSON, _parse_hex_color, compile_page


class DemoAppProtocolTests(unittest.TestCase):
    def test_parse_hex_color(self) -> None:
        self.assertEqual(_parse_hex_color("#112233"), (17, 34, 51, 255))
        self.assertEqual(_parse_hex_color("#11223344"), (17, 34, 51, 68))

    def test_compile_page_builds_renderable_elements(self) -> None:
        compiled = compile_page(PAGE_JSON)
        self.assertEqual(compiled.viewport_width, 640)
        self.assertEqual(compiled.viewport_height, 360)
        self.assertGreaterEqual(len(compiled.elements), 3)
        for e in compiled.elements:
            self.assertGreater(e.width_px, 0.0)
            self.assertGreater(e.height_px, 0.0)
            self.assertTrue(e.svg_markup.startswith("<svg") or "<svg" in e.svg_markup)


if __name__ == "__main__":
    unittest.main()
