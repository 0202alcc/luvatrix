from __future__ import annotations

import unittest

from luvatrix_core.core.scene_graph import (
    CircleNode,
    ClearNode,
    RectNode,
    SceneFrame,
    SceneGraphBuffer,
    ShaderRectNode,
    TextNode,
)


class SceneGraphTests(unittest.TestCase):
    def test_scene_frame_sorts_nodes_by_z_index(self) -> None:
        frame = SceneFrame(
            revision=0,
            logical_width=320,
            logical_height=180,
            display_width=320,
            display_height=180,
            ts_ns=1,
            nodes=(
                TextNode("top", x=0, y=0, z_index=20),
                ClearNode((0, 0, 0, 255)),
                RectNode(x=0, y=0, width=10, height=10, color_rgba=(255, 0, 0, 255), z_index=5),
            ),
        )
        self.assertIsInstance(frame.nodes[0], ClearNode)
        self.assertIsInstance(frame.nodes[1], RectNode)
        self.assertIsInstance(frame.nodes[2], TextNode)

    def test_nodes_validate_geometry(self) -> None:
        with self.assertRaises(ValueError):
            ShaderRectNode(x=0, y=0, width=0, height=10)
        with self.assertRaises(ValueError):
            CircleNode(cx=0, cy=0, radius=-1, fill_rgba=(255, 255, 255, 255))
        with self.assertRaises(ValueError):
            TextNode("bad", x=0, y=0, font_size_px=0)

    def test_scene_graph_buffer_revisions_and_latest_lookup(self) -> None:
        buffer = SceneGraphBuffer()
        frame = SceneFrame(
            revision=0,
            logical_width=2,
            logical_height=2,
            display_width=2,
            display_height=2,
            ts_ns=1,
            nodes=(ClearNode((1, 2, 3, 255)),),
        )
        event = buffer.submit(frame)
        self.assertEqual(event.revision, 1)
        latest = buffer.latest_frame(event.revision)
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest.revision, 1)
        self.assertIsNone(buffer.latest_frame(999))
        self.assertEqual(buffer.pop_scene_blit().revision, 1)


if __name__ == "__main__":
    unittest.main()
