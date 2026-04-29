from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from luvatrix_core.core.hdi_thread import HDIEvent, HDIThread
from luvatrix_core.core.scene_display_runtime import SceneDisplayRuntime
from luvatrix_core.core.scene_graph import ClearNode, RectNode, SceneFrame, SceneGraphBuffer
from luvatrix_core.core.scene_graph import CircleNode, TextNode
from luvatrix_core.core.sensor_manager import SensorManagerThread
from luvatrix_core.core.unified_runtime import UnifiedRuntime
from luvatrix_core.core.window_matrix import WindowMatrix
from luvatrix_core.targets.base import DisplayFrame, RenderTarget
from luvatrix_core.targets.cpu_scene_target import CpuSceneTarget


class _NoopHDISource:
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        return []


class _RecordingMatrixTarget(RenderTarget):
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.presented: list[DisplayFrame] = []

    def start(self) -> None:
        self.started += 1

    def present_frame(self, frame: DisplayFrame) -> None:
        self.presented.append(frame)

    def stop(self) -> None:
        self.stopped += 1


class _RecordingSceneTarget:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.presented: list[SceneFrame] = []
        self.pumped = 0

    def start(self) -> None:
        self.started += 1

    def present_scene(self, frame: SceneFrame) -> None:
        self.presented.append(frame)

    def stop(self) -> None:
        self.stopped += 1

    def pump_events(self) -> None:
        self.pumped += 1

    def should_close(self) -> bool:
        return False


class _TelemetrySceneTarget(_RecordingSceneTarget):
    def consume_telemetry(self) -> dict[str, int]:
        return {
            "next_drawable_nil": 2,
            "next_drawable_slow": 1,
            "present_commits": len(self.presented),
        }


class _FakeSensorManager(SensorManagerThread):
    def __init__(self) -> None:
        super().__init__(providers={})
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


