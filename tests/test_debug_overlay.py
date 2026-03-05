from __future__ import annotations

import unittest

from luvatrix_core.core.debug_capture import (
    OverlayRect,
    build_overlay_spec,
    debug_capture_platform_capability_matrix,
    toggle_overlay_non_destructive,
)
from luvatrix_core.core.debug_menu import build_debug_capability_registry


class DebugOverlayContractTests(unittest.TestCase):
    def test_debug_overlay_spec_validates_bounds_and_dirty_rects(self) -> None:
        spec = build_overlay_spec(
            overlay_id="overlay.bounds",
            bounds=OverlayRect(x=0, y=0, width=1920, height=1080),
            dirty_rects=(OverlayRect(x=100, y=100, width=200, height=150),),
            coordinate_space="window_px",
            opacity=0.75,
            enabled=True,
        )
        self.assertEqual(spec.bounds.width, 1920)
        self.assertEqual(spec.dirty_rects[0].height, 150)

    def test_debug_overlay_toggle_is_non_destructive(self) -> None:
        result = toggle_overlay_non_destructive(
            overlay_id="overlay.bounds",
            previous_enabled=False,
            next_enabled=True,
            content_digest="frame-sha256-abc",
        )
        self.assertFalse(result.destructive)
        self.assertEqual(result.content_digest_before, result.content_digest_after)

    def test_debug_overlay_capability_is_declared_for_macos(self) -> None:
        registry = build_debug_capability_registry()
        self.assertEqual(registry["debug.menu.overlay.toggle"], "debug.overlay.render")

    def test_debug_overlay_non_macos_is_explicit_stub(self) -> None:
        matrix = debug_capture_platform_capability_matrix()
        self.assertIn("debug.overlay.stub", matrix["windows"]["declared_capabilities"])
        self.assertIn("debug.overlay.stub", matrix["linux"]["declared_capabilities"])


if __name__ == "__main__":
    unittest.main()
