from __future__ import annotations

import unittest

from luvatrix_core.platform.frame_pipeline import PresentationMode
from main import _resolve_presentation_mode


class MainCliTests(unittest.TestCase):
    def test_macos_defaults_to_pixel_preserve(self) -> None:
        self.assertEqual(_resolve_presentation_mode("macos", None), PresentationMode.PIXEL_PRESERVE)

    def test_headless_defaults_to_stretch(self) -> None:
        self.assertEqual(_resolve_presentation_mode("headless", None), PresentationMode.STRETCH)

    def test_explicit_presentation_mode_is_respected(self) -> None:
        self.assertEqual(
            _resolve_presentation_mode("macos", "preserve_aspect"),
            PresentationMode.PRESERVE_ASPECT,
        )


if __name__ == "__main__":
    unittest.main()
