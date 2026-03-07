from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from luvatrix_core.platform.macos.vulkan_backend import MoltenVKMacOSBackend
from luvatrix_core.platform.macos.window_system import MacOSWindowHandle


class _FakeWindowSystem:
    def create_window(
        self,
        width: int,
        height: int,
        title: str,
        use_metal_layer: bool = True,
        preserve_aspect_ratio: bool = False,
        menu_config=None,
    ) -> MacOSWindowHandle:
        class _Layer:
            pass

        return MacOSWindowHandle(window=object(), layer=_Layer())

    def destroy_window(self, handle: MacOSWindowHandle) -> None:
        _ = handle

    def pump_events(self) -> None:
        return

    def is_window_open(self, handle: MacOSWindowHandle) -> bool:
        _ = handle
        return True


class MacOSMenuIntegrationTests(unittest.TestCase):
    def _profile(self, *, supported: bool = True, enabled: bool = True) -> dict[str, object]:
        return {
            "supported": supported,
            "enable_default_debug_root": enabled,
            "declared_capabilities": ["debug.root.default"] if supported and enabled else [],
            "unsupported_reason": None if supported and enabled else "policy disabled",
            "host_os": "macos",
        }

    def test_configure_debug_menu_writes_manifest(self) -> None:
        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "debug_menu"
            backend.configure_debug_menu(app_id="examples.app", profile=self._profile(), artifact_dir=out)
            manifest_path = out / "manifest.json"
            self.assertTrue(manifest_path.exists())
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["app_id"], "examples.app")
            self.assertTrue(payload["menu_wiring_enabled"])
            self.assertTrue(payload["profile"]["supported"])

    def test_dispatch_executes_when_profile_supported(self) -> None:
        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "debug_menu"
            backend.configure_debug_menu(app_id="examples.app", profile=self._profile(), artifact_dir=out)
            result = backend.dispatch_debug_menu_action("debug.menu.capture.screenshot")
            self.assertEqual(result.status, "EXECUTED")

    def test_dispatch_is_disabled_when_policy_disabled(self) -> None:
        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "debug_menu"
            backend.configure_debug_menu(
                app_id="examples.app",
                profile=self._profile(supported=True, enabled=False),
                artifact_dir=out,
            )
            result = backend.dispatch_debug_menu_action("debug.menu.capture.screenshot")
            self.assertEqual(result.status, "DISABLED")

    def test_rollback_flag_disables_wiring(self) -> None:
        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        old = os.environ.get("LUVATRIX_MACOS_DEBUG_MENU_WIRING")
        os.environ["LUVATRIX_MACOS_DEBUG_MENU_WIRING"] = "0"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "debug_menu"
                backend.configure_debug_menu(app_id="examples.app", profile=self._profile(), artifact_dir=out)
                result = backend.dispatch_debug_menu_action("debug.menu.capture.screenshot")
                self.assertEqual(result.status, "DISABLED")
        finally:
            if old is None:
                os.environ.pop("LUVATRIX_MACOS_DEBUG_MENU_WIRING", None)
            else:
                os.environ["LUVATRIX_MACOS_DEBUG_MENU_WIRING"] = old
