from __future__ import annotations

import json
from pathlib import Path
import struct
import unittest

from luvatrix_core.core.scene_graph import CircleNode, ClearNode, RectNode, SceneFrame, ShaderRectNode, TextNode
from luvatrix_core.platform.android.scene_target import AndroidNativeSceneTarget


ROOT = Path(__file__).resolve().parents[1]
ANDROID_CPP_RENDERERS = (
    ROOT / "android" / "app" / "src" / "main" / "cpp" / "luvatrix_vulkan_renderer.cpp",
    ROOT / "luvatrix_core" / "templates" / "native" / "android" / "app" / "src" / "main" / "cpp" / "luvatrix_vulkan_renderer.cpp",
)
ANDROID_KOTLIN_VIEWS = (
    ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "luvatrix" / "app" / "LuvatrixVulkanView.kt",
    ROOT / "luvatrix_core" / "templates" / "native" / "android" / "app" / "src" / "main" / "java" / "com" / "luvatrix" / "app" / "LuvatrixVulkanView.kt",
)


class _Presenter:
    def __init__(self) -> None:
        self.calls = []

    def presentScene(self, payload: str, revision: int, width: int, height: int, presentation_mode: str = "") -> None:
        self.calls.append((payload, revision, width, height, presentation_mode))


class _DeltaPresenter(_Presenter):
    def __init__(self) -> None:
        super().__init__()
        self.transform_calls = []

    def presentSceneTransform(self, revision: int, content_offset_x: float, content_offset_y: float) -> None:
        self.transform_calls.append((revision, content_offset_x, content_offset_y))


class _BinaryPresenter(_DeltaPresenter):
    def __init__(self) -> None:
        super().__init__()
        self.binary_calls = []

    def presentSceneBinary(
        self,
        payload: bytes,
        revision: int,
        width: int,
        height: int,
        presentation_mode: str = "",
    ) -> None:
        self.binary_calls.append((payload, revision, width, height, presentation_mode))


