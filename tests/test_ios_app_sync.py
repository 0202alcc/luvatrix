from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from luvatrix_core.platform.ios.runner import _sync_ios_app_dir


class IOSAppSyncTests(unittest.TestCase):
    def test_sync_skips_native_project_nested_inside_app_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = Path(td) / "app"
            ios_dir = app / "ios"
            packages_dir = ios_dir / "PyPackages-simulator"
            app.mkdir()
            (app / "app.toml").write_text('app_id = "x"\n', encoding="utf-8")
            (app / "app_main.py").write_text("def create(): pass\n", encoding="utf-8")
            (app / ".luvatrix").mkdir()
            (ios_dir / "Luvatrix").mkdir(parents=True)
            stale = packages_dir / "luvatrix_app" / "stale.py"
            stale.parent.mkdir(parents=True)
            stale.write_text("", encoding="utf-8")

            app_dest = _sync_ios_app_dir(app, ios_dir, packages_dir)

            self.assertEqual(app_dest, packages_dir / "luvatrix_app")
            self.assertTrue((app_dest / "app.toml").exists())
            self.assertTrue((app_dest / "app_main.py").exists())
            self.assertFalse((app_dest / "ios").exists())
            self.assertFalse((app_dest / ".luvatrix").exists())
            self.assertFalse((app_dest / "stale.py").exists())

    def test_sync_keeps_sibling_native_project_layout_working(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = Path(td) / "app"
            ios_dir = Path(td) / "ios"
            packages_dir = ios_dir / "PyPackages-device"
            app.mkdir()
            (app / "app.toml").write_text('app_id = "x"\n', encoding="utf-8")
            (app / "assets").mkdir()
            (app / "assets" / "icon.png").write_bytes(b"png")

            app_dest = _sync_ios_app_dir(app, ios_dir, packages_dir)

            self.assertTrue((app_dest / "app.toml").exists())
            self.assertTrue((app_dest / "assets" / "icon.png").exists())


if __name__ == "__main__":
    unittest.main()
