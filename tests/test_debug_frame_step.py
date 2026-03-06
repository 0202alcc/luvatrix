from __future__ import annotations

import unittest

from luvatrix_core.core.debug_capture import (
    FrameStepState,
    REQUIRED_PERF_HUD_KEYS,
    build_perf_hud_snapshot,
    debug_capture_platform_capability_matrix,
    frame_step_advance,
)
from luvatrix_core.core.debug_menu import build_debug_capability_registry


class DebugFrameStepContractTests(unittest.TestCase):
    def test_frame_step_advances_only_from_paused_state(self) -> None:
        state = FrameStepState(paused=True, frame_index=41, last_ordering_digest="digest-41")
        next_state = frame_step_advance(state, next_ordering_digest="digest-42")
        self.assertEqual(next_state.frame_index, 42)
        self.assertEqual(next_state.last_ordering_digest, "digest-42")
        self.assertTrue(next_state.paused)

    def test_frame_step_rejects_non_paused_state(self) -> None:
        state = FrameStepState(paused=False, frame_index=3, last_ordering_digest="digest-3")
        with self.assertRaises(ValueError):
            frame_step_advance(state, next_ordering_digest="digest-4")

    def test_perf_hud_snapshot_has_required_fields(self) -> None:
        snapshot = build_perf_hud_snapshot(
            frame_index=24,
            frame_time_ms=16.667,
            present_mode="incremental",
            ordering_digest="digest-24",
        )
        for key in REQUIRED_PERF_HUD_KEYS:
            self.assertIn(key, snapshot)
        self.assertAlmostEqual(float(snapshot["fps"]), 60.0, places=2)

    def test_debug_menu_declares_frame_step_and_perf_hud_capabilities(self) -> None:
        registry = build_debug_capability_registry()
        self.assertEqual(registry["debug.menu.frame.step"], "debug.frame.step")
        self.assertEqual(registry["debug.menu.perf.hud.toggle"], "debug.perf.hud")

    def test_non_macos_frame_step_and_perf_hud_are_explicit_stubs(self) -> None:
        matrix = debug_capture_platform_capability_matrix()
        self.assertIn("debug.frame.step.stub", matrix["windows"]["declared_capabilities"])
        self.assertIn("debug.perf.hud.stub", matrix["windows"]["declared_capabilities"])
        self.assertIn("debug.frame.step.stub", matrix["linux"]["declared_capabilities"])
        self.assertIn("debug.perf.hud.stub", matrix["linux"]["declared_capabilities"])


if __name__ == "__main__":
    unittest.main()
