from __future__ import annotations

import unittest

from luvatrix_core.core.debug_capture import (
    REQUIRED_SCREENSHOT_SIDECAR_KEYS,
    build_screenshot_artifact_bundle,
    build_screenshot_sidecar,
    debug_capture_platform_capability_matrix,
    screenshot_artifacts_are_atomic,
)


class DebugScreenshotContractTests(unittest.TestCase):
    def test_debug_screenshot_sidecar_has_required_fields(self) -> None:
        sidecar = build_screenshot_sidecar(
            route="app.home",
            revision="r42",
            captured_at_utc="2026-03-05T15:30:00Z",
            provenance_id="run-abc",
        )
        self.assertEqual(tuple(REQUIRED_SCREENSHOT_SIDECAR_KEYS), ("route", "revision", "captured_at_utc", "provenance_id"))
        for key in REQUIRED_SCREENSHOT_SIDECAR_KEYS:
            self.assertIn(key, sidecar)
            self.assertTrue(sidecar[key])

    def test_debug_screenshot_bundle_is_deterministic_for_capture_id(self) -> None:
        bundle = build_screenshot_artifact_bundle(
            capture_id="capture-0001",
            route="app.home",
            revision="r42",
            captured_at_utc="2026-03-05T15:30:00Z",
            provenance_id="run-abc",
            output_dir="artifacts",
        )
        self.assertEqual(bundle.png_path, "artifacts/capture-0001.png")
        self.assertEqual(bundle.sidecar_path, "artifacts/capture-0001.json")
        self.assertEqual(bundle.sidecar["route"], "app.home")
        self.assertEqual(bundle.sidecar["revision"], "r42")

    def test_debug_screenshot_artifacts_require_atomic_pairing(self) -> None:
        self.assertTrue(screenshot_artifacts_are_atomic(png_written=True, sidecar_written=True))
        self.assertTrue(screenshot_artifacts_are_atomic(png_written=False, sidecar_written=False))
        self.assertFalse(screenshot_artifacts_are_atomic(png_written=True, sidecar_written=False))
        self.assertFalse(screenshot_artifacts_are_atomic(png_written=False, sidecar_written=True))

    def test_debug_screenshot_non_macos_is_explicit_stub(self) -> None:
        matrix = debug_capture_platform_capability_matrix()
        self.assertEqual(matrix["windows"]["supported"], False)
        self.assertEqual(matrix["linux"]["supported"], False)
        self.assertEqual(matrix["windows"]["unsupported_reason"], "macOS-first phase: explicit stub only")
        self.assertEqual(matrix["linux"]["unsupported_reason"], "macOS-first phase: explicit stub only")


if __name__ == "__main__":
    unittest.main()
