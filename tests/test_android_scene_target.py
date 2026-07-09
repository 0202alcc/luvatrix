from __future__ import annotations

import json
import unittest

from luvatrix_core.core.scene_graph import CircleNode, ClearNode, SceneFrame, ShaderRectNode, TextNode
from luvatrix_core.platform.android.scene_target import AndroidNativeSceneTarget


class _Presenter:
    def __init__(self) -> None:
        self.calls = []

    def presentScene(self, payload: str, revision: int, width: int, height: int, presentation_mode: str = "") -> None:
        self.calls.append((payload, revision, width, height, presentation_mode))


class AndroidNativeSceneTargetTests(unittest.TestCase):
    def test_present_scene_serializes_supported_nodes(self) -> None:
        presenter = _Presenter()
        target = AndroidNativeSceneTarget(presenter)
        target.start()
        frame = SceneFrame(
            revision=2,
            logical_width=100,
            logical_height=200,
            display_width=100,
            display_height=200,
            ts_ns=1,
            nodes=(
                ClearNode((1, 2, 3, 255)),
                ShaderRectNode(0, 0, 100, 200, shader="full_suite_background", uniforms=(1.0, 2.0, 3.0)),
                CircleNode(10, 20, 5, fill_rgba=(4, 5, 6, 128), stroke_rgba=(7, 8, 9, 255), stroke_width=2),
                TextNode("hello", x=1, y=2, font_size_px=12, color_rgba=(10, 11, 12, 255)),
            ),
        )

        target.present_scene(frame, target_present_time=123.456)

        self.assertEqual(target.frames_presented, 1)
        self.assertEqual(presenter.calls[0][1:4], (2, 100, 200))
        payload = json.loads(presenter.calls[0][0])
        self.assertEqual([node["type"] for node in payload], ["meta", "clear", "shader_rect", "circle", "text"])
        self.assertEqual(
            payload[0],
            {
                "type": "meta",
                "presentation_mode": "",
                "content_offset_x": 0.0,
                "content_offset_y": 0.0,
            },
        )
        self.assertEqual(payload[2]["uniforms"], [1.0, 2.0, 3.0])

    def test_present_scene_serializes_content_offset(self) -> None:
        presenter = _Presenter()
        target = AndroidNativeSceneTarget(presenter)
        target.start()
        frame = SceneFrame(
            revision=3,
            logical_width=100,
            logical_height=200,
            display_width=100,
            display_height=200,
            ts_ns=1,
            nodes=(ClearNode((0, 0, 0, 255)),),
            content_offset_x=4.5,
            content_offset_y=-12.25,
        )

        target.present_scene(frame)

        payload = json.loads(presenter.calls[0][0])
        self.assertEqual(payload[0]["content_offset_x"], 4.5)
        self.assertEqual(payload[0]["content_offset_y"], -12.25)

    def test_present_scene_requires_start(self) -> None:
        target = AndroidNativeSceneTarget(_Presenter())
        frame = SceneFrame(1, 1, 1, 1, 1, ts_ns=1, nodes=(ClearNode(),))

        with self.assertRaisesRegex(RuntimeError, "before start"):
            target.present_scene(frame)


if __name__ == "__main__":
    unittest.main()