class AndroidNativeSceneTargetTests(unittest.TestCase):
    def test_present_scene_uses_versioned_binary_packet_when_supported(self) -> None:
        presenter = _BinaryPresenter()
        target = AndroidNativeSceneTarget(presenter)
        target.start()
        frame = SceneFrame(
            revision=7,
            logical_width=100,
            logical_height=200,
            display_width=100,
            display_height=200,
            ts_ns=1,
            nodes=(
                ClearNode((1, 2, 3, 255)),
                RectNode(1, 2, 30, 40, (4, 5, 6, 255)),
                CircleNode(10, 20, 5, fill_rgba=(7, 8, 9, 255)),
                TextNode("hello", x=1, y=2, font_size_px=12, color_rgba=(10, 11, 12, 255)),
            ),
            content_offset_x=4.5,
            content_offset_y=-12.25,
        )

        target.present_scene(frame)

        self.assertEqual(presenter.calls, [])
        payload, revision, width, height, mode = presenter.binary_calls[0]
        self.assertEqual((revision, width, height, mode), (7, 100, 200, ""))
        magic, version, node_count, offset_x, offset_y = struct.unpack_from("<4sBHdd", payload)
        self.assertEqual((magic, version, node_count), (b"LVXS", 1, 5))
        self.assertEqual((offset_x, offset_y), (4.5, -12.25))
        self.assertEqual(payload[struct.calcsize("<4sBHdd")], 1)  # meta node

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

    def test_retained_offset_revision_uses_transform_only_present(self) -> None:
        presenter = _DeltaPresenter()
        target = AndroidNativeSceneTarget(presenter)
        target.start()
        nodes = (ClearNode((0, 0, 0, 255)), RectNode(1, 2, 30, 40, (1, 2, 3, 255)))
        first = SceneFrame(1, 100, 200, 100, 200, ts_ns=1, nodes=nodes, retained=True)
        transformed = SceneFrame(
            2,
            100,
            200,
            100,
            200,
            ts_ns=2,
            nodes=nodes,
            content_offset_x=4.5,
            content_offset_y=17.25,
            retained=True,
        )

        target.present_scene(first)
        target.present_scene(transformed)

        self.assertEqual(len(presenter.calls), 1)
        self.assertEqual(presenter.transform_calls, [(2, 4.5, 17.25)])
        self.assertEqual(target.consume_telemetry()["transform_commits"], 1)

    def test_retained_geometry_change_uses_full_scene_present(self) -> None:
        presenter = _DeltaPresenter()
        target = AndroidNativeSceneTarget(presenter)
        target.start()
        target.present_scene(
            SceneFrame(
                1,
                100,
                200,
                100,
                200,
                ts_ns=1,
                nodes=(RectNode(0, 0, 10, 10, (255, 255, 255, 255)),),
                retained=True,
            )
        )
        target.present_scene(
            SceneFrame(
                2,
                100,
                200,
                100,
                200,
                ts_ns=2,
                nodes=(RectNode(0, 0, 20, 10, (255, 255, 255, 255)),),
                retained=True,
            )
        )

        self.assertEqual(len(presenter.calls), 2)
        self.assertEqual(presenter.transform_calls, [])

    def test_offset_revision_falls_back_for_presenter_without_transform_api(self) -> None:
        presenter = _Presenter()
        target = AndroidNativeSceneTarget(presenter)
        target.start()
        nodes = (RectNode(0, 0, 10, 10, (255, 255, 255, 255)),)
        target.present_scene(SceneFrame(1, 100, 200, 100, 200, ts_ns=1, nodes=nodes, retained=True))
        target.present_scene(
            SceneFrame(2, 100, 200, 100, 200, ts_ns=2, nodes=nodes, content_offset_y=8, retained=True)
        )

        self.assertEqual(len(presenter.calls), 2)

    def test_non_retained_offset_revision_uses_full_scene_present(self) -> None:
        presenter = _DeltaPresenter()
        target = AndroidNativeSceneTarget(presenter)
        target.start()
        nodes = (RectNode(0, 0, 10, 10, (255, 255, 255, 255)),)
        target.present_scene(SceneFrame(1, 100, 200, 100, 200, ts_ns=1, nodes=nodes))
        target.present_scene(
            SceneFrame(2, 100, 200, 100, 200, ts_ns=2, nodes=nodes, content_offset_y=8)
        )

        self.assertEqual(len(presenter.calls), 2)
        self.assertEqual(presenter.transform_calls, [])

    def test_native_renderer_applies_serialized_content_offset(self) -> None:
        for source in ANDROID_CPP_RENDERERS:
            with self.subTest(source=source):
                text = source.read_text(encoding="utf-8")
                self.assertIn("double content_offset_x = 0.0;", text)
                self.assertIn('parse_number_key(node, "content_offset_x"', text)
                self.assertIn("shifted.x -= scene.content_offset_x;", text)
                self.assertIn("shifted.cx -= scene.content_offset_x;", text)
                self.assertIn("shifted.y -= scene.content_offset_y;", text)
                self.assertIn('key += "/offset="', text)

    def test_canvas_fallback_applies_serialized_content_offset(self) -> None:
        for source in ANDROID_KOTLIN_VIEWS:
            with self.subTest(source=source):
                text = source.read_text(encoding="utf-8")
                self.assertIn('contentOffsetX = node.optDouble("content_offset_x"', text)
                self.assertIn('node.optDouble("x", 0.0) - contentOffsetX', text)
                self.assertIn('node.optDouble("cx", 0.0) - contentOffsetX', text)
                self.assertIn('node.optDouble("y", 0.0) - contentOffsetY', text)

    def test_native_android_bridge_exposes_transform_only_scene_present(self) -> None:
        for source in ANDROID_KOTLIN_VIEWS:
            with self.subTest(source=source):
                text = source.read_text(encoding="utf-8")
                self.assertIn("fun presentSceneTransform(", text)
                self.assertIn("NativeVulkan.presentSceneTransform(", text)
                self.assertIn("retainedSceneJson", text)
        for source in ANDROID_CPP_RENDERERS:
            with self.subTest(source=source):
                text = source.read_text(encoding="utf-8")
                self.assertIn("NativeVulkan_presentSceneTransform", text)
                self.assertIn("g_retained_scene.content_offset_x", text)
                self.assertIn("const auto nodes = parse_node_objects(json);", text)
                self.assertEqual(text.count("parse_node_objects(json)"), 1)

    def test_native_android_bridge_exposes_binary_scene_present(self) -> None:
        for source in ANDROID_KOTLIN_VIEWS:
            with self.subTest(source=source):
                text = source.read_text(encoding="utf-8")
                self.assertIn("fun presentSceneBinary(", text)
                self.assertIn("NativeVulkan.presentSceneBinary(", text)
        for source in ANDROID_CPP_RENDERERS:
            with self.subTest(source=source):
                text = source.read_text(encoding="utf-8")
                self.assertIn("NativeVulkan_presentSceneBinary", text)
                self.assertIn("parse_scene_binary", text)
                self.assertIn("LVXS", text)

    def test_present_scene_requires_start(self) -> None:
        target = AndroidNativeSceneTarget(_Presenter())
        frame = SceneFrame(1, 1, 1, 1, 1, ts_ns=1, nodes=(ClearNode(),))

        with self.assertRaisesRegex(RuntimeError, "before start"):
            target.present_scene(frame)


if __name__ == "__main__":
    unittest.main()
