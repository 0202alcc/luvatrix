from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from luvatrix_core.scaffold import (
    default_native_project_dir,
    init_app,
    init_native_project,
    resolve_native_project_dir,
)


class ScaffoldTests(unittest.TestCase):
    def test_init_app_creates_standalone_basic_app(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = Path(td) / "my_app"

            result = init_app(app)

            self.assertEqual(result.path, app)
            self.assertTrue((app / "app.toml").exists())
            self.assertTrue((app / "app_main.py").exists())
            self.assertIn("from luvatrix.app import App", (app / "app_main.py").read_text(encoding="utf-8"))
            self.assertIn('platform_support = ["macos", "ios", "android", "web"]', (app / "app.toml").read_text(encoding="utf-8"))

    def test_init_app_camera_defaults_to_android_support(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = Path(td) / "camera"

            init_app(app, template="camera")

            self.assertIn('platform_support = ["android"]', (app / "app.toml").read_text(encoding="utf-8"))
            self.assertIn("luvatrix validate-app . --render android-emulator", (app / "README.md").read_text(encoding="utf-8"))

    def test_init_native_android_copies_template(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = Path(td) / "app"
            app.mkdir()
            out = app / "android"

            result = init_native_project(app, target="android", out=out)

            self.assertEqual(result.path, out)
            self.assertTrue((out / "settings.gradle.kts").exists())
            self.assertTrue((out / "app" / "src" / "main" / "python" / "luvatrix_android_boot.py").exists())
            self.assertFalse((out / "app" / "src" / "main" / "python" / "luvatrix_core").exists())

    def test_init_native_ios_copies_template(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = Path(td) / "app"
            app.mkdir()
            out = app / "ios"

            init_native_project(app, target="ios", out=out)

            self.assertTrue((out / "project.yml").exists())
            self.assertTrue((out / "Luvatrix" / "AppDelegate.swift").exists())
            self.assertFalse((out / "PyPackages").exists())

    def test_resolve_native_project_prefers_explicit_then_app_local_default(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = Path(td) / "app"
            explicit = Path(td) / "android"
            default = default_native_project_dir(app, "android")
            default.mkdir(parents=True)

            self.assertEqual(resolve_native_project_dir(app, "android"), default)
            self.assertEqual(resolve_native_project_dir(app, "android", explicit), explicit)


if __name__ == "__main__":
    unittest.main()
