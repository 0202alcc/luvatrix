from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

import torch

from luvatrix_core.core.hdi_thread import HDIEvent, HDIThread
from luvatrix_core.core.energy_safety import EnergySafetyDecision
from luvatrix_core.core.sensor_manager import SensorManagerThread, SensorSample
from luvatrix_core.core.unified_runtime import UnifiedRuntime
from luvatrix_core.core.window_matrix import WindowMatrix
from luvatrix_core.targets.base import DisplayFrame, RenderTarget


class _NoopHDISource:
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        return []


class _FakeSensorManager(SensorManagerThread):
    def __init__(self) -> None:
        super().__init__(providers={})
        self.started = 0
        self.stopped = 0
        self.set_calls: list[tuple[str, bool, str]] = []

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def read_sensor(self, sensor_type: str) -> SensorSample:
        return SensorSample(
            sample_id=1,
            ts_ns=1,
            sensor_type=sensor_type,
            status="UNAVAILABLE",
            value=None,
            unit=None,
        )

    def set_sensor_enabled(self, sensor_type: str, enabled: bool, actor: str = "runtime") -> bool:
        self.set_calls.append((sensor_type, enabled, actor))
        return True


class _RecordingTarget(RenderTarget):
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.presented: list[DisplayFrame] = []
        self.pumped = 0

    def start(self) -> None:
        self.started += 1

    def present_frame(self, frame: DisplayFrame) -> None:
        self.presented.append(frame)

    def stop(self) -> None:
        self.stopped += 1

    def pump_events(self) -> None:
        self.pumped += 1

    def should_close(self) -> bool:
        return False


class _CriticalEnergySafety:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self) -> EnergySafetyDecision:
        self.calls += 1
        return EnergySafetyDecision(
            state="CRITICAL",
            throttle_multiplier=2.0,
            should_shutdown=True,
            reason="test",
            thermal_c=100.0,
            power_w=100.0,
        )


