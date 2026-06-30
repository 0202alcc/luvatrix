from __future__ import annotations

import unittest

from luvatrix_core.core.scene_graph import (
    Camera3DNode,
    CircleNode,
    ClearNode,
    Cube3DNode,
    GroundPlane3DNode,
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
                Cube3DNode(z_index=10),
                RectNode(x=0, y=0, width=10, height=10, color_rgba=(255, 0, 0, 255), z_index=5),
            ),
        )
        self.assertIsInstance(frame.nodes[0], ClearNode)
        self.assertIsInstance(frame.nodes[1], RectNode)
        self.assertIsInstance(frame.nodes[2], Cube3DNode)
        self.assertIsInstance(frame.nodes[3], TextNode)

    def test_nodes_validate_geometry(self) -> None:
        with self.assertRaises(ValueError):
            ShaderRectNode(x=0, y=0, width=0, height=10)
        with self.assertRaises(ValueError):
            CircleNode(cx=0, cy=0, radius=-1, fill_rgba=(255, 255, 255, 255))
        with self.assertRaises(ValueError):
            TextNode("bad", x=0, y=0, font_size_px=0)
        with self.assertRaises(ValueError):
            Camera3DNode(fov_deg=180)
        with self.assertRaises(ValueError):
            Camera3DNode(near=1.0, far=1.0)
        with self.assertRaises(ValueError):
            Cube3DNode(size=0)
        with self.assertRaises(ValueError):
            GroundPlane3DNode(width=0)
        with self.assertRaises(ValueError):
            GroundPlane3DNode(depth=0)

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

    def test_scene_graph_buffer_deduplicates_identical_render_content(self) -> None:
        buffer = SceneGraphBuffer()
        first = SceneFrame(
            revision=0,
            logical_width=100,
            logical_height=80,
            display_width=100,
            display_height=80,
            ts_ns=1,
            nodes=(ClearNode((0, 0, 0, 255)), RectNode(x=1, y=2, width=3, height=4, color_rgba=(1, 2, 3, 255))),
            animation_t=1.0,
        )
        second = SceneFrame(
            revision=0,
            logical_width=100,
            logical_height=80,
            display_width=100,
            display_height=80,
            ts_ns=2,
            nodes=(ClearNode((0, 0, 0, 255)), RectNode(x=1, y=2, width=3, height=4, color_rgba=(1, 2, 3, 255))),
            animation_t=2.0,
        )

        submitted = buffer.submit_if_changed(first)
        duplicate = buffer.submit_if_changed(second)

        self.assertEqual(submitted.revision, 1)
        self.assertEqual(duplicate.event_id, 0)
        self.assertEqual(duplicate.revision, 1)
        self.assertEqual(buffer.deduplicated_submissions, 1)
        self.assertEqual(buffer.pop_scene_blit().revision, 1)
        self.assertIsNone(buffer.pop_scene_blit())

    def test_scene_graph_buffer_treats_content_offset_as_transform_revision(self) -> None:
        buffer = SceneGraphBuffer()
        base = SceneFrame(1, 100, 80, 100, 80, 1, (ClearNode((0, 0, 0, 255)),))
        shifted = SceneFrame(
            2,
            100,
            80,
            100,
            80,
            2,
            (ClearNode((0, 0, 0, 255)),),
            content_offset_y=12.5,
        )

        self.assertEqual(buffer.submit_if_changed(base).revision, 1)
        self.assertEqual(buffer.submit_if_changed(shifted).revision, 2)

    def test_scene_graph_buffer_can_submit_transform_without_rebuilding_nodes(self) -> None:
        buffer = SceneGraphBuffer()
        frame = SceneFrame(0, 100, 80, 100, 80, 1, (RectNode(1, 2, 3, 4, (1, 2, 3, 255)),))
        buffer.submit(frame)
        original = buffer.latest_frame()

        event = buffer.submit_content_offset(0.0, 24.0)
        transformed = buffer.latest_frame()

        self.assertIsNotNone(event)
        self.assertEqual(event.revision, 2)
        self.assertIs(transformed.nodes, original.nodes)
        self.assertEqual(transformed.content_offset_y, 24.0)


if __name__ == "__main__":
    unittest.main()
