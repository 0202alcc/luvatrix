from __future__ import annotations

import unittest

from luvatrix_core.core.coordinates import CoordinateFrameRegistry


class CoordinateFrameRegistryTests(unittest.TestCase):
    def test_presets_transform_as_expected(self) -> None:
        reg = CoordinateFrameRegistry(width=100, height=50)
        x, y = reg.transform_point((0.0, 0.0), from_frame="screen_tl", to_frame="cartesian_bl")
        self.assertEqual((x, y), (0.0, 49.0))
        x2, y2 = reg.transform_point((0.0, 49.0), from_frame="cartesian_bl", to_frame="screen_tl")
        self.assertEqual((x2, y2), (0.0, 0.0))

    def test_center_preset_origin(self) -> None:
        reg = CoordinateFrameRegistry(width=101, height=51)
        x, y = reg.transform_point((0.0, 0.0), from_frame="cartesian_center", to_frame="screen_tl")
        self.assertEqual((x, y), (50.0, 25.0))

    def test_define_custom_frame_and_transform(self) -> None:
        reg = CoordinateFrameRegistry(width=100, height=100)
        reg.define_frame(
            name="my_frame",
            origin=(10.0, 20.0),
            basis_x=(2.0, 0.0),
            basis_y=(0.0, 2.0),
        )
        x, y = reg.to_render_coords((3.0, 4.0), frame="my_frame")
        self.assertEqual((x, y), (16.0, 28.0))
        back = reg.from_render_coords((16.0, 28.0), frame="my_frame")
        self.assertEqual(back, (3.0, 4.0))

    def test_singular_custom_frame_rejected(self) -> None:
        reg = CoordinateFrameRegistry(width=10, height=10)
        with self.assertRaises(ValueError):
            reg.define_frame("bad", origin=(0.0, 0.0), basis_x=(1.0, 0.0), basis_y=(2.0, 0.0))


if __name__ == "__main__":
    unittest.main()