class UnifiedRuntimeTests(unittest.TestCase):
    def test_unified_runtime_runs_app_and_presents_frames(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            (app_dir / "app.toml").write_text(
                "\n".join(
                    [
                        'app_id = "test.unified"',
                        'protocol_version = "1"',
                        'entrypoint = "app_main:create"',
                        'required_capabilities = ["window.write"]',
                        'optional_capabilities = ["sensor.thermal"]',
                    ]
                )
            )
            (app_dir / "app_main.py").write_text(
                "\n".join(
                    [
                        "import torch",
                        "from luvatrix_core.core.window_matrix import FullRewrite, WriteBatch",
                        "",
                        "class _App:",
                        "    def __init__(self):",
                        "        self._t = 0",
                        "",
                        "    def init(self, ctx):",
                        "        pass",
                        "",
                        "    def loop(self, ctx, dt):",
                        "        self._t += 1",
                        "        frame = torch.tensor([[[self._t % 255, 0, 0, 255]]], dtype=torch.uint8)",
                        "        ctx.submit_write_batch(WriteBatch([FullRewrite(frame)]))",
                        "",
                        "    def stop(self, ctx):",
                        "        pass",
                        "",
                        "def create():",
                        "    return _App()",
                    ]
                )
            )
            matrix = WindowMatrix(height=1, width=1)
            target = _RecordingTarget()
            hdi = HDIThread(source=_NoopHDISource())
            sensors = _FakeSensorManager()
            runtime = UnifiedRuntime(
                matrix=matrix,
                target=target,
                hdi=hdi,
                sensor_manager=sensors,
                capability_decider=lambda cap: True,
            )
            result = runtime.run_app(app_dir, max_ticks=5, target_fps=1000)
            self.assertEqual(result.ticks_run, 5)
            self.assertGreaterEqual(result.frames_presented, 1)
            self.assertFalse(result.stopped_by_energy_safety)
            self.assertEqual(target.started, 1)
            self.assertEqual(target.stopped, 1)
            self.assertGreaterEqual(len(target.presented), 1)
            self.assertEqual(sensors.started, 1)
            self.assertEqual(sensors.stopped, 1)
            self.assertEqual(matrix.revision, 5)
            self.assertIn(("thermal.temperature", True, "unified_runtime"), sensors.set_calls)

    def test_unified_runtime_stops_when_energy_safety_requests_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            (app_dir / "app.toml").write_text(
                "\n".join(
                    [
                        'app_id = "test.energy.stop"',
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
                        "    def init(self, ctx):",
                        "        pass",
                        "    def loop(self, ctx, dt):",
                        "        raise AssertionError('loop should not execute when safety stops run')",
                        "    def stop(self, ctx):",
                        "        pass",
                        "def create():",
                        "    return _App()",
                    ]
                )
            )
            matrix = WindowMatrix(height=1, width=1)
            target = _RecordingTarget()
            hdi = HDIThread(source=_NoopHDISource())
            sensors = _FakeSensorManager()
            safety = _CriticalEnergySafety()
            runtime = UnifiedRuntime(
                matrix=matrix,
                target=target,
                hdi=hdi,
                sensor_manager=sensors,
                capability_decider=lambda cap: True,
                energy_safety=safety,
            )
            result = runtime.run_app(app_dir, max_ticks=5, target_fps=1000)
            self.assertEqual(result.ticks_run, 0)
            self.assertEqual(result.frames_presented, 0)
            self.assertTrue(result.stopped_by_energy_safety)
            self.assertEqual(safety.calls, 1)

    def test_unified_runtime_enables_new_av_sensor_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            (app_dir / "app.toml").write_text(
                "\n".join(
                    [
                        'app_id = "test.av.sensors"',
                        'protocol_version = "1"',
                        'entrypoint = "app_main:create"',
                        'required_capabilities = ["window.write"]',
                        'optional_capabilities = ["sensor.camera", "sensor.microphone", "sensor.speaker"]',
                    ]
                )
            )
            (app_dir / "app_main.py").write_text(
                "\n".join(
                    [
                        "class _App:",
                        "    def init(self, ctx):",
                        "        pass",
                        "    def loop(self, ctx, dt):",
                        "        pass",
                        "    def stop(self, ctx):",
                        "        pass",
                        "def create():",
                        "    return _App()",
                    ]
                )
            )
            matrix = WindowMatrix(height=1, width=1)
            target = _RecordingTarget()
            hdi = HDIThread(source=_NoopHDISource())
            sensors = _FakeSensorManager()
            runtime = UnifiedRuntime(
                matrix=matrix,
                target=target,
                hdi=hdi,
                sensor_manager=sensors,
                capability_decider=lambda cap: True,
            )
            runtime.run_app(app_dir, max_ticks=1, target_fps=1000)
            self.assertIn(("camera.device", True, "unified_runtime"), sensors.set_calls)
            self.assertIn(("microphone.device", True, "unified_runtime"), sensors.set_calls)
            self.assertIn(("speaker.device", True, "unified_runtime"), sensors.set_calls)

    def test_unified_runtime_can_cap_presentation_rate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            (app_dir / "app.toml").write_text(
                "\n".join(
                    [
                        'app_id = "test.present.cap"',
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
                        "import torch",
                        "from luvatrix_core.core.window_matrix import FullRewrite, WriteBatch",
                        "",
                        "class _App:",
                        "    def __init__(self):",
                        "        self._t = 0",
                        "    def init(self, ctx):",
                        "        pass",
                        "    def loop(self, ctx, dt):",
                        "        self._t += 1",
                        "        frame = torch.tensor([[[self._t % 255, 0, 0, 255]]], dtype=torch.uint8)",
                        "        ctx.submit_write_batch(WriteBatch([FullRewrite(frame)]))",
                        "    def stop(self, ctx):",
                        "        pass",
                        "def create():",
                        "    return _App()",
                    ]
                )
            )
            matrix = WindowMatrix(height=1, width=1)
            target = _RecordingTarget()
            hdi = HDIThread(source=_NoopHDISource())
            sensors = _FakeSensorManager()
            runtime = UnifiedRuntime(
                matrix=matrix,
                target=target,
                hdi=hdi,
                sensor_manager=sensors,
                capability_decider=lambda cap: True,
            )
            result = runtime.run_app(app_dir, max_ticks=30, target_fps=120, present_fps=1)
            self.assertEqual(result.ticks_run, 30)
            # With a very low present cap, runtime should present far fewer frames than ticks.
            self.assertLessEqual(result.frames_presented, 2)

    def test_unified_runtime_supports_v2_python_process_lane(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            worker_cmd = [sys.executable, "-u", "worker.py"]
            (app_dir / "app.toml").write_text(
                "\n".join(
                    [
                        'app_id = "test.v2.process"',
                        'protocol_version = "2"',
                        'entrypoint = "app_main:create"',
                        'required_capabilities = ["window.write"]',
                        "optional_capabilities = []",
                        "",
                        "[runtime]",
                        'kind = "process"',
                        'transport = "stdio_jsonl"',
                        f'command = ["{worker_cmd[0]}", "{worker_cmd[1]}", "{worker_cmd[2]}"]',
                    ]
                )
            )
            (app_dir / "app_main.py").write_text("def create():\n    return object()\n")
            (app_dir / "worker.py").write_text(
                "\n".join(
                    [
                        "from luvatrix_core.core.process_sdk import TickEvent, HostHello, run_stdio_jsonl",
                        "",
                        "class _Worker:",
                        "    def __init__(self):",
                        "        self._tick = 0",
                        "    def init(self, hello: HostHello) -> None:",
                        "        assert hello.width > 0 and hello.height > 0",
                        "    def tick(self, event: TickEvent):",
                        "        _ = event",
                        "        self._tick += 1",
                        "        return [{\"op\": \"solid_fill\", \"rgba\": [self._tick % 255, 0, 0, 255]}]",
                        "    def stop(self) -> None:",
                        "        pass",
                        "",
                        "if __name__ == \"__main__\":",
                        "    run_stdio_jsonl(_Worker())",
                    ]
                )
            )
            matrix = WindowMatrix(height=1, width=1)
            target = _RecordingTarget()
            hdi = HDIThread(source=_NoopHDISource())
            sensors = _FakeSensorManager()
            runtime = UnifiedRuntime(
                matrix=matrix,
                target=target,
                hdi=hdi,
                sensor_manager=sensors,
                capability_decider=lambda cap: True,
            )
            result = runtime.run_app(app_dir, max_ticks=3, target_fps=1000)
            self.assertEqual(result.ticks_run, 3)
            self.assertEqual(matrix.revision, 3)


if __name__ == "__main__":
    unittest.main()
