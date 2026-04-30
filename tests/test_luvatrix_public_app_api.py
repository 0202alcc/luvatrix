from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest

from luvatrix.app import (
    App,
    CoordinateFrames,
    InputState,
    MissingOptionalDependencyError,
    PLATFORM_IOS,
    PLATFORM_MACOS,
    apply_hdi_events,
    check_app_install,
    load_app_manifest,
    validate_app_install,
)
from luvatrix_core.core.app_runtime import AppRuntime
from luvatrix_core.core.hdi_thread import HDIEvent, HDIThread
from luvatrix_core.core.sensor_manager import SensorManagerThread
from luvatrix_core.core.window_matrix import WindowMatrix


class _NoopHDISource:
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        return []


def _write_app(root: Path, platform_support: list[str] | None = None) -> None:
    lines = [
        'app_id = "tests.public_api"',
        'protocol_version = "1"',
        'entrypoint = "app_main:create"',
        "required_capabilities = []",
        "optional_capabilities = []",
    ]
    if platform_support is not None:
        values = ", ".join(f'"{item}"' for item in platform_support)
        lines.append(f"platform_support = [{values}]")
    (root / "app.toml").write_text("\n".join(lines), encoding="utf-8")
    (root / "app_main.py").write_text(
        "class App:\n"
        "    def init(self, ctx): pass\n"
        "    def loop(self, ctx, dt): pass\n"
        "    def stop(self, ctx): pass\n"
        "def create():\n"
        "    return App()\n",
        encoding="utf-8",
    )