class SceneRuntimeTests(unittest.TestCase):
    def test_scene_mode_routes_scene_frames_to_scene_target(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            (app_dir / "app.toml").write_text(
                "\n".join(
                    [
                        'app_id = "test.scene.runtime"',
                        'protocol_version = "1"',
                        'entrypoint = "app_main:create"',
                        'required_capabilities = ["window.write"]',
                        "optional_capabilities = []",
                    ]
                )
            )
            (app_dir / "app_main.py").write_text(
                "\n".join(
                    [
                        "class _App:",
                        "    def loop(self, ctx, dt):",
                        "        assert ctx.supports_scene_graph",
                        "        ctx.begin_scene_frame()",
                        "        ctx.clear_scene((0, 0, 0, 255))",
                        "        ctx.draw_rect(x=0, y=0, width=1, height=1, color_rgba=(255, 0, 0, 255))",
                        "        ctx.finalize_scene_frame()",
                        "    def init(self, ctx):",
                        "        pass",
                        "    def stop(self, ctx):",
                        "        pass",
                        "def create():",
                        "    return _App()",
                    ]
                )
            )
            matrix_target = _RecordingMatrixTarget()
            scene_target = _RecordingSceneTarget()
            runtime = UnifiedRuntime(
                matrix=WindowMatrix(height=2, width=2),
                target=matrix_target,
                scene_target=scene_target,
                render_mode="scene",
                hdi=HDIThread(source=_NoopHDISource()),
                sensor_manager=_FakeSensorManager(),
                capability_decider=lambda _cap: True,
            )
            result = runtime.run_app(app_dir, max_ticks=3, target_fps=1000)
            self.assertEqual(result.ticks_run, 3)
            self.assertGreaterEqual(result.frames_presented, 1)
            self.assertEqual(scene_target.started, 1)
            self.assertEqual(scene_target.stopped, 1)
            self.assertEqual(matrix_target.started, 0)
            self.assertGreaterEqual(len(scene_target.presented), 1)
            self.assertIsInstance(scene_target.presented[-1].nodes[0], ClearNode)

    def test_cpu_scene_target_rasterizes_scene_to_matrix_target(self) -> None:
        matrix_target = _RecordingMatrixTarget()
        scene_target = CpuSceneTarget(matrix_target)
        frame = SceneFrame(
            revision=7,
            logical_width=2,
            logical_height=2,
            display_width=2,
            display_height=2,
            ts_ns=1,
            nodes=(
                ClearNode((0, 0, 0, 255)),
                RectNode(x=0, y=0, width=1, height=1, color_rgba=(255, 0, 0, 255)),
            ),
        )
        scene_target.start()
        scene_target.present_scene(frame)
        scene_target.stop()
        self.assertEqual(matrix_target.started, 1)
        self.assertEqual(matrix_target.stopped, 1)
        self.assertEqual(len(matrix_target.presented), 1)
        presented = matrix_target.presented[0]
        self.assertEqual(presented.revision, 7)
        self.assertEqual(int(presented.rgba[0, 0, 0]), 255)

    def test_scene_display_runtime_can_repeat_latest_frame_without_new_revision(self) -> None:
        buffer = SceneGraphBuffer()
        target = _RecordingSceneTarget()
        runtime = SceneDisplayRuntime(buffer, target)
        frame = SceneFrame(
            revision=0,
            logical_width=2,
            logical_height=2,
            display_width=2,
            display_height=2,
            ts_ns=1,
            nodes=(ClearNode((0, 0, 0, 255)),),
        )
        submitted = buffer.submit(frame)

        first = runtime.run_once(timeout=0.0)
        second = runtime.run_once(timeout=0.0, repeat_latest=True)

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None
        assert second is not None
        self.assertEqual(first.event.event_id, submitted.event_id)
        self.assertEqual(second.event.event_id, 0)
        self.assertEqual(first.frame.revision, second.frame.revision)
        self.assertEqual(buffer.revision, 1)
        self.assertEqual(len(target.presented), 2)

    def test_scene_display_runtime_skips_while_inactive_and_reports_telemetry(self) -> None:
        active = False
        buffer = SceneGraphBuffer()
        target = _TelemetrySceneTarget()
        runtime = SceneDisplayRuntime(buffer, target, active_provider=lambda: active)
        frame = SceneFrame(
            revision=0,
            logical_width=2,
            logical_height=2,
            display_width=2,
            display_height=2,
            ts_ns=1,
            nodes=(ClearNode((0, 0, 0, 255)),),
        )
        buffer.submit(frame)

        skipped = runtime.run_once(timeout=0.0)
        self.assertIsNone(skipped)
        self.assertEqual(len(target.presented), 0)
        self.assertGreaterEqual(runtime.telemetry().skipped_inactive, 1)
        self.assertEqual(runtime.telemetry().app_active, 0)

        active = True
        tick = runtime.run_once(timeout=0.0)
        self.assertIsNotNone(tick)
        self.assertEqual(len(target.presented), 1)
        telemetry = runtime.telemetry()
        self.assertEqual(telemetry.next_drawable_nil, 2)
        self.assertEqual(telemetry.next_drawable_slow, 1)
        self.assertEqual(telemetry.present_commits, 1)

    def test_ios_scene_overlay_split_keeps_static_text_out_of_dynamic_layer(self) -> None:
        from luvatrix_core.platform.ios.scene_target import (
            _is_dynamic_overlay_node,
            _is_static_text_node,
            _text_node_texture_key,
            _text_overlay_signature,
        )

        static = TextNode(
            "active frame: screen_tl",
            x=8,
            y=100,
            font_family="Comic Mono",
            cache_key="active_frame",
        )
        dynamic = TextNode(
            "screen_tl x=1.0, y=2.0",
            x=10,
            y=20,
            font_family="Comic Mono",
            cache_key="mouse_label",
        )
        circle = CircleNode(cx=10, cy=10, radius=4, fill_rgba=(255, 0, 0, 128))
        frame = SceneFrame(
            revision=1,
            logical_width=320,
            logical_height=180,
            display_width=320,
            display_height=180,
            ts_ns=1,
            nodes=(static, dynamic, circle),
        )

        self.assertFalse(_is_static_text_node(static))
        self.assertFalse(_is_dynamic_overlay_node(static))
        self.assertFalse(_is_static_text_node(dynamic))
        self.assertFalse(_is_dynamic_overlay_node(dynamic))
        self.assertFalse(_is_dynamic_overlay_node(circle))
        signature = _text_overlay_signature(frame)
        self.assertEqual(signature, ())
        moved = TextNode(
            "screen_tl x=1.0, y=2.0",
            x=200,
            y=300,
            font_family="Comic Mono",
            cache_key="mouse_label",
        )
        self.assertEqual(_text_node_texture_key(dynamic, 1.0), _text_node_texture_key(moved, 1.0))


if __name__ == "__main__":
    unittest.main()
