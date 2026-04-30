from __future__ import annotations

import unittest
from unittest.mock import patch

from luvatrix_core.platform.frame_pipeline import PresentationMode
from main import _is_free_threaded_runtime, _resolve_presentation_mode, _warn_if_not_free_threaded


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

    def test_free_threaded_runtime_detects_disabled_gil(self) -> None:
        with patch("main.sys._is_gil_enabled", return_value=False, create=True):
            self.assertTrue(_is_free_threaded_runtime())

    def test_warn_if_not_free_threaded_logs_warning(self) -> None:
        with (
            patch("main.sys._is_gil_enabled", return_value=True, create=True),
            patch("main.LOGGER.warning") as warning,
        ):
            _warn_if_not_free_threaded()
        warning.assert_called_once()

    def test_warn_if_not_free_threaded_skips_warning_for_free_threaded_runtime(self) -> None:
        with (
            patch("main.sys._is_gil_enabled", return_value=False, create=True),
            patch("main.LOGGER.warning") as warning,
        ):
            _warn_if_not_free_threaded()
        warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