class LuvatrixPublicAppApiTests(unittest.TestCase):
    def test_v3_manifest_parses_render_and_display_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_app(root, [PLATFORM_MACOS, PLATFORM_IOS])
            text = (root / "app.toml").read_text(encoding="utf-8")
            text = text.replace('protocol_version = "1"', 'protocol_version = "3"')
            text += "\n[display]\ndefault_coordinate_frame = \"cartesian_bl\"\n"
            text += "\n[render]\npreferred = \"auto\"\nfallbacks = [\"scene\", \"ui\", \"matrix\"]\n"
            (root / "app.toml").write_text(text, encoding="utf-8")

            manifest = load_app_manifest(root, host_os="macos", host_arch="arm64")

            self.assertEqual(manifest.protocol_version, "3")
            self.assertEqual(manifest.display_default_coordinate_frame, "cartesian_bl")
            self.assertEqual(manifest.render_preferred, "auto")
            self.assertEqual(manifest.render_fallbacks, ["scene", "ui", "matrix"])

    def test_public_manifest_loader_supports_macos_ios_platform_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_app(root, [PLATFORM_MACOS, PLATFORM_IOS])

            manifest = load_app_manifest(root, host_os="macos", host_arch="arm64")

            self.assertEqual(manifest.platform_support, [PLATFORM_MACOS, PLATFORM_IOS])

    def test_headless_validation_has_no_optional_extra_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_app(root, [PLATFORM_MACOS, PLATFORM_IOS])

            validation = check_app_install(root, render="headless", host_os="macos", host_arch="arm64")

            self.assertTrue(validation.ok)
            self.assertEqual(validation.required_extras, ())
            self.assertEqual(validation.missing_modules, ())
            self.assertEqual(validation.resolved_variant.variant_id, "default")

    def test_macos_vulkan_validation_reports_actionable_optional_extra_hint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_app(root, [PLATFORM_MACOS])

            validation = check_app_install(
                root,
                render="macos",
                host_arch="arm64",
                module_available=lambda name: False,
            )

            self.assertFalse(validation.ok)
            self.assertEqual(validation.required_extras, ("macos", "vulkan"))
            self.assertIn("AppKit", validation.missing_modules)
            self.assertIn("vulkan", validation.missing_modules)
            self.assertIn('pip install "luvatrix[macos,vulkan]"', validation.install_hint)

    def test_validate_app_install_raises_for_missing_render_extra(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_app(root, [PLATFORM_MACOS])

            with self.assertRaises(MissingOptionalDependencyError) as cm:
                validate_app_install(
                    root,
                    render="macos-metal",
                    host_arch="arm64",
                    module_available=lambda name: False,
                )

            self.assertIn('pip install "luvatrix[macos]"', str(cm.exception))

    def test_importing_public_api_and_cli_does_not_import_platform_modules(self) -> None:
        code = (
            "import sys\n"
            "from luvatrix.app import App, InputState\n"
            "import main\n"
            "blocked = [name for name in sys.modules "
            "if name.startswith('luvatrix_core.platform.macos') "
            "or name.startswith('luvatrix_core.platform.web')]\n"
            "if blocked:\n"
            "    raise SystemExit('\\n'.join(blocked))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_public_app_subclass_loads_as_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app.toml").write_text(
                "\n".join(
                    [
                        'app_id = "tests.v3_app"',
                        'protocol_version = "3"',
                        'entrypoint = "app_main:create"',
                        'required_capabilities = ["window.write"]',
                        "optional_capabilities = []",
                        "",
                        "[render]",
                        'preferred = "matrix"',
                        'fallbacks = ["matrix"]',
                    ]
                ),
                encoding="utf-8",
            )
            (root / "app_main.py").write_text(
                "from luvatrix.app import App\n"
                "class Demo(App):\n"
                "    def render(self):\n"
                "        with self.frame(clear=(1, 2, 3, 255)) as frame:\n"
                "            frame.rect(x=0, y=0, width=1, height=1, color=(255, 255, 255, 255))\n"
                "def create():\n"
                "    return Demo()\n",
                encoding="utf-8",
            )
            runtime = AppRuntime(
                matrix=WindowMatrix(2, 2),
                hdi=HDIThread(source=_NoopHDISource()),
                sensor_manager=SensorManagerThread(providers={}),
            )

            lifecycle = runtime.load_lifecycle(root, "app_main:create")
            self.assertIsInstance(lifecycle, App)
            runtime.run(root, max_ticks=1, target_fps=1000)

    def test_migrated_hello_world_renders_non_empty_headless_frame(self) -> None:
        root = Path(__file__).resolve().parents[1]
        matrix = WindowMatrix(32, 32)
        runtime = AppRuntime(
            matrix=matrix,
            hdi=HDIThread(source=_NoopHDISource()),
            sensor_manager=SensorManagerThread(providers={}),
        )

        runtime.run(root / "examples" / "hello_world", max_ticks=1, target_fps=1000)

        self.assertGreater(int(matrix.read_snapshot().sum()), 0)

    def test_input_state_reduces_hdi_events(self) -> None:
        class _Event:
            def __init__(self, device, event_type, payload, status="OK") -> None:
                self.device = device
                self.event_type = event_type
                self.status = status
                self.payload = payload

        state = InputState()
        apply_hdi_events(
            state,
            [
                _Event("keyboard", "key_down", {"key": "a", "phase": "down", "active_keys": ["a"]}),
                _Event("mouse", "pointer_move", {"x": 12.0, "y": 34.0}),
                _Event("trackpad", "scroll", {"delta_x": 1.0, "delta_y": -2.0}),
            ],
        )

        self.assertEqual(state.key_last, "a")
        self.assertEqual(state.keys_down, ["a"])
        self.assertTrue(state.mouse_in_window)
        self.assertEqual(state.pointer, (12.0, 34.0))
        self.assertEqual(state.scroll_y, -2.0)

    def test_coordinate_switch_helper_maps_default_keys(self) -> None:
        class _Ctx:
            def __init__(self) -> None:
                self.default_coordinate_frame = "screen_tl"

            def set_default_coordinate_frame(self, frame_name: str) -> None:
                self.default_coordinate_frame = frame_name

            def from_render_coords(self, x, y, frame=None):
                return (x, y)

            def to_render_coords(self, x, y, frame=None):
                return (x, y)

        coords = CoordinateFrames(_Ctx())  # type: ignore[arg-type]
        self.assertEqual(coords.bind_switch_keys(InputState(key_last="2", key_state="down")), "cartesian_bl")
        self.assertEqual(coords.default, "cartesian_bl")
        self.assertEqual(coords.bind_switch_keys(InputState(key_last="c", key_state="down")), "cartesian_center")

    def test_platform_heavy_dependencies_are_optional_extras(self) -> None:
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        with pyproject.open("rb") as f:
            data = tomllib.load(f)

        base_deps = data["project"]["dependencies"]
        optional = data["project"]["optional-dependencies"]

        self.assertNotIn("vulkan>=1.3.275.1", base_deps)
        self.assertFalse(any(dep.startswith("pyobjc-") for dep in base_deps))
        self.assertIn("vulkan>=1.3.275.1", optional["vulkan"])
        self.assertTrue(any(dep.startswith("pyobjc-core") for dep in optional["macos"]))


if __name__ == "__main__":
    unittest.main()
