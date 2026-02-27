from __future__ import annotations

import unittest

from luvatrix_core.core.frame_rate_controller import FrameRateController


class FrameRateControllerTests(unittest.TestCase):
    def test_rejects_invalid_target_fps(self) -> None:
        with self.assertRaises(ValueError):
            FrameRateController(target_fps=0)

    def test_rejects_invalid_present_fps(self) -> None:
        with self.assertRaises(ValueError):
            FrameRateController(target_fps=60, present_fps=0)

    def test_present_fps_is_clamped_to_target_fps(self) -> None:
        rate = FrameRateController(target_fps=60, present_fps=240)
        self.assertEqual(rate.present_fps, 60)

    def test_should_present_tracks_cadence(self) -> None:
        rate = FrameRateController(target_fps=120, present_fps=30)
        dt = 1.0 / 120.0
        now = 0.0
        presented = 0
        for _ in range(120):
            if rate.should_present(now):
                presented += 1
            now += dt
        self.assertEqual(presented, 30)

    def test_should_present_recovers_after_stall(self) -> None:
        rate = FrameRateController(target_fps=60, present_fps=20)
        self.assertTrue(rate.should_present(0.0))
        # Long pause should not force multiple immediate presents on resume.
        self.assertTrue(rate.should_present(1.0))
        self.assertFalse(rate.should_present(1.0))

    def test_compute_sleep_handles_negative_elapsed(self) -> None:
        rate = FrameRateController(target_fps=100)
        sleep_for = rate.compute_sleep(loop_started_at=10.0, loop_finished_at=9.0)
        self.assertAlmostEqual(sleep_for, 0.01, places=6)

    def test_compute_sleep_rejects_invalid_throttle(self) -> None:
        rate = FrameRateController(target_fps=60)
        with self.assertRaises(ValueError):
            rate.compute_sleep(loop_started_at=0.0, loop_finished_at=0.0, throttle_multiplier=0.0)


if __name__ == "__main__":
    unittest.main()
