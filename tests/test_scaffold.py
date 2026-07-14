from __future__ import annotations

from pathlib import Path
import hashlib
import json
import tempfile
import unittest

from luvatrix_core.scaffold import (
    default_native_project_dir,
    init_app,
    init_native_project,
    resolve_native_project_dir,
    upgrade_native_project,
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
            java_root = out / "app" / "src" / "main" / "java" / "com" / "luvatrix" / "app"
            self.assertTrue((java_root / "LuvatrixApplication.kt").exists())
            self.assertTrue((java_root / "StartupResources.kt").exists())
            manifest = (out / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
            self.assertIn('android:name=".LuvatrixApplication"', manifest)
            self.assertFalse((out / "app" / "src" / "main" / "python" / "luvatrix_core").exists())
            gitignore = (out / ".gitignore").read_text(encoding="utf-8")
            self.assertIn("app/src/main/assets/luvatrix_launch_config.json", gitignore)
            self.assertIn("app/src/main/python/luvatrix_launch_config.json", gitignore)
            self.assertIn(".luvatrix-scaffold-updates/", gitignore)
            metadata = json.loads((out / ".luvatrix-scaffold.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["schema_version"], 1)
            self.assertEqual(metadata["target"], "android")
            self.assertIn("settings.gradle.kts", metadata["files"])

    def test_upgrade_native_updates_unmodified_template_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = Path(td) / "app"
            app.mkdir()
            out = app / "android"
            init_native_project(app, target="android", out=out)
            relative = "settings.gradle.kts"
            path = out / relative
            latest = path.read_bytes()
            old = b"// old generated template\n"
            path.write_bytes(old)
            metadata_path = out / ".luvatrix-scaffold.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["files"][relative] = hashlib.sha256(old).hexdigest()
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

            result = upgrade_native_project(app, target="android", out=out)

            self.assertEqual(path.read_bytes(), latest)
            self.assertIn(path, result.updated_files)
            self.assertEqual(result.conflicted_files, ())

    def test_upgrade_native_preserves_custom_file_and_writes_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = Path(td) / "app"
            app.mkdir()
            out = app / "android"
            init_native_project(app, target="android", out=out)
            relative = "settings.gradle.kts"
            path = out / relative
            latest = path.read_bytes()
            custom = b"// app-owned customization\n"
            path.write_bytes(custom)
            metadata_path = out / ".luvatrix-scaffold.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["files"][relative] = hashlib.sha256(b"// prior template\n").hexdigest()
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

            result = upgrade_native_project(app, target="android", out=out)

            self.assertEqual(path.read_bytes(), custom)
            self.assertIn(path, result.conflicted_files)
            candidate = result.candidate_dir / relative
            self.assertEqual(candidate.read_bytes(), latest)

    def test_upgrade_native_legacy_scaffold_requires_explicit_adoption(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = Path(td) / "app"
            app.mkdir()
            out = app / "android"
            init_native_project(app, target="android", out=out)
            (out / ".luvatrix-scaffold.json").unlink()

            with self.assertRaisesRegex(RuntimeError, "--adopt"):
                upgrade_native_project(app, target="android", out=out)

            result = upgrade_native_project(app, target="android", out=out, adopt=True)

            self.assertTrue(result.adopted)
            self.assertTrue((out / ".luvatrix-scaffold.json").exists())

    def test_upgrade_native_rejects_unsafe_metadata_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = Path(td) / "app"
            app.mkdir()
            out = app / "android"
            init_native_project(app, target="android", out=out)
            metadata_path = out / ".luvatrix-scaffold.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["files"]["../outside"] = hashlib.sha256(b"x").hexdigest()
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "unsafe"):
                upgrade_native_project(app, target="android", out=out)

    def test_upgrade_native_rejects_managed_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app = root / "app"
            app.mkdir()
            out = app / "android"
            init_native_project(app, target="android", out=out)
            managed = out / "settings.gradle.kts"
            outside = root / "outside.gradle.kts"
            old = b"// prior generated template\n"
            outside.write_bytes(old)
            managed.unlink()
            managed.symlink_to(outside)
            metadata_path = out / ".luvatrix-scaffold.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["files"]["settings.gradle.kts"] = hashlib.sha256(old).hexdigest()
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "symlink"):
                upgrade_native_project(app, target="android", out=out)

            self.assertEqual(outside.read_bytes(), old)

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
