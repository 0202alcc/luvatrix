from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from luvatrix_core.core.app_runtime import AppRuntime
from luvatrix_core.core.hdi_thread import HDIEventSource, HDIThread
from luvatrix_core.core.sensor_manager import SensorManagerThread
from luvatrix_core.core.window_matrix import WindowMatrix


class _NoopHDISource(HDIEventSource):
    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def poll_events(self, max_events: int):
        return []


def _build_runtime(*, host_os: str = "macos") -> AppRuntime:
    return AppRuntime(
        matrix=WindowMatrix(1, 1),
        hdi=HDIThread(source=_NoopHDISource()),
        sensor_manager=SensorManagerThread(providers={}),
        host_os=host_os,
        host_arch="arm64",
    )


def _write_manifest(root: Path, lines: list[str]) -> None:
    (root / "app.toml").write_text("\n".join(lines))
    (root / "app_main.py").write_text("def create():\n    return object()\n")


class DebugManifestPolicyTests(unittest.TestCase):
    def test_debug_manifest_defaults_keep_legacy_debug_root_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_manifest(
                root,
                [
                    'app_id = "x"',
                    'protocol_version = "2"',
                    'entrypoint = "app_main:create"',
                    "required_capabilities = []",
                    "optional_capabilities = []",
                ],
            )
            runtime = _build_runtime(host_os="macos")
            manifest = runtime.load_manifest(root)
            profile = runtime.resolve_debug_policy_profile(manifest)
            self.assertTrue(profile["supported"])
            self.assertTrue(profile["enable_default_debug_root"])
            self.assertEqual(profile["declared_capabilities"], ["debug.root.default"])

    def test_legacy_debug_conformance_requires_disable_approval(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_manifest(
                root,
                [
                    'app_id = "x"',
                    'protocol_version = "2"',
                    'entrypoint = "app_main:create"',
                    "required_capabilities = []",
                    "optional_capabilities = []",
                    "",
                    "[debug_policy]",
                    "enable_default_debug_root = false",
                ],
            )
            runtime = _build_runtime(host_os="macos")
            with self.assertRaisesRegex(ValueError, "disable_debug_root_approval"):
                runtime.load_manifest(root)

    def test_debug_manifest_policy_allows_explicit_disable_with_approval(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_manifest(
                root,
                [
                    'app_id = "x"',
                    'protocol_version = "2"',
                    'entrypoint = "app_main:create"',
                    "required_capabilities = []",
                    "optional_capabilities = []",
                    "",
                    "[debug_policy]",
                    "enable_default_debug_root = false",
                    'disable_debug_root_approval = "A-037-policy-review"',
                ],
            )
            runtime = _build_runtime(host_os="macos")
            manifest = runtime.load_manifest(root)
            profile = runtime.resolve_debug_policy_profile(manifest)
            self.assertFalse(profile["supported"])
            self.assertFalse(profile["enable_default_debug_root"])
            self.assertEqual(
                profile["unsupported_reason"],
                "disabled by manifest debug_policy with explicit approval",
            )

    def test_debug_manifest_rejects_unsupported_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_manifest(
                root,
                [
                    'app_id = "x"',
                    'protocol_version = "2"',
                    'entrypoint = "app_main:create"',
                    "required_capabilities = []",
                    "optional_capabilities = []",
                    "",
                    "[debug_policy]",
                    "schema_version = 2",
                ],
            )
            runtime = _build_runtime(host_os="macos")
            with self.assertRaisesRegex(ValueError, "schema_version"):
                runtime.load_manifest(root)

    def test_legacy_debug_conformance_non_macos_declares_explicit_stub(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_manifest(
                root,
                [
                    'app_id = "x"',
                    'protocol_version = "2"',
                    'entrypoint = "app_main:create"',
                    "required_capabilities = []",
                    "optional_capabilities = []",
                ],
            )
            runtime = _build_runtime(host_os="linux")
            manifest = runtime.load_manifest(root)
            profile = runtime.resolve_debug_policy_profile(manifest)
            self.assertFalse(profile["supported"])
            self.assertEqual(profile["declared_capabilities"], ["debug.policy.non_macos.stub"])
            self.assertEqual(profile["unsupported_reason"], "macOS-first phase: explicit stub only")


if __name__ == "__main__":
    unittest.main()
