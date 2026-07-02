from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from luvatrix_core.platform.android.runner import (
    DEFAULT_ANDROID_PACKAGE,
    _adb_prefix,
    _android_subprocess_env,
    _android_python_packages_for_app,
    _find_emulator_binary,
    _resolve_android_project,
    build_android_debug_apk,
    force_stop_android_app,
    sync_android_python_assets,
    write_android_launch_config,
)


class AndroidRunnerTests(unittest.TestCase):
    def test_write_launch_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            app = project / "example"
            app.mkdir()

            path = write_android_launch_config(app, project_dir=project, render_scale=0.75, render_mode="scene")

            self.assertEqual(
                path,
                (project / "app" / "src" / "main" / "assets" / "luvatrix_launch_config.json").resolve(),
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn('"app_dir": "luvatrix_app"', text)
            self.assertNotIn('"native_width"', text)
            self.assertIn('"low_latency_mode": true', text)
            self.assertIn('"render_mode": "scene"', text)
            self.assertIn('"render_scale": 0.75', text)

    def test_write_launch_config_can_disable_low_latency_mode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            app = project / "example"
            app.mkdir()

            path = write_android_launch_config(app, project_dir=project, low_latency_mode=False)

            text = path.read_text(encoding="utf-8")
            self.assertIn('"low_latency_mode": false', text)

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

    def test_build_android_debug_apk_resolves_relative_project_dir_before_chdir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "android"
            project.mkdir()
            (project / "gradlew").write_text("#!/usr/bin/env sh\n", encoding="utf-8")
            apk = project / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
            apk.parent.mkdir(parents=True)
            apk.write_bytes(b"apk")
            old_cwd = Path.cwd()
            calls: list[tuple[list[str], Path]] = []

            def _run(args, **kwargs):
                calls.append((list(args), Path(kwargs["cwd"])))

            try:
                os.chdir(root)
                with patch("luvatrix_core.platform.android.runner.subprocess.run", side_effect=_run):
                    self.assertEqual(build_android_debug_apk(Path("android")), apk.resolve())
            finally:
                os.chdir(old_cwd)

            self.assertEqual(calls, [([str((project / "gradlew").resolve()), "assembleDebug"], project.resolve())])

    def test_default_package_name(self) -> None:
        self.assertEqual(DEFAULT_ANDROID_PACKAGE, "com.luvatrix.app")

    def test_force_stop_android_app_uses_adb_shell_am(self) -> None:
        class _Result:
            returncode = 0
            stdout = "List of devices attached\nserial\tdevice\n"
            stderr = ""

        calls: list[list[str]] = []

        def _run(args, **kwargs):
            _ = kwargs
            calls.append(list(args))
            return _Result()

        with (
            patch("luvatrix_core.platform.android.runner.shutil.which", return_value="adb"),
            patch("luvatrix_core.platform.android.runner.subprocess.run", side_effect=_run),
        ):
            force_stop_android_app(package_name="com.example.app", device_id="serial")

        self.assertIn(["adb", "-s", "serial", "shell", "am", "force-stop", "com.example.app"], calls)

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

    def test_resolve_android_project_uses_app_local_scaffold(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = Path(td) / "app"
            project = app / ".luvatrix" / "android"
            project.mkdir(parents=True)

            self.assertEqual(_resolve_android_project(app), project.resolve())

    def test_resolve_android_project_requires_scaffold(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(RuntimeError, "init-native"):
                _resolve_android_project(Path(td) / "app")

    def test_sync_android_python_assets_copies_installed_packages_and_app(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "android"
            app = root / "app"
            app.mkdir()
            (app / "app.toml").write_text('app_id = "x"\n', encoding="utf-8")
            (app / "app_main.py").write_text("def create(): pass\n", encoding="utf-8")
            assets = project / "app" / "src" / "main" / "assets"
            assets.mkdir(parents=True)
            (assets / "luvatrix_launch_config.json").write_text("{}", encoding="utf-8")
            stale_plot = project / "app" / "src" / "main" / "python" / "luvatrix_plot"
            stale_ui = project / "app" / "src" / "main" / "python" / "luvatrix_ui"
            stale_plot.mkdir(parents=True)
            stale_ui.mkdir(parents=True)

            sync_android_python_assets(app, project_dir=project)

            py_root = project / "app" / "src" / "main" / "python"
            self.assertTrue((py_root / "luvatrix").is_dir())
            self.assertTrue((py_root / "luvatrix_core").is_dir())
            self.assertFalse((py_root / "luvatrix_ui").exists())
            self.assertFalse((py_root / "luvatrix_plot").exists())
            platform_root = py_root / "luvatrix_core" / "platform"
            self.assertTrue((platform_root / "android").is_dir())
            self.assertFalse((platform_root / "ios").exists())
            self.assertFalse((platform_root / "macos").exists())
            self.assertFalse((platform_root / "web").exists())
            native_templates = py_root / "luvatrix_core" / "templates" / "native"
            self.assertTrue((native_templates / "android").is_dir())
            self.assertFalse((native_templates / "ios").exists())
            self.assertTrue((py_root / "luvatrix_app" / "app.toml").exists())
            self.assertTrue((py_root / "examples" / "app" / "_luvatrix_bundle.py").exists())
            self.assertTrue((py_root / "luvatrix_launch_config.json").exists())

    def test_sync_android_python_assets_ignores_app_owned_native_project(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = Path(td) / "app"
            project = app / "android"
            app.mkdir()
            project.mkdir()
            (app / "app.toml").write_text('app_id = "x"\n', encoding="utf-8")
            (app / "app_main.py").write_text("def create(): pass\n", encoding="utf-8")
            assets = project / "app" / "src" / "main" / "assets"
            assets.mkdir(parents=True)
            (assets / "luvatrix_launch_config.json").write_text("{}", encoding="utf-8")

            def _copy_app_tree(src, dst, *, ignore=None):
                self.assertEqual(Path(src), app)
                self.assertIsNotNone(ignore)
                ignored = ignore(str(app), ["app.toml", "app_main.py", "android"])
                self.assertIn("android", ignored)
                Path(dst).mkdir(parents=True)
                return dst

            with (
                patch("luvatrix_core.platform.android.runner.copy_package_tree_for_target"),
                patch("luvatrix_core.platform.android.runner._write_android_app_bundle"),
                patch("luvatrix_core.platform.android.runner.shutil.copytree", side_effect=_copy_app_tree),
            ):
                sync_android_python_assets(app, project_dir=project)

    def test_sync_android_python_assets_skips_nested_native_project_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = Path(td) / "app"
            project = app / "android"
            app.mkdir()
            (app / "app.toml").write_text('app_id = "x"\n', encoding="utf-8")
            (app / "app_main.py").write_text("def create(): pass\n", encoding="utf-8")
            assets = project / "app" / "src" / "main" / "assets"
            assets.mkdir(parents=True)
            (assets / "luvatrix_launch_config.json").write_text("{}", encoding="utf-8")
            stale_app = project / "app" / "src" / "main" / "python" / "luvatrix_app"
            stale_app.mkdir(parents=True)
            (stale_app / "old_generated.py").write_text("import luvatrix_plot\n", encoding="utf-8")

            sync_android_python_assets(app, project_dir=project)

            py_root = project / "app" / "src" / "main" / "python"
            self.assertTrue((py_root / "luvatrix_app" / "app.toml").exists())
            self.assertFalse((py_root / "luvatrix_app" / "android").exists())
            self.assertFalse((py_root / "luvatrix_plot").exists())

    def test_sync_android_python_assets_includes_only_imported_optional_packages(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "android"
            app = root / "app"
            app.mkdir()
            (app / "app.toml").write_text('app_id = "x"\n', encoding="utf-8")
            (app / "app_main.py").write_text(
                "from luvatrix_plot import figure\n"
                "from luvatrix_ui.component_schema import BoundingBox\n"
                "def create(): pass\n",
                encoding="utf-8",
            )

            self.assertEqual(
                _android_python_packages_for_app(app),
                ("luvatrix", "luvatrix_core", "luvatrix_ui", "luvatrix_plot"),
            )

            sync_android_python_assets(app, project_dir=project)

            py_root = project / "app" / "src" / "main" / "python"
            self.assertTrue((py_root / "luvatrix").is_dir())
            self.assertTrue((py_root / "luvatrix_core").is_dir())
            self.assertTrue((py_root / "luvatrix_ui").is_dir())
            self.assertTrue((py_root / "luvatrix_plot").is_dir())


if __name__ == "__main__":
    unittest.main()
