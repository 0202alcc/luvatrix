from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest

from luvatrix.app import (
    MissingOptionalDependencyError,
    PLATFORM_IOS,
    PLATFORM_MACOS,
    check_app_install,
    load_app_manifest,
    validate_app_install,
)


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
            "import luvatrix.app\n"
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
