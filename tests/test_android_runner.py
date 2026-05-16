from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from luvatrix_core.platform.android.runner import (
    DEFAULT_ANDROID_PACKAGE,
    _adb_prefix,
    _android_subprocess_env,
    _find_emulator_binary,
    build_android_debug_apk,
    write_android_launch_config,
)


class AndroidRunnerTests(unittest.TestCase):
    def test_write_launch_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            app = project / "example"
            app.mkdir()

            path = write_android_launch_config(app, project_dir=project, render_scale=0.75, render_mode="scene")

            self.assertEqual(path, project / "app" / "src" / "main" / "assets" / "luvatrix_launch_config.json")
            text = path.read_text(encoding="utf-8")
            self.assertIn('"app_dir": "luvatrix_app"', text)
            self.assertNotIn('"native_width"', text)
            self.assertIn('"render_mode": "scene"', text)
            self.assertIn('"render_scale": 0.75', text)

    def test_write_launch_config_includes_manifest_display_size(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            app = project / "example"
            app.mkdir()
            (app / "app.toml").write_text(
                "[display]\n"
                "native_width = 393\n"
                "native_height = 852\n",
                encoding="utf-8",
            )

            path = write_android_launch_config(app, project_dir=project)

            text = path.read_text(encoding="utf-8")
            self.assertIn('"native_width": 393', text)
            self.assertIn('"native_height": 852', text)

    def test_build_reports_missing_gradle_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(RuntimeError, "Gradle wrapper"):
                build_android_debug_apk(Path(td))

    def test_default_package_name(self) -> None:
        self.assertEqual(DEFAULT_ANDROID_PACKAGE, "com.luvatrix.app")

    def test_android_env_drops_conflicting_deprecated_sdk_root(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "ANDROID_HOME": "/opt/homebrew/share/android-commandlinetools",
                "ANDROID_SDK_ROOT": "/Users/example/Library/Android/sdk",
            },
            clear=True,
        ):
            env = _android_subprocess_env()

        self.assertEqual(env["ANDROID_HOME"], "/opt/homebrew/share/android-commandlinetools")
        self.assertNotIn("ANDROID_SDK_ROOT", env)

    def test_adb_prefix_reports_no_connected_devices(self) -> None:
        class _Result:
            returncode = 0
            stdout = "List of devices attached\n\n"
            stderr = ""

        with patch("luvatrix_core.platform.android.runner.subprocess.run", return_value=_Result()):
            with self.assertRaisesRegex(RuntimeError, "No Android emulator/device"):
                _adb_prefix("adb")

    def test_find_emulator_binary_uses_sdk_home_when_not_on_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            sdk = Path(td)
            binary = sdk / "emulator" / "emulator"
            binary.parent.mkdir(parents=True)
            binary.write_text("", encoding="utf-8")
            with (
                patch("luvatrix_core.platform.android.runner.shutil.which", return_value=None),
                patch.dict("os.environ", {"ANDROID_HOME": str(sdk)}, clear=True),
            ):
                self.assertEqual(_find_emulator_binary(), binary)


if __name__ == "__main__":
    unittest.main()
