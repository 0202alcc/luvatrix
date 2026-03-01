from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

from luvatrix_core.core.app_runtime import AppRuntime
from luvatrix_core.core.hdi_thread import HDIEvent, HDIEventSource, HDIThread
from luvatrix_core.core.sensor_manager import SensorManagerThread
from luvatrix_core.core.window_matrix import WindowMatrix

APP_DIR = Path(__file__).resolve().parents[1] / "examples" / "app_protocol" / "planes_v2_poc"
MODULE_PATH = APP_DIR / "app_main.py"
SPEC = importlib.util.spec_from_file_location("planes_v2_poc_app_main", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"failed to load module spec for {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

PlanesV2PocApp = MODULE.PlanesV2PocApp
PLANES_JSON = MODULE.PLANES_JSON


class _NoopHDISource(HDIEventSource):
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        _ = (window_active, ts_ns)
        return []


class PlanesV2PocExampleTests(unittest.TestCase):
    def test_planes_poc_compiles_and_inherits_web_metadata(self) -> None:
        app = PlanesV2PocApp()
        self.assertEqual(app._metadata.title, "Planes v2 Proof")
        self.assertEqual(app._metadata.tab_title, "Planes v2 Proof")
        self.assertEqual(app._metadata.icon, "assets/logo.svg")
        self.assertEqual(app._metadata.tab_icon, "assets/logo.svg")
        self.assertTrue(PLANES_JSON.exists())

    def test_planes_poc_runtime_runs_with_protocol_v2(self) -> None:
        matrix = WindowMatrix(height=96, width=160)
        runtime = AppRuntime(
            matrix=matrix,
            hdi=HDIThread(source=_NoopHDISource()),
            sensor_manager=SensorManagerThread(providers={}),
            capability_decider=lambda capability: True,
        )

        manifest = runtime.load_manifest(APP_DIR)
        self.assertEqual(manifest.protocol_version, "2")

        runtime.run(APP_DIR, max_ticks=2, target_fps=120)
        self.assertEqual(matrix.revision, 2)
        frame = matrix.read_snapshot()
        self.assertEqual(tuple(frame.shape), (96, 160, 4))
        self.assertGreater(float(frame[:, :, :3].float().mean().item()), 0.0)


if __name__ == "__main__":
    unittest.main()
