from __future__ import annotations

import unittest

from luvatrix_core.platform.ios import lifecycle


class IOSLifecycleTests(unittest.TestCase):
    def tearDown(self) -> None:
        lifecycle.set_app_active(True)

    def test_lifecycle_defaults_active_and_can_transition(self) -> None:
        lifecycle.set_app_active(True)
        self.assertTrue(lifecycle.is_app_active())

        lifecycle.set_app_active(False)
        self.assertFalse(lifecycle.is_app_active())
        inactive = lifecycle.snapshot()
        self.assertEqual(inactive["ios_app_active"], 0)

        lifecycle.set_app_active(True)
        self.assertTrue(lifecycle.is_app_active())
        active = lifecycle.snapshot()
        self.assertEqual(active["ios_app_active"], 1)
        self.assertGreaterEqual(
            active["ios_lifecycle_transition_count"],
            inactive["ios_lifecycle_transition_count"],
        )


if __name__ == "__main__":
    unittest.main()
