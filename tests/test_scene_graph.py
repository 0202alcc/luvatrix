from __future__ import annotations

import unittest

import numpy as np

from luvatrix_core.core.scene_graph import (
    Camera3DNode,
    CircleNode,
    ClearNode,
    CpuLayerNode,
    Cube3DNode,
    GroundPlane3DNode,
    RectNode,
    SceneFrame,
    SceneGraphBuffer,
    ShaderRectNode,
    TextNode,
    split_frame_by_z_band,
)
from luvatrix_core.core.scene_rasterizer import (
    _Offsets,
    _encode_node_for_rs,
    _rasterize_scene_frame_python,
    rasterize_scene_frame,
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


class ContentZBandTests(unittest.TestCase):
    """SL-41 app-side scroll rebuild: the retained content-offset path needs
    fixed chrome (sidebar, pill, scrollbar) living in the SAME frame as the
    scrolling content. ``content_z_band`` names the inclusive z range the
    offset applies to; nodes outside the band (the z=0 window backstop below,
    z>=5 chrome above) present untransformed. ``None`` keeps the legacy
    whole-frame semantics every existing app and target already has."""

    @staticmethod
    def _frame(nodes, *, band=None, offset_y: float = 0.0) -> SceneFrame:
        return SceneFrame(
            revision=0,
            logical_width=100,
            logical_height=80,
            display_width=100,
            display_height=80,
            ts_ns=1,
            nodes=tuple(nodes),
            content_offset_y=offset_y,
            content_z_band=band,
        )

    def test_content_z_band_defaults_to_none(self) -> None:
        frame = SceneFrame(0, 100, 80, 100, 80, 1, ())
        self.assertIsNone(frame.content_z_band)

    def test_invalid_band_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._frame((), band=(4.0, 1.0))  # low must not exceed high
        with self.assertRaises(ValueError):
            self._frame((), band=(2.0,))  # exactly (low, high)

    def test_submit_preserves_the_band(self) -> None:
        buffer = SceneGraphBuffer()
        buffer.submit(self._frame((RectNode(1, 2, 3, 4, (1, 2, 3, 255)),), band=(1.0, 4.0)))
        self.assertEqual(buffer.latest_frame().content_z_band, (1.0, 4.0))

    def test_submit_content_offset_preserves_the_band(self) -> None:
        """A transform-only scroll tick must keep the band — losing it would
        drag the chrome along with the content for one revision."""
        buffer = SceneGraphBuffer()
        buffer.submit(self._frame((RectNode(1, 2, 3, 4, (1, 2, 3, 255)),), band=(1.0, 4.0)))

        event = buffer.submit_content_offset(0.0, 42.0)
        transformed = buffer.latest_frame()

        self.assertIsNotNone(event)
        self.assertEqual(transformed.content_z_band, (1.0, 4.0))
        self.assertEqual(transformed.content_offset_y, 42.0)

    def test_band_change_is_a_render_change(self) -> None:
        """Same nodes + same offset but a different band composites
        differently, so the dedup must not swallow it."""
        buffer = SceneGraphBuffer()
        first = self._frame((RectNode(1, 2, 3, 4, (1, 2, 3, 255)),), band=(1.0, 4.0), offset_y=8.0)
        second = self._frame((RectNode(1, 2, 3, 4, (1, 2, 3, 255)),), band=None, offset_y=8.0)
        third = self._frame((RectNode(1, 2, 3, 4, (1, 2, 3, 255)),), band=None, offset_y=8.0)

        self.assertEqual(buffer.submit_if_changed(first).revision, 1)
        self.assertEqual(buffer.submit_if_changed(second).revision, 2)
        deduped = buffer.submit_if_changed(third)
        self.assertEqual(deduped.event_id, 0)
        self.assertEqual(buffer.deduplicated_submissions, 1)

    def test_split_groups_nodes_into_z_tiers(self) -> None:
        """Tiers are z-contiguous by construction, so drawing below -> band ->
        above preserves the frame's exact z compositing order."""
        backstop = RectNode(0, 0, 100, 80, (9, 9, 9, 255), z_index=0)
        card = RectNode(4, 100, 20, 20, (200, 0, 0, 255), z_index=2)
        label = TextNode("row", x=4, y=100, z_index=3)
        chrome = RectNode(90, 0, 5, 40, (90, 90, 90, 255), z_index=5)
        pill = CircleNode(50, 70, 10, (255, 255, 255, 255), z_index=10)
        frame = self._frame((backstop, card, label, chrome, pill), band=(1.0, 4.0), offset_y=33.0)

        tiers = split_frame_by_z_band(frame)

        self.assertEqual(len(tiers), 3)
        below, banded, above = tiers
        self.assertEqual(below.nodes, (backstop,))
        self.assertEqual(banded.nodes, (card, label))
        self.assertEqual(above.nodes, (chrome, pill))
        # Fixed tiers present untransformed; only the band keeps the offset.
        self.assertEqual((below.content_offset_x, below.content_offset_y), (0.0, 0.0))
        self.assertEqual(banded.content_offset_y, 33.0)
        self.assertEqual((above.content_offset_x, above.content_offset_y), (0.0, 0.0))
        # Sub-frames must not re-split downstream (rasterizer recursion).
        for tier in tiers:
            self.assertIsNone(tier.content_z_band)

    def test_split_skips_empty_tiers(self) -> None:
        card = RectNode(4, 100, 20, 20, (200, 0, 0, 255), z_index=2)
        frame = self._frame((card,), band=(1.0, 4.0), offset_y=12.0)
        tiers = split_frame_by_z_band(frame)
        self.assertEqual(len(tiers), 1)
        self.assertIs(tiers[0].nodes[0], card)
        self.assertEqual(tiers[0].content_offset_y, 12.0)

    def test_split_band_bounds_are_inclusive(self) -> None:
        low_node = RectNode(0, 0, 10, 10, (1, 1, 1, 255), z_index=1)
        high_node = RectNode(0, 20, 10, 10, (2, 2, 2, 255), z_index=4)
        frame = self._frame((low_node, high_node), band=(1.0, 4.0), offset_y=5.0)
        tiers = split_frame_by_z_band(frame)
        self.assertEqual(len(tiers), 1)
        self.assertEqual(tiers[0].nodes, (low_node, high_node))


class CpuLayerGeometryRasterTests(unittest.TestCase):
    """A layer node's RGBA payload is content stretched over the node geometry.

    Retina payloads carry more pixels than the node's logical size; the CPU
    raster (and the MCP readbacks built on it) must still paint the node's
    rect, not the raw payload size.
    """

    def _frame(self, nodes, *, display: int = 40) -> SceneFrame:
        return SceneFrame(
            revision=0,
            logical_width=40,
            logical_height=40,
            display_width=display,
            display_height=display,
            ts_ns=1,
            nodes=tuple(nodes),
        )

    def test_oversized_payload_paints_only_the_node_rect(self) -> None:
        payload = np.full((20, 20, 4), (255, 0, 0, 255), dtype=np.uint8)
        frame = self._frame([
            ClearNode((0, 0, 0, 255)),
            CpuLayerNode(x=2, y=3, width=10, height=10, rgba=payload, z_index=1),
        ])
        for raster in (rasterize_scene_frame(frame), _rasterize_scene_frame_python(frame)):
            self.assertEqual(tuple(int(c) for c in raster[3, 2][:3]), (255, 0, 0))
            self.assertEqual(tuple(int(c) for c in raster[12, 11][:3]), (255, 0, 0))
            # A 1:1 paste of the 20px payload would reach these pixels.
            self.assertEqual(tuple(int(c) for c in raster[13, 13][:3]), (0, 0, 0))
            self.assertEqual(tuple(int(c) for c in raster[22, 22][:3]), (0, 0, 0))

    def test_undersized_payload_scales_up_to_the_node_rect(self) -> None:
        payload = np.full((6, 6, 4), (0, 255, 0, 255), dtype=np.uint8)
        frame = self._frame([
            ClearNode((0, 0, 0, 255)),
            CpuLayerNode(x=0, y=0, width=12, height=12, rgba=payload, z_index=1),
        ])
        raster = _rasterize_scene_frame_python(frame)
        self.assertEqual(tuple(int(c) for c in raster[0, 0][:3]), (0, 255, 0))
        self.assertEqual(tuple(int(c) for c in raster[11, 11][:3]), (0, 255, 0))
        self.assertEqual(tuple(int(c) for c in raster[12, 12][:3]), (0, 0, 0))

    def test_matching_payload_keeps_exact_pixels(self) -> None:
        payload = np.arange(10 * 10 * 4, dtype=np.uint8).reshape(10, 10, 4)
        payload[:, :, 3] = 255
        frame = self._frame([
            ClearNode((0, 0, 0, 255)),
            CpuLayerNode(x=5, y=5, width=10, height=10, rgba=payload, z_index=1),
        ])
        raster = _rasterize_scene_frame_python(frame)
        region = raster[5:15, 5:15, :]
        self.assertTrue(bool((region == payload).all()))

    def test_rs_encode_scales_payload_to_node_geometry(self) -> None:
        payload = np.full((20, 20, 4), (9, 9, 9, 255), dtype=np.uint8)
        frame = self._frame([])
        node = CpuLayerNode(x=2, y=3, width=10, height=10, rgba=payload, z_index=1)

        ops = _encode_node_for_rs(node, 1.0, 1.0, frame, Camera3DNode(), _Offsets(0.0, 0.0, 0.0, 0.0))

        self.assertIsNotNone(ops)
        assert ops is not None
        self.assertEqual(len(ops), 1)
        op = ops[0]
        self.assertEqual(op[0], 5)
        self.assertEqual((op[1], op[2]), (2, 3))
        self.assertEqual((op[3], op[4]), (10, 10))
        self.assertEqual(tuple(op[5].shape), (10, 10, 4))

    def test_rs_encode_scales_payload_with_display_ratio(self) -> None:
        payload = np.full((10, 10, 4), (9, 9, 9, 255), dtype=np.uint8)
        frame = self._frame([], display=80)
        node = CpuLayerNode(x=2, y=3, width=10, height=10, rgba=payload, z_index=1)

        ops = _encode_node_for_rs(node, 2.0, 2.0, frame, Camera3DNode(), _Offsets(0.0, 0.0, 0.0, 0.0))

        self.assertIsNotNone(ops)
        assert ops is not None
        op = ops[0]
        self.assertEqual((op[3], op[4]), (20, 20))
        self.assertEqual(tuple(op[5].shape), (20, 20, 4))


if __name__ == "__main__":
    unittest.main()
