from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
import unittest

import torch

from luvatrix_ui.component_schema import CoordinatePoint, DisplayableArea
from luvatrix_ui.controls.svg_component import SVGComponent
from luvatrix_ui.controls.svg_renderer import SVGRenderBatch
from luvatrix_ui.text.component import TextComponent
from luvatrix_ui.text.renderer import TextLayoutMetrics, TextMeasureRequest, TextRenderBatch, TextSizeSpec

from luvatrix_core.core.app_runtime import (
    APP_PROTOCOL_VERSION,
    AppRuntime,
)
from luvatrix_core.core.hdi_thread import HDIEvent, HDIThread
from luvatrix_core.core.sensor_manager import SensorManagerThread, SensorSample
from luvatrix_core.core.window_matrix import FullRewrite, WindowMatrix, WriteBatch


@dataclass
class _LifecycleRecorder:
    init_called: bool = False
    loop_calls: int = 0
    stop_called: bool = False
    saw_sensor_status: str | None = None
    saw_hdi_count: int | None = None

    def init(self, ctx) -> None:
        self.init_called = True
        ctx.submit_write_batch(
            WriteBatch([FullRewrite(torch.zeros((1, 1, 4), dtype=torch.uint8))])
        )

    def loop(self, ctx, dt: float) -> None:
        self.loop_calls += 1
        self.saw_hdi_count = len(ctx.poll_hdi_events(16))
        self.saw_sensor_status = ctx.read_sensor("thermal.temperature").status

    def stop(self, ctx) -> None:
        self.stop_called = True


class _LifecycleRaisesInLoop(_LifecycleRecorder):
    def loop(self, ctx, dt: float) -> None:
        super().loop(ctx, dt)
        raise RuntimeError("boom")


class _FakeHDI:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def poll_events(self, max_events: int) -> list[HDIEvent]:
        return [
            HDIEvent(1, 1, "w", "keyboard", "key_down", "OK", {"key": "a"}),
            HDIEvent(2, 2, "w", "mouse", "pointer_move", "OK", {"x": 0.0, "y": 0.0}),
        ]


class _FakeSensor:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def read_sensor(self, sensor_type: str) -> SensorSample:
        return SensorSample(
            sample_id=1,
            ts_ns=1,
            sensor_type=sensor_type,
            status="OK",
            value=42,
            unit="u",
        )


class _CameraMetadataSensor:
    def read_sensor(self, sensor_type: str) -> SensorSample:
        return SensorSample(
            sample_id=1,
            ts_ns=1,
            sensor_type=sensor_type,
            status="OK",
            value={"available": True, "device_count": 2, "default_present": True, "raw_name": "internal"},
            unit="metadata",
        )


class _FakeUIRenderer:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.started_display: DisplayableArea | None = None
        self.clear_color: tuple[int, int, int, int] | None = None
        self.measure_requests: list[TextMeasureRequest] = []
        self.batches: list[TextRenderBatch] = []
        self.svg_batches: list[SVGRenderBatch] = []

    def begin_frame(self, display: DisplayableArea, clear_color: tuple[int, int, int, int]) -> None:
        self.started_display = display
        self.clear_color = clear_color

    def measure_text(self, request: TextMeasureRequest) -> TextLayoutMetrics:
        self.measure_requests.append(request)
        return TextLayoutMetrics(
            width_px=float(len(request.text)) * request.font_size_px * 0.5,
            height_px=request.font_size_px,
            baseline_px=request.font_size_px * 0.8,
        )

    def draw_text_batch(self, batch: TextRenderBatch) -> None:
        self.batches.append(batch)

    def draw_svg_batch(self, batch: SVGRenderBatch) -> None:
        self.svg_batches.append(batch)

    def end_frame(self) -> torch.Tensor:
        return torch.zeros((self.height, self.width, 4), dtype=torch.uint8)


