from __future__ import annotations

import importlib.util
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


BOOT_PATH = Path(__file__).resolve().parents[1] / "android" / "app" / "src" / "main" / "python" / "luvatrix_android_boot.py"
SPEC = importlib.util.spec_from_file_location("luvatrix_android_boot_test", BOOT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"failed to load module spec for {BOOT_PATH}")
BOOT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BOOT
SPEC.loader.exec_module(BOOT)


class AndroidBootConfigTests(unittest.TestCase):
    def test_auto_render_mode_is_left_for_unified_runtime_to_resolve(self) -> None:
        with patch.object(BOOT, "_app_dir") as app_dir:
            self.assertEqual(BOOT._runtime_render_mode({"render_mode": "auto"}), "auto")

        app_dir.assert_not_called()

    def test_configured_synced_app_wins_over_stale_full_suite_package(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            configured = root / "luvatrix_app"
            configured.mkdir()
            (configured / "app.toml").write_text('app_id = "examples.camera"\n', encoding="utf-8")
            (configured / "app_main.py").write_text("def create(): pass\n", encoding="utf-8")

            stale = root / "examples" / "full_suite_interactive"
            stale.mkdir(parents=True)
            (stale / "app.toml").write_text('app_id = "examples.full_suite_interactive"\n', encoding="utf-8")
            (stale / "app_main.py").write_text("def create(): pass\n", encoding="utf-8")

            (root / "luvatrix_launch_config.json").write_text(
                json.dumps({"app_dir": "luvatrix_app", "source_app_dir": "examples/camera"}),
                encoding="utf-8",
            )

            old_root = BOOT._ROOT
            try:
                BOOT._ROOT = root
                self.assertEqual(BOOT._app_dir(), configured.resolve())
            finally:
                BOOT._ROOT = old_root

    def test_configured_missing_app_does_not_fall_back_to_full_suite(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stale = root / "examples" / "full_suite_interactive"
            stale.mkdir(parents=True)
            (stale / "app.toml").write_text('app_id = "examples.full_suite_interactive"\n', encoding="utf-8")
            (stale / "app_main.py").write_text("def create(): pass\n", encoding="utf-8")
            (root / "luvatrix_launch_config.json").write_text(
                json.dumps({"app_dir": "luvatrix_app", "source_app_dir": "examples/camera"}),
                encoding="utf-8",
            )

            old_root = BOOT._ROOT
            try:
                BOOT._ROOT = root
                app_dir = BOOT._app_dir()
            finally:
                BOOT._ROOT = old_root

            self.assertIn('app_id = "examples.camera"', (app_dir / "app.toml").read_text(encoding="utf-8"))

    def test_configured_missing_files_materialize_configured_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "luvatrix_launch_config.json").write_text(
                json.dumps({"app_dir": "luvatrix_app", "source_app_dir": "examples/camera"}),
                encoding="utf-8",
            )

            class _Bundle:
                APP_TOML = 'app_id = "examples.camera"\n'
                APP_MAIN = "def create(): pass\n"

            old_root = BOOT._ROOT
            try:
                BOOT._ROOT = root
                with patch.object(importlib, "import_module", return_value=_Bundle):
                    app_dir = BOOT._app_dir()
            finally:
                BOOT._ROOT = old_root

            self.assertEqual((app_dir / "app.toml").read_text(encoding="utf-8"), _Bundle.APP_TOML)
            self.assertEqual((app_dir / "app_main.py").read_text(encoding="utf-8"), _Bundle.APP_MAIN)
            self.assertIn("examples_camera", str(app_dir))

    def test_import_configured_app_main_registers_module_for_dataclasses(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            configured = root / "luvatrix_app"
            configured.mkdir()
            (configured / "app.toml").write_text('app_id = "examples.camera"\n', encoding="utf-8")
            (configured / "app_main.py").write_text(
                "from dataclasses import dataclass\n"
                "@dataclass\n"
                "class Probe:\n"
                "    value: int\n",
                encoding="utf-8",
            )
            (root / "luvatrix_launch_config.json").write_text(
                json.dumps({"app_dir": "luvatrix_app"}),
                encoding="utf-8",
            )

            old_root = BOOT._ROOT
            try:
                BOOT._ROOT = root
                BOOT._import_configured_app_main()
            finally:
                BOOT._ROOT = old_root
                sys.modules.pop("luvatrix_configured_app_main", None)


if __name__ == "__main__":
    unittest.main()
