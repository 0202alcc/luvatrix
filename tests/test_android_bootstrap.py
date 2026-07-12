from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


BOOT = Path(__file__).resolve().parents[1] / "android" / "app" / "src" / "main" / "python" / "luvatrix_android_boot.py"


def _load_boot_module():
    spec = importlib.util.spec_from_file_location("luvatrix_android_boot_test", BOOT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AndroidBootstrapTests(unittest.TestCase):
    def test_android_presenter_replays_latest_matrix_frame_when_view_rebinds(self) -> None:
        boot = _load_boot_module()

        class _View:
            def __init__(self) -> None:
                self.frames: list[tuple[bytes, int, int, int]] = []

            def presentRgba(self, rgba: bytes, revision: int, width: int, height: int) -> None:
                self.frames.append((rgba, revision, width, height))

        first = _View()
        second = _View()
        presenter = boot._AndroidViewPresenter()
        presenter.bind(first)
        presenter.presentRgba(b"rgba", 7, 1, 1)
        presenter.unbind(first)
        presenter.bind(second)

        self.assertEqual(first.frames, [(b"rgba", 7, 1, 1)])
        self.assertEqual(second.frames, [(b"rgba", 7, 1, 1)])

    def test_android_presenter_replays_latest_scene_when_view_rebinds(self) -> None:
        boot = _load_boot_module()

        class _View:
            def __init__(self) -> None:
                self.scenes: list[tuple[str, int, int, int, str]] = []

            def presentScene(self, payload: str, revision: int, width: int, height: int, mode: str) -> None:
                self.scenes.append((payload, revision, width, height, mode))

        first = _View()
        second = _View()
        presenter = boot._AndroidViewPresenter()
        presenter.bind(first)
        presenter.presentScene("[]", 11, 393, 852, "retained")
        presenter.unbind(first)
        presenter.bind(second)

        expected = [("[]", 11, 393, 852, "retained")]
        self.assertEqual(first.scenes, expected)
        self.assertEqual(second.scenes, expected)

    def test_run_app_vulkan_rebinds_without_starting_duplicate_runtime(self) -> None:
        boot = _load_boot_module()
        calls: list[object] = []
        boot.configure_android_tls = lambda: ""
        boot.import_probe = lambda: ""
        boot._RUNTIME_RUNNING = True
        boot._ANDROID_PRESENTER.bind = calls.append

        result = boot.run_app_vulkan("replacement-view")

        self.assertEqual(result, "luvatrix visual reattached")
        self.assertEqual(calls, ["replacement-view"])

    def test_default_frame_rates_are_two_x_refresh_for_app_and_refresh_for_present(self) -> None:
        boot = _load_boot_module()

        self.assertEqual(boot._runtime_frame_rates(None, {"refresh_rate_hz": 60}), (120, 60))
        self.assertEqual(boot._runtime_frame_rates(None, {"refresh_rate_hz": 120}), (240, 120))

    def test_explicit_frame_rates_override_refresh_defaults(self) -> None:
        boot = _load_boot_module()

        self.assertEqual(
            boot._runtime_frame_rates(None, {"refresh_rate_hz": 120, "target_fps": 90, "present_fps": 45}),
            (90, 45),
        )

    def test_frame_rates_can_read_view_refresh(self) -> None:
        boot = _load_boot_module()

        class _View:
            def displayRefreshRateHz(self) -> float:
                return 90.0

        self.assertEqual(boot._runtime_frame_rates(_View(), {}), (180, 90))

    def test_runtime_render_mode_honors_explicit_config_before_manifest(self) -> None:
        boot = _load_boot_module()

        self.assertEqual(boot._runtime_render_mode({"render_mode": "scene"}), "scene")

    def test_runtime_render_mode_reads_manifest_when_config_is_auto(self) -> None:
        boot = _load_boot_module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app = root / "luvatrix_app"
            app.mkdir()
            (app / "app.toml").write_text(
                'app_id = "x"\n'
                "[render]\n"
                'preferred = "matrix"\n',
                encoding="utf-8",
            )
            (app / "app_main.py").write_text("def create(): pass\n", encoding="utf-8")
            (root / "luvatrix_launch_config.json").write_text('{"app_dir": "luvatrix_app"}\n', encoding="utf-8")
            old_root = boot._ROOT
            try:
                boot._ROOT = root
                self.assertEqual(boot._runtime_render_mode({"render_mode": "auto"}), "matrix")
            finally:
                boot._ROOT = old_root

    def test_camera_app_defaults_to_120_present_even_when_display_reports_60(self) -> None:
        boot = _load_boot_module()

        self.assertEqual(
            boot._runtime_frame_rates(
                None,
                {"refresh_rate_hz": 60, "source_app_dir": "/tmp/examples/camera"},
            ),
            (240, 120),
        )

    def test_low_latency_mode_applies_to_view(self) -> None:
        boot = _load_boot_module()

        class _View:
            calls: list[tuple[int, int]]

            def __init__(self) -> None:
                self.calls = []

            def applyLowLatencyMode(self, target_fps: int, present_fps: int) -> None:
                self.calls.append((target_fps, present_fps))

        view = _View()

        boot._apply_low_latency_mode(view, target_fps=240, present_fps=120)

        self.assertEqual(view.calls, [(240, 120)])

    def test_low_latency_truthy_parsing(self) -> None:
        boot = _load_boot_module()

        self.assertTrue(boot._truthy(None, default=True))
        self.assertTrue(boot._truthy("on"))
        self.assertFalse(boot._truthy("off", default=True))


if __name__ == "__main__":
    unittest.main()
