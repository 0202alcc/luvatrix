from __future__ import annotations

import unittest
from unittest.mock import patch
from pathlib import Path
import sys
import tempfile
import types

from luvatrix_core.platform.frame_pipeline import PresentationMode
from main import _is_free_threaded_runtime, _resolve_presentation_mode, _warn_if_not_free_threaded, main


class MainCliTests(unittest.TestCase):
    def test_macos_defaults_to_pixel_preserve(self) -> None:
        self.assertEqual(_resolve_presentation_mode("macos", None), PresentationMode.PIXEL_PRESERVE)

    def test_headless_defaults_to_stretch(self) -> None:
        self.assertEqual(_resolve_presentation_mode("headless", None), PresentationMode.STRETCH)

    def test_android_defaults_to_stretch(self) -> None:
        self.assertEqual(_resolve_presentation_mode("android-emulator", None), PresentationMode.STRETCH)

    def test_explicit_presentation_mode_is_respected(self) -> None:
        self.assertEqual(
            _resolve_presentation_mode("macos", "preserve_aspect"),
            PresentationMode.PRESERVE_ASPECT,
        )

    def test_free_threaded_runtime_detects_disabled_gil(self) -> None:
        with patch("main.sys._is_gil_enabled", return_value=False, create=True):
            self.assertTrue(_is_free_threaded_runtime())

    def test_warn_if_not_free_threaded_logs_warning(self) -> None:
        with (
            patch("main.sys._is_gil_enabled", return_value=True, create=True),
            patch("main.LOGGER.warning") as warning,
        ):
            _warn_if_not_free_threaded()
        warning.assert_called_once()

    def test_warn_if_not_free_threaded_skips_warning_for_free_threaded_runtime(self) -> None:
        with (
            patch("main.sys._is_gil_enabled", return_value=False, create=True),
            patch("main.LOGGER.warning") as warning,
        ):
            _warn_if_not_free_threaded()
        warning.assert_not_called()

    def test_run_app_web_delegates_to_static_server(self) -> None:
        calls = []
        fake_server = types.ModuleType("luvatrix_core.platform.web.server")
        fake_server.serve_web_app = lambda app_dir, host, port: calls.append((str(app_dir), host, port))
        with (
            patch.object(sys, "argv", ["luvatrix", "run-app", "examples/full_suite_interactive", "--render", "web"]),
            patch.dict(sys.modules, {"luvatrix_core.platform.web.server": fake_server}),
            patch("main.validate_app_install"),
            patch("main._warn_if_not_free_threaded") as warning,
        ):
            main()

        self.assertEqual(calls, [("examples/full_suite_interactive", "127.0.0.1", 8765)])
        warning.assert_not_called()

    def test_run_web_shortcut_uses_static_server_without_app_dev_server(self) -> None:
        calls = []
        fake_server = types.ModuleType("luvatrix_core.platform.web.server")
        fake_server.serve_web_app = lambda app_dir, host, port: calls.append((str(app_dir), host, port))
        with (
            patch.object(sys, "argv", ["luvatrix", "run", "web", "examples/full_suite_interactive"]),
            patch.dict(sys.modules, {"luvatrix_core.platform.web.server": fake_server}),
        ):
            main()

        self.assertEqual(calls, [("examples/full_suite_interactive", "127.0.0.1", 8765)])

    def test_run_web_shortcut_uses_app_dev_server_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir).resolve()
            (app_dir / "dev_web.py").write_text("print('dev server')\n", encoding="utf-8")
            with (
                patch.object(sys, "argv", ["luvatrix", "run", "web", str(app_dir), "--host", "localhost", "--port", "8001"]),
                patch("main.subprocess.run") as subprocess_run,
            ):
                main()

        subprocess_run.assert_called_once_with(
            [sys.executable, str(app_dir / "dev_web.py"), "--host", "localhost", "--port", "8001"],
            cwd=app_dir,
            check=True,
        )

    def test_validate_app_command_reports_valid_app(self) -> None:
        class _Manifest:
            app_id = "tests.app"

        class _Variant:
            variant_id = "default"

        class _Validation:
            manifest = _Manifest()
            resolved_variant = _Variant()
            render = "headless"
            target_platform = "macos"
            required_extras = ()

        with (
            patch.object(sys, "argv", ["luvatrix", "validate-app", "example", "--render", "headless"]),
            patch("main.validate_app_install", return_value=_Validation()) as validate,
            patch("builtins.print") as print_,
        ):
            main()

        validate.assert_called_once()
        self.assertIn("app valid", print_.call_args[0][0])

    def test_init_app_command_uses_scaffold(self) -> None:
        with (
            patch.object(sys, "argv", ["luvatrix", "init-app", "my_app", "--template", "camera", "--force"]),
            patch("luvatrix_core.scaffold.init_app") as init_app,
        ):
            init_app.return_value.path = "my_app"
            main()

        init_app.assert_called_once()
        self.assertEqual(init_app.call_args.kwargs["template"], "camera")
        self.assertTrue(init_app.call_args.kwargs["force"])

    def test_init_native_command_uses_scaffold(self) -> None:
        with (
            patch.object(
                sys,
                "argv",
                ["luvatrix", "init-native", "my_app", "--target", "android", "--out", "my_app/android", "--force"],
            ),
            patch("luvatrix_core.scaffold.init_native_project") as init_native,
        ):
            init_native.return_value.path = "my_app/android"
            main()

        init_native.assert_called_once()
        self.assertEqual(init_native.call_args.kwargs["target"], "android")
        self.assertTrue(init_native.call_args.kwargs["force"])

    def test_upgrade_native_command_uses_scaffold(self) -> None:
        with (
            patch.object(
                sys,
                "argv",
                ["luvatrix", "upgrade-native", "my_app", "--target", "android", "--out", "my_app/android"],
            ),
            patch("luvatrix_core.scaffold.upgrade_native_project") as upgrade_native,
        ):
            upgrade_native.return_value.path = "my_app/android"
            upgrade_native.return_value.updated_files = ()
            upgrade_native.return_value.added_files = ()
            upgrade_native.return_value.removed_files = ()
            upgrade_native.return_value.conflicted_files = ()
            upgrade_native.return_value.adopted = False
            main()

        upgrade_native.assert_called_once()
        self.assertEqual(upgrade_native.call_args.kwargs["target"], "android")


if __name__ == "__main__":
    unittest.main()
