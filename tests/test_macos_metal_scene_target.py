from __future__ import annotations

import unittest
import ctypes

from luvatrix_core.core.scene_graph import CircleNode, ClearNode, RectNode, RoundedRectNode, SceneFrame, ShaderRectNode, TextNode
from luvatrix_core.platform.macos.metal_scene_target import (
    _ReusableMetalBuffer,
    _clear_color,
    _collect_circle_instances,
    _collect_rect_instances,
    _scene_view_uniform,
    _write_reusable_float_buffer,
)


class _FakeContents:
    def __init__(self, storage: bytearray) -> None:
        self.storage = storage

    def as_buffer(self, length: int) -> memoryview:
        return memoryview(self.storage)[:length]


class _FakeBuffer:
    def __init__(self, capacity: int) -> None:
        self.storage = bytearray(capacity)

    def contents(self) -> _FakeContents:
        return _FakeContents(self.storage)


class _FakeDevice:
    def __init__(self) -> None:
        self.allocations: list[int] = []

    def newBufferWithLength_options_(self, capacity: int, _options: int) -> _FakeBuffer:
        self.allocations.append(capacity)
        return _FakeBuffer(capacity)


class MacOSMetalSceneTargetTests(unittest.TestCase):
    def test_scene_view_uniform_carries_content_translation(self) -> None:
        frame = SceneFrame(1, 200, 100, 200, 100, 1, (), content_offset_x=3.5, content_offset_y=17.25)

        self.assertEqual(list(_scene_view_uniform(frame)), [200.0, 100.0, 3.5, 17.25])

    def test_reusable_float_buffer_grows_by_capacity_and_reuses_allocation(self) -> None:
        device = _FakeDevice()
        slot = _ReusableMetalBuffer()
        small = (ctypes.c_float * 8)(*range(8))
        large = (ctypes.c_float * 2048)(*range(2048))

        first = _write_reusable_float_buffer(device, slot, small)
        second = _write_reusable_float_buffer(device, slot, small)
        grown = _write_reusable_float_buffer(device, slot, large)

        self.assertIs(first, second)
        self.assertIsNot(grown, first)
        self.assertEqual(len(device.allocations), 2)
        self.assertGreaterEqual(slot.capacity_bytes, ctypes.sizeof(large))
        self.assertEqual(bytes(grown.storage[: ctypes.sizeof(large)]), bytes(large))

    def test_collect_rect_instances_batches_rect_like_nodes(self) -> None:
        frame = SceneFrame(
            logical_width=100,
            logical_height=80,
            display_width=100,
            display_height=80,
            revision=1,
            ts_ns=1,
            nodes=(
                ClearNode((1, 2, 3, 255)),
                RectNode(1, 2, 3, 4, (10, 20, 30, 255)),
                RoundedRectNode(5, 6, 7, 8, 2, (40, 50, 60, 128)),
                ShaderRectNode(9, 10, 11, 12, shader="solid", color_rgba=(70, 80, 90, 64)),
                CircleNode(20, 30, 5, (100, 110, 120, 255)),
                TextNode("not batched", 1, 1),
            ),
        )

        rects = _collect_rect_instances(frame)

        self.assertEqual(len(rects), 3)
        self.assertEqual(rects[0][:4], (1.0, 2.0, 3.0, 4.0))
        self.assertEqual(rects[1][:4], (5.0, 6.0, 7.0, 8.0))
        self.assertEqual(rects[2][:4], (9.0, 10.0, 11.0, 12.0))

    def test_collect_circle_instances_batches_circles_separately(self) -> None:
        frame = SceneFrame(
            logical_width=100,
            logical_height=80,
            display_width=100,
            display_height=80,
            revision=1,
            ts_ns=1,
            nodes=(
                CircleNode(20, 30, 5, (100, 110, 120, 255), stroke_rgba=(10, 20, 30, 128), stroke_width=2),
                RectNode(1, 2, 3, 4, (10, 20, 30, 255)),
            ),
        )

        circles = _collect_circle_instances(frame)

        self.assertEqual(len(circles), 1)
        self.assertEqual(circles[0][:4], (15.0, 25.0, 10.0, 10.0))
        self.assertEqual(circles[0][4:8], (100 / 255.0, 110 / 255.0, 120 / 255.0, 1.0))
        self.assertEqual(circles[0][8:12], (10 / 255.0, 20 / 255.0, 30 / 255.0, 128 / 255.0))
        self.assertEqual(circles[0][12], 0.4)

    def test_clear_color_uses_scene_clear_node(self) -> None:
        frame = SceneFrame(10, 10, 10, 10, 1, 1, nodes=(ClearNode((4, 5, 6, 7)),))

        self.assertEqual(_clear_color(frame, (0, 0, 0, 255)), (4, 5, 6, 7))


if __name__ == "__main__":
    unittest.main()
