from __future__ import annotations

from pathlib import Path
import tomllib
import unittest

from luvatrix.app import validate_app_install
from luvatrix_core.core.app_runtime import AppRuntime
from luvatrix_core.core.hdi_thread import HDIEvent, HDIThread
from luvatrix_core.core.sensor_manager import SensorManagerThread
from luvatrix_core.core.window_matrix import WindowMatrix


APP_DIR = Path(__file__).resolve().parents[1] / "examples" / "hello_ios"


class _NoopHDISource:
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        return []


class HelloIosExampleTests(unittest.TestCase):
    def test_manifest_declares_ios_only(self) -> None:
        manifest = tomllib.loads((APP_DIR / "app.toml").read_text(encoding="utf-8"))

        self.assertEqual(manifest["platform_support"], ["ios"])
        self.assertEqual(manifest["entrypoint"], "app_main:create")

    def test_validates_for_ios_simulator_and_device(self) -> None:
        for render in ("ios-simulator", "ios-device"):
            with self.subTest(render=render):
                validation = validate_app_install(APP_DIR, render=render)
                self.assertTrue(validation.ok)

    def test_rejected_for_non_ios_targets(self) -> None:
        with self.assertRaises(Exception):
            validate_app_install(APP_DIR, render="android-emulator")

    def test_renders_non_empty_frame_as_ios(self) -> None:
        matrix = WindowMatrix(32, 32)
        runtime = AppRuntime(
            matrix=matrix,
            hdi=HDIThread(source=_NoopHDISource()),
            sensor_manager=SensorManagerThread(providers={}),
            host_os="ios",
        )

        runtime.run(APP_DIR, max_ticks=1, target_fps=1000)

        self.assertGreater(int(matrix.read_snapshot().sum()), 0)

    def test_has_app_owned_ios_native_project(self) -> None:
        native = APP_DIR / "ios"

        self.assertTrue((native / "project.yml").is_file())
        self.assertTrue((native / "scripts" / "setup_ios.sh").is_file())
        self.assertTrue((native / ".luvatrix-scaffold.json").is_file())


if __name__ == "__main__":
    unittest.main()