class AppRuntimeTests(unittest.TestCase):
    def test_manifest_parses_platform_support_and_variants(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app.toml").write_text(
                "\n".join(
                    [
                        'app_id = "x"',
                        'protocol_version = "1"',
                        'entrypoint = "app_main:create"',
                        'platform_support = ["macos", "linux"]',
                        "required_capabilities = []",
                        "optional_capabilities = []",
                        "",
                        "[[variants]]",
                        'id = "mac-arm64"',
                        'os = ["macos"]',
                        'arch = ["arm64"]',
                        'module_root = "variants/macos_arm64"',
                    ]
                )
            )
            (root / "app_main.py").write_text("def create():\n    return object()\n")
            runtime = AppRuntime(
                matrix=WindowMatrix(1, 1),
                hdi=HDIThread(source=_NoopHDISource()),
                sensor_manager=SensorManagerThread(providers={}),
            )
            manifest = runtime.load_manifest(root)
            self.assertEqual(manifest.platform_support, ["macos", "linux"])
            self.assertEqual(len(manifest.variants), 1)
            self.assertEqual(manifest.variants[0].variant_id, "mac-arm64")

    def test_resolve_variant_picks_host_match_with_arch_priority(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app.toml").write_text(
                "\n".join(
                    [
                        'app_id = "x"',
                        'protocol_version = "1"',
                        'entrypoint = "app_main:create"',
                        'platform_support = ["macos"]',
                        "required_capabilities = []",
                        "optional_capabilities = []",
                        "",
                        "[[variants]]",
                        'id = "mac-any"',
                        'os = ["macos"]',
                        "",
                        "[[variants]]",
                        'id = "mac-arm64"',
                        'os = ["macos"]',
                        'arch = ["arm64"]',
                        'module_root = "variants/macos_arm64"',
                        'entrypoint = "variant_main:create"',
                    ]
                )
            )
            (root / "app_main.py").write_text("def create():\n    return object()\n")
            runtime = AppRuntime(
                matrix=WindowMatrix(1, 1),
                hdi=HDIThread(source=_NoopHDISource()),
                sensor_manager=SensorManagerThread(providers={}),
                host_os="macos",
                host_arch="arm64",
            )
            manifest = runtime.load_manifest(root)
            resolved = runtime.resolve_variant(root, manifest)
            self.assertEqual(resolved.variant_id, "mac-arm64")
            self.assertEqual(resolved.entrypoint, "variant_main:create")
            self.assertEqual(resolved.module_dir, (root / "variants/macos_arm64").resolve())

    def test_resolve_variant_rejects_unsupported_platform(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app.toml").write_text(
                "\n".join(
                    [
                        'app_id = "x"',
                        'protocol_version = "1"',
                        'entrypoint = "app_main:create"',
                        'platform_support = ["linux"]',
                        "required_capabilities = []",
                        "optional_capabilities = []",
                    ]
                )
            )
            (root / "app_main.py").write_text("def create():\n    return object()\n")
            runtime = AppRuntime(
                matrix=WindowMatrix(1, 1),
                hdi=HDIThread(source=_NoopHDISource()),
                sensor_manager=SensorManagerThread(providers={}),
                host_os="macos",
                host_arch="arm64",
            )
            manifest = runtime.load_manifest(root)
            with self.assertRaises(RuntimeError):
                runtime.resolve_variant(root, manifest)

    def test_variant_module_root_cannot_escape_app_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app.toml").write_text(
                "\n".join(
                    [
                        'app_id = "x"',
                        'protocol_version = "1"',
                        'entrypoint = "app_main:create"',
                        "required_capabilities = []",
                        "optional_capabilities = []",
                        "",
                        "[[variants]]",
                        'id = "bad"',
                        'os = ["macos"]',
                        'module_root = "../escape"',
                    ]
                )
            )
            (root / "app_main.py").write_text("def create():\n    return object()\n")
            runtime = AppRuntime(
                matrix=WindowMatrix(1, 1),
                hdi=HDIThread(source=_NoopHDISource()),
                sensor_manager=SensorManagerThread(providers={}),
                host_os="macos",
                host_arch="arm64",
            )
            manifest = runtime.load_manifest(root)
            with self.assertRaises(ValueError):
                runtime.resolve_variant(root, manifest)

    def test_app_context_hdi_events_denied_without_device_capability(self) -> None:
        from luvatrix_core.core.app_runtime import AppContext

        ctx = AppContext(
            matrix=WindowMatrix(1, 1),
            hdi=_FakeHDI(),  # type: ignore[arg-type]
            sensor_manager=_FakeSensor(),  # type: ignore[arg-type]
            granted_capabilities={"window.write", "hdi.mouse"},
        )
        events = ctx.poll_hdi_events(8)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].device, "keyboard")
        self.assertEqual(events[0].status, "DENIED")
        self.assertIsNone(events[0].payload)
        self.assertEqual(events[1].device, "mouse")
        self.assertEqual(events[1].status, "OK")

    def test_app_context_hdi_coordinates_can_be_requested_in_custom_frame(self) -> None:
        from luvatrix_core.core.app_runtime import AppContext

        ctx = AppContext(
            matrix=WindowMatrix(100, 100),
            hdi=_FakeHDI(),  # type: ignore[arg-type]
            sensor_manager=_FakeSensor(),  # type: ignore[arg-type]
            granted_capabilities={"window.write", "hdi.mouse", "hdi.keyboard"},
        )
        ctx.set_default_coordinate_frame("cartesian_bl")
        events = ctx.poll_hdi_events(8)
        mouse = [e for e in events if e.device == "mouse"][0]
        assert isinstance(mouse.payload, dict)
        self.assertEqual(mouse.payload["x"], 0.0)
        self.assertEqual(mouse.payload["y"], 99.0)

    def test_app_context_render_coordinate_helpers(self) -> None:
        from luvatrix_core.core.app_runtime import AppContext

        ctx = AppContext(
            matrix=WindowMatrix(10, 10),
            hdi=_FakeHDI(),  # type: ignore[arg-type]
            sensor_manager=_FakeSensor(),  # type: ignore[arg-type]
            granted_capabilities={"window.write"},
        )
        ctx.set_default_coordinate_frame("cartesian_bl")
        rx, ry = ctx.to_render_coords(0.0, 0.0)
        self.assertEqual((rx, ry), (0.0, 9.0))
        fx, fy = ctx.from_render_coords(0.0, 9.0)
        self.assertEqual((fx, fy), (0.0, 0.0))

    def test_app_context_ui_frame_compiles_text_components_to_matrix_write(self) -> None:
        from luvatrix_core.core.app_runtime import AppContext

        matrix = WindowMatrix(20, 30)
        renderer = _FakeUIRenderer(width=30, height=20)
        ctx = AppContext(
            matrix=matrix,
            hdi=_FakeHDI(),  # type: ignore[arg-type]
            sensor_manager=_FakeSensor(),  # type: ignore[arg-type]
            granted_capabilities={"window.write"},
        )

        component = TextComponent(
            component_id="title",
            text="Hello",
            position=CoordinatePoint(2.0, 3.0, "screen_tl"),
        )
        ctx.begin_ui_frame(renderer)
        ctx.mount_component(component)
        event = ctx.finalize_ui_frame()

        self.assertEqual(event.revision, 1)
        self.assertEqual(matrix.revision, 1)
        self.assertEqual(len(renderer.batches), 1)
        self.assertEqual(len(renderer.batches[0].commands), 1)
        self.assertEqual(renderer.batches[0].commands[0].text, "Hello")
        self.assertEqual(renderer.batches[0].commands[0].font.family, "Comic Mono")

    def test_app_context_ui_frame_uses_displayable_area_for_ratio_sizing(self) -> None:
        from luvatrix_core.core.app_runtime import AppContext

        renderer = _FakeUIRenderer(width=50, height=40)
        ctx = AppContext(
            matrix=WindowMatrix(40, 50),
            hdi=_FakeHDI(),  # type: ignore[arg-type]
            sensor_manager=_FakeSensor(),  # type: ignore[arg-type]
            granted_capabilities={"window.write"},
        )
        component = TextComponent(
            component_id="status",
            text="ratio",
            size=TextSizeSpec(unit="ratio_display_height", value=0.25),
        )
        ctx.begin_ui_frame(renderer, content_width_px=24, content_height_px=12)
        ctx.mount_component(component)
        ctx.finalize_ui_frame()

        self.assertIsNotNone(renderer.started_display)
        assert renderer.started_display is not None
        self.assertEqual(renderer.started_display.content_width_px, 24.0)
        self.assertEqual(renderer.started_display.content_height_px, 12.0)
        self.assertEqual(renderer.measure_requests[-1].font_size_px, 3.0)

    def test_app_context_ui_frame_requires_begin(self) -> None:
        from luvatrix_core.core.app_runtime import AppContext

        ctx = AppContext(
            matrix=WindowMatrix(5, 5),
            hdi=_FakeHDI(),  # type: ignore[arg-type]
            sensor_manager=_FakeSensor(),  # type: ignore[arg-type]
            granted_capabilities={"window.write"},
        )
        with self.assertRaises(RuntimeError):
            ctx.mount_component(TextComponent(component_id="x", text="x"))
        with self.assertRaises(RuntimeError):
            ctx.finalize_ui_frame()

    def test_app_context_ui_frame_compiles_svg_components_with_explicit_size(self) -> None:
        from luvatrix_core.core.app_runtime import AppContext

        renderer = _FakeUIRenderer(width=64, height=64)
        ctx = AppContext(
            matrix=WindowMatrix(64, 64),
            hdi=_FakeHDI(),  # type: ignore[arg-type]
            sensor_manager=_FakeSensor(),  # type: ignore[arg-type]
            granted_capabilities={"window.write"},
        )
        svg = SVGComponent(
            component_id="logo",
            svg_markup="""<svg width="8" height="8"><rect x="0" y="0" width="8" height="8" fill="#ff0000"/></svg>""",
            position=CoordinatePoint(5.0, 7.0, "screen_tl"),
            width=48.0,
            height=20.0,
        )
        ctx.begin_ui_frame(renderer)
        ctx.mount_component(svg)
        ctx.finalize_ui_frame()

        self.assertEqual(len(renderer.svg_batches), 1)
        self.assertEqual(len(renderer.svg_batches[0].commands), 1)
        cmd = renderer.svg_batches[0].commands[0]
        self.assertEqual(cmd.component_id, "logo")
        self.assertEqual((cmd.width, cmd.height), (48.0, 20.0))

    def test_app_context_sensor_denied_without_sensor_capability(self) -> None:
        from luvatrix_core.core.app_runtime import AppContext

        ctx = AppContext(
            matrix=WindowMatrix(1, 1),
            hdi=_FakeHDI(),  # type: ignore[arg-type]
            sensor_manager=_FakeSensor(),  # type: ignore[arg-type]
            granted_capabilities={"window.write"},
        )
        sample = ctx.read_sensor("thermal.temperature")
        self.assertEqual(sample.status, "DENIED")
        self.assertIsNone(sample.value)

    def test_app_context_sensor_rate_limit_blocks_abusive_reads(self) -> None:
        from luvatrix_core.core.app_runtime import AppContext

        ctx = AppContext(
            matrix=WindowMatrix(1, 1),
            hdi=_FakeHDI(),  # type: ignore[arg-type]
            sensor_manager=_FakeSensor(),  # type: ignore[arg-type]
            granted_capabilities={"window.write", "sensor.thermal"},
            sensor_read_min_interval_s=5.0,
        )
        first = ctx.read_sensor("thermal.temperature")
        second = ctx.read_sensor("thermal.temperature")
        self.assertEqual(first.status, "OK")
        self.assertEqual(second.status, "DENIED")

    def test_app_context_camera_sensor_requires_capability_and_sanitizes(self) -> None:
        from luvatrix_core.core.app_runtime import AppContext

        denied_ctx = AppContext(
            matrix=WindowMatrix(1, 1),
            hdi=_FakeHDI(),  # type: ignore[arg-type]
            sensor_manager=_CameraMetadataSensor(),  # type: ignore[arg-type]
            granted_capabilities={"window.write"},
        )
        denied = denied_ctx.read_sensor("camera.device")
        self.assertEqual(denied.status, "DENIED")
        self.assertIsNone(denied.value)

        allowed_ctx = AppContext(
            matrix=WindowMatrix(1, 1),
            hdi=_FakeHDI(),  # type: ignore[arg-type]
            sensor_manager=_CameraMetadataSensor(),  # type: ignore[arg-type]
            granted_capabilities={"window.write", "sensor.camera"},
            sensor_read_min_interval_s=0.0,
        )
        allowed = allowed_ctx.read_sensor("camera.device")
        self.assertEqual(allowed.status, "OK")
        assert isinstance(allowed.value, dict)
        self.assertEqual(
            allowed.value,
            {"available": True, "device_count": 2, "default_present": True},
        )

    def test_manifest_protocol_mismatch_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app.toml").write_text(
                "\n".join(
                    [
                        'app_id = "x"',
                        'protocol_version = "999"',
                        'entrypoint = "app_main:create"',
                        "required_capabilities = []",
                        "optional_capabilities = []",
                    ]
                )
            )
            (root / "app_main.py").write_text("def create():\n    return object()\n")
            runtime = AppRuntime(
                matrix=WindowMatrix(1, 1),
                hdi=HDIThread(source=_NoopHDISource()),
                sensor_manager=SensorManagerThread(providers={}),
            )
            with self.assertRaises(ValueError):
                runtime.load_manifest(root)

    def test_manifest_runtime_protocol_bounds_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app.toml").write_text(
                "\n".join(
                    [
                        'app_id = "x"',
                        'protocol_version = "1"',
                        'entrypoint = "app_main:create"',
                        'min_runtime_protocol_version = "2"',
                        "required_capabilities = []",
                        "optional_capabilities = []",
                    ]
                )
            )
            (root / "app_main.py").write_text("def create():\n    return object()\n")
            runtime = AppRuntime(
                matrix=WindowMatrix(1, 1),
                hdi=HDIThread(source=_NoopHDISource()),
                sensor_manager=SensorManagerThread(providers={}),
            )
            with self.assertRaises(ValueError):
                runtime.load_manifest(root)

    def test_required_capability_denial_fails_fast(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_app_files(root, lifecycle_expr="_LifecycleRecorder()")
            runtime = AppRuntime(
                matrix=WindowMatrix(1, 1),
                hdi=_FakeHDI(),  # type: ignore[arg-type]
                sensor_manager=_FakeSensor(),  # type: ignore[arg-type]
                capability_decider=lambda capability: capability != "window.write",
            )
            with self.assertRaises(PermissionError):
                runtime.run(root, max_ticks=1)

    def test_capability_audit_logger_receives_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_app_files(root, lifecycle_expr="_LifecycleRecorder()")
            events: list[dict[str, object]] = []
            runtime = AppRuntime(
                matrix=WindowMatrix(1, 1),
                hdi=_FakeHDI(),  # type: ignore[arg-type]
                sensor_manager=_FakeSensor(),  # type: ignore[arg-type]
                capability_decider=lambda capability: capability != "sensor.thermal",
                capability_audit_logger=events.append,
            )
            runtime.run(root, max_ticks=1, target_fps=1000)
            actions = {str(e.get("action")) for e in events}
            self.assertIn("granted_required", actions)
            self.assertIn("denied_optional", actions)

    def test_runtime_wires_context_and_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_app_files(root, lifecycle_expr="_LifecycleRecorder()")
            hdi = _FakeHDI()
            sensor = _FakeSensor()
            runtime = AppRuntime(
                matrix=WindowMatrix(1, 1),
                hdi=hdi,  # type: ignore[arg-type]
                sensor_manager=sensor,  # type: ignore[arg-type]
                capability_decider=lambda capability: True,
            )
            runtime.run(root, max_ticks=2, target_fps=1000)
            self.assertEqual(hdi.started, 1)
            self.assertEqual(hdi.stopped, 1)
            self.assertEqual(sensor.started, 1)
            self.assertEqual(sensor.stopped, 1)

    def test_runtime_stop_called_on_loop_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_app_files(root, lifecycle_expr="_LifecycleRaisesInLoop()")
            hdi = _FakeHDI()
            sensor = _FakeSensor()
            runtime = AppRuntime(
                matrix=WindowMatrix(1, 1),
                hdi=hdi,  # type: ignore[arg-type]
                sensor_manager=sensor,  # type: ignore[arg-type]
                capability_decider=lambda capability: True,
            )
            with self.assertRaises(RuntimeError):
                runtime.run(root, max_ticks=1, target_fps=1000)
            self.assertIsNotNone(runtime.last_error)
            self.assertEqual(hdi.stopped, 1)
            self.assertEqual(sensor.stopped, 1)

    def test_runtime_calls_on_tick_hook(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_app_files(root, lifecycle_expr="_LifecycleRecorder()")
            hdi = _FakeHDI()
            sensor = _FakeSensor()
            runtime = AppRuntime(
                matrix=WindowMatrix(1, 1),
                hdi=hdi,  # type: ignore[arg-type]
                sensor_manager=sensor,  # type: ignore[arg-type]
                capability_decider=lambda capability: True,
            )
            ticks = {"n": 0}

            def on_tick() -> None:
                ticks["n"] += 1

            runtime.run(root, max_ticks=3, target_fps=1000, on_tick=on_tick)
            self.assertGreaterEqual(ticks["n"], 3)


class _NoopHDISource:
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        return []


def _write_app_files(root: Path, lifecycle_expr: str) -> None:
    (root / "app.toml").write_text(
        "\n".join(
            [
                'app_id = "sample.app"',
                f'protocol_version = "{APP_PROTOCOL_VERSION}"',
                'entrypoint = "app_main:create"',
                'required_capabilities = ["window.write"]',
                'optional_capabilities = ["sensor.thermal"]',
            ]
        )
    )
    (root / "app_main.py").write_text(
        "\n".join(
            [
                "import torch",
                "from luvatrix_core.core.window_matrix import FullRewrite, WriteBatch",
                "",
                "class _LifecycleRecorder:",
                "    def __init__(self):",
                "        self.init_called = False",
                "        self.loop_calls = 0",
                "        self.stop_called = False",
                "",
                "    def init(self, ctx):",
                "        self.init_called = True",
                "        ctx.submit_write_batch(WriteBatch([FullRewrite(torch.zeros((1, 1, 4), dtype=torch.uint8))]))",
                "",
                "    def loop(self, ctx, dt):",
                "        self.loop_calls += 1",
                "        ctx.poll_hdi_events(16)",
                "        ctx.read_sensor('thermal.temperature')",
                "",
                "    def stop(self, ctx):",
                "        self.stop_called = True",
                "",
                "class _LifecycleRaisesInLoop(_LifecycleRecorder):",
                "    def loop(self, ctx, dt):",
                "        super().loop(ctx, dt)",
                "        raise RuntimeError('boom')",
                "",
                "def create():",
                f"    return {lifecycle_expr}",
            ]
        )
    )


if __name__ == "__main__":
    unittest.main()
