from __future__ import annotations

import importlib.util
from pathlib import Path
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
