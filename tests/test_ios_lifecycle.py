from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from luvatrix_core.platform.ios import lifecycle
from luvatrix_core.platform.ios.runner import _resolve_ios_project, _sync_luvatrix_packages


class IOSLifecycleTests(unittest.TestCase):
    def tearDown(self) -> None:
        lifecycle.set_app_active(True)

    def test_lifecycle_defaults_active_and_can_transition(self) -> None:
        lifecycle.set_app_active(True)
        self.assertTrue(lifecycle.is_app_active())

        lifecycle.set_app_active(False)
        self.assertFalse(lifecycle.is_app_active())
        inactive = lifecycle.snapshot()
        self.assertEqual(inactive["ios_app_active"], 0)

        lifecycle.set_app_active(True)
        self.assertTrue(lifecycle.is_app_active())
        active = lifecycle.snapshot()
        self.assertEqual(active["ios_app_active"], 1)
        self.assertGreaterEqual(
            active["ios_lifecycle_transition_count"],
            inactive["ios_lifecycle_transition_count"],
        )

    def test_resolve_ios_project_uses_app_local_scaffold(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = Path(td) / "app"
            project = app / ".luvatrix" / "ios"
            project.mkdir(parents=True)

            self.assertEqual(_resolve_ios_project(app), project)

    def test_resolve_ios_project_requires_scaffold(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(RuntimeError, "init-native"):
                _resolve_ios_project(Path(td) / "app")

    def test_sync_luvatrix_packages_prunes_non_ios_platform_runtimes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            packages_dir = Path(td) / "PyPackages"

            _sync_luvatrix_packages(packages_dir)

            platform_root = packages_dir / "luvatrix_core" / "platform"
            self.assertTrue((platform_root / "ios").is_dir())
            self.assertFalse((platform_root / "android").exists())
            self.assertFalse((platform_root / "macos").exists())
            self.assertFalse((platform_root / "web").exists())
            native_templates = packages_dir / "luvatrix_core" / "templates" / "native"
            self.assertTrue((native_templates / "ios").is_dir())
            self.assertFalse((native_templates / "android").exists())


if __name__ == "__main__":
    unittest.main()
