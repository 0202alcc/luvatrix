from __future__ import annotations

import unittest

from luvatrix_core.platform.macos.hdi_source import _to_top_left_y


class MacOSHDISourceTests(unittest.TestCase):
    def test_to_top_left_y_converts_and_clamps(self) -> None:
        self.assertEqual(_to_top_left_y(99.0, 100.0), 0.0)
        self.assertEqual(_to_top_left_y(0.0, 100.0), 99.0)
        self.assertEqual(_to_top_left_y(-10.0, 100.0), 99.0)
        self.assertEqual(_to_top_left_y(1000.0, 100.0), 0.0)



if __name__ == "__main__":
    unittest.main()
