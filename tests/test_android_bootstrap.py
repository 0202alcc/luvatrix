from __future__ import annotations

import importlib.util
from pathlib import Path
import py_compile
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


BOOT = Path(__file__).resolve().parents[1] / "android" / "app" / "src" / "main" / "python" / "luvatrix_android_boot.py"
TEMPLATE_BOOT = (
    Path(__file__).resolve().parents[1]
    / "luvatrix_core"
    / "templates"
    / "native"
    / "android"
    / "app"
    / "src"
    / "main"
    / "python"
    / "luvatrix_android_boot.py"
)


def _load_boot_module():
    spec = importlib.util.spec_from_file_location("luvatrix_android_boot_test", BOOT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AndroidBootstrapTests(unittest.TestCase):
    def test_android_render_activity_uses_window_focus_and_visibility(self) -> None:
        boot = _load_boot_module()

        class _View:
            def __init__(self, *, focused: bool, visibility: int) -> None:
                self.focused = focused
                self.visibility = visibility

            def hasWindowFocus(self) -> bool:
                return self.focused

            def getWindowVisibility(self) -> int:
                return self.visibility

        self.assertTrue(boot._android_view_is_render_active(None))
        self.assertTrue(boot._android_view_is_render_active(_View(focused=True, visibility=0)))
        self.assertFalse(boot._android_view_is_render_active(_View(focused=False, visibility=0)))
        self.assertFalse(boot._android_view_is_render_active(_View(focused=True, visibility=4)))

    def test_android_template_defers_scene_matrix_storage(self) -> None:
        for boot_path in (BOOT, TEMPLATE_BOOT):
            boot_source = boot_path.read_text(encoding="utf-8")

            self.assertIn('lazy=render_mode == "scene"', boot_source)

    def test_loading_android_boot_does_not_mutate_process_import_paths(self) -> None:
        android_python_root = str(BOOT.parent)
        previous = list(sys.path)
        sys.path[:] = [entry for entry in sys.path if entry != android_python_root]
        try:
            _load_boot_module()
            self.assertNotIn(android_python_root, sys.path)
        finally:
            sys.path[:] = previous

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

    def test_run_app_vulkan_does_not_execute_import_probe_before_normal_launch(self) -> None:
        boot = _load_boot_module()
        boot.configure_android_tls = lambda: ""

        def unexpected_probe() -> str:
            raise AssertionError("normal launch must not execute app_main through import_probe")

        boot.import_probe = unexpected_probe
        def run_runtime(_presenter, *, before_lifecycle_init):
            before_lifecycle_init()
            return type("Result", (), {"ticks_run": 1, "frames_presented": 1})()

        boot._run_visual_runtime = run_runtime

        self.assertEqual(boot.run_app_vulkan("view"), "luvatrix visual ok")

    def test_run_app_vulkan_overlaps_tls_setup_and_joins_before_lifecycle_init(self) -> None:
        boot = _load_boot_module()
        tls_started = threading.Event()
        release_tls = threading.Event()
        lifecycle_ready = threading.Event()

        def configure_tls() -> str:
            tls_started.set()
            self.assertTrue(release_tls.wait(1.0))
            return "/app/cacert.pem"

        def run_runtime(_presenter, *, before_lifecycle_init):
            self.assertTrue(tls_started.wait(1.0))
            lifecycle_ready.set()
            before_lifecycle_init()
            return type("Result", (), {"ticks_run": 1, "frames_presented": 1})()

        boot.configure_android_tls = configure_tls
        boot._run_visual_runtime = run_runtime
        owner = threading.Thread(target=boot.run_app_vulkan, args=("view",))
        owner.start()

        self.assertTrue(lifecycle_ready.wait(1.0))
        self.assertTrue(owner.is_alive())
        release_tls.set()
        owner.join(1.0)

        self.assertFalse(owner.is_alive())

    def test_runtime_restarts_when_rebound_while_previous_owner_exits(self) -> None:
        boot = _load_boot_module()
        first_started = threading.Event()
        release_first = threading.Event()
        second_started = threading.Event()
        release_second = threading.Event()
        calls: list[object] = []
        boot.configure_android_tls = lambda: ""
        boot.import_probe = lambda: ""

        def run_runtime(presenter, *, before_lifecycle_init):
            before_lifecycle_init()
            calls.append(presenter.current_view())
            if len(calls) == 1:
                first_started.set()
                self.assertTrue(release_first.wait(1.0))
            else:
                second_started.set()
                self.assertTrue(release_second.wait(1.0))
            return type("Result", (), {"ticks_run": 1, "frames_presented": 1})()

        boot._run_visual_runtime = run_runtime
        owner = threading.Thread(target=boot.run_app_vulkan, args=("first-view",))
        owner.start()
        self.assertTrue(first_started.wait(1.0))

        self.assertEqual(boot.run_app_vulkan("replacement-view"), "luvatrix visual reattached")
        release_first.set()

        self.assertTrue(second_started.wait(1.0))
        release_second.set()
        owner.join(1.0)
        self.assertFalse(owner.is_alive())
        self.assertEqual(calls, ["first-view", "replacement-view"])

    def test_configured_android_package_materializes_bytecode_without_source_wrapper(self) -> None:
        boot = _load_boot_module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = root / "compiled_app"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "app.toml").write_text('app_id = "compiled"\n', encoding="utf-8")
            source = package / "app_main.py"
            source.write_text("def create(): return object()\n", encoding="utf-8")
            py_compile.compile(str(source), cfile=str(package / "app_main.pyc"), doraise=True)
            source.unlink()
            (root / "luvatrix_launch_config.json").write_text(
                '{"app_dir": "compiled_app"}\n',
                encoding="utf-8",
            )
            old_root = boot._ROOT
            sys.path.insert(0, str(root))
            try:
                boot._ROOT = root
                materialized = boot._app_dir()
            finally:
                boot._ROOT = old_root
                sys.path.remove(str(root))
                sys.modules.pop("compiled_app", None)

            self.assertTrue((materialized / "app_main.pyc").exists())
            self.assertFalse((materialized / "app_main.py").exists())

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

    def test_runtime_render_mode_leaves_manifest_resolution_to_unified_runtime(self) -> None:
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
                self.assertEqual(boot._runtime_render_mode({"render_mode": "auto"}), "auto")
            finally:
                boot._ROOT = old_root

    def test_visual_runtime_only_defers_matrix_for_resolved_scene_mode(self) -> None:
        boot = _load_boot_module()
        constructed: list[tuple[str, object]] = []

        class _UnifiedRuntime:
            def __init__(self, *, matrix, render_mode, **_kwargs) -> None:
                constructed.append((render_mode, matrix))

            def run_app(self, *_args, **_kwargs):
                return type("Result", (), {"ticks_run": 1, "frames_presented": 0})()

        class _Dependency:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

        with (
            patch("luvatrix_core.core.unified_runtime.UnifiedRuntime", _UnifiedRuntime),
            patch("luvatrix_core.core.hdi_thread.HDIThread", _Dependency),
            patch("luvatrix_core.core.sensor_manager.SensorManagerThread", _Dependency),
            patch("luvatrix_core.platform.android.hdi_source.AndroidHDISource", _Dependency),
            patch("luvatrix_core.platform.android.hdi_source.clear_android_input_events"),
            patch("luvatrix_core.platform.android.sensors.make_android_sensor_providers", return_value={}),
        ):
            boot._app_dir = lambda _config=None: Path("/tmp/luvatrix-scene-test")
            boot._runtime_dimensions = lambda _view, _config: (393, 852)
            boot._runtime_frame_rates = lambda _view, _config: (120, 60)
            for render_mode in ("scene", "matrix", "auto"):
                boot._launch_config = lambda mode=render_mode: {
                    "render_mode": mode,
                    "low_latency_mode": False,
                }
                boot._run_visual_runtime(None)

        matrices = {render_mode: matrix for render_mode, matrix in constructed}
        self.assertFalse(matrices["scene"].is_materialized)
        self.assertTrue(matrices["matrix"].is_materialized)
        self.assertTrue(matrices["auto"].is_materialized)

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
