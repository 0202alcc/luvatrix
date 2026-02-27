from __future__ import annotations

from pathlib import Path
import unittest

from luvatrix_core.core.app_runtime import AppRuntime
from luvatrix_core.core.hdi_thread import HDIEvent, HDIEventSource, HDIThread
from luvatrix_core.core.sensor_manager import SensorManagerThread
from luvatrix_core.core.window_matrix import WindowMatrix


class _NoopHDISource(HDIEventSource):
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        return []


class PlotDemoAppProtocolTests(unittest.TestCase):
    def test_plot_demo_runs_and_writes_frames(self) -> None:
        app_dir = Path(__file__).resolve().parents[1] / "examples" / "plots" / "plot_demo"
        matrix = WindowMatrix(height=96, width=160)
        runtime = AppRuntime(
            matrix=matrix,
            hdi=HDIThread(source=_NoopHDISource()),
            sensor_manager=SensorManagerThread(providers={}),
            capability_decider=lambda capability: True,
        )

        runtime.run(app_dir, max_ticks=3, target_fps=120)
        self.assertEqual(matrix.revision, 3)

        frame = matrix.read_snapshot()
        self.assertEqual(tuple(frame.shape), (96, 160, 4))
        # Plot rendering should write non-uniform RGB values.
        self.assertGreater(float(frame[:, :, :3].float().std().item()), 0.0)

    def test_static_plot_2d_runs_and_writes_static_frame(self) -> None:
        app_dir = Path(__file__).resolve().parents[1] / "examples" / "plots" / "static_plot_2d"
        matrix = WindowMatrix(height=96, width=160)
        runtime = AppRuntime(
            matrix=matrix,
            hdi=HDIThread(source=_NoopHDISource()),
            sensor_manager=SensorManagerThread(providers={}),
            capability_decider=lambda capability: True,
        )

        runtime.run(app_dir, max_ticks=3, target_fps=120)
        # Static app writes once in init only.
        self.assertEqual(matrix.revision, 1)

        frame = matrix.read_snapshot()
        self.assertEqual(tuple(frame.shape), (96, 160, 4))
        self.assertGreater(float(frame[:, :, :3].float().std().item()), 0.0)

    def test_dynamic_plot_2d_runs_and_writes_frames(self) -> None:
        app_dir = Path(__file__).resolve().parents[1] / "examples" / "plots" / "dynamic_plot_2d"
        matrix = WindowMatrix(height=96, width=160)
        runtime = AppRuntime(
            matrix=matrix,
            hdi=HDIThread(source=_NoopHDISource()),
            sensor_manager=SensorManagerThread(providers={}),
            capability_decider=lambda capability: True,
        )

        runtime.run(app_dir, max_ticks=3, target_fps=120)
        # App starts empty and writes once per loop tick.
        self.assertEqual(matrix.revision, 3)

        frame = matrix.read_snapshot()
        self.assertEqual(tuple(frame.shape), (96, 160, 4))
        self.assertGreater(float(frame[:, :, :3].float().std().item()), 0.0)


if __name__ == "__main__":
    unittest.main()
