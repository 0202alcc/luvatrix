from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from luvatrix_core.platform.frame_pipeline import PresentationMode
from luvatrix_core.platform.macos.vulkan_backend import MoltenVKMacOSBackend
from luvatrix_core.platform.macos.window_system import MacOSWindowHandle


class _FakeWindowSystem:
    def create_window(
        self,
        width: int,
        height: int,
        title: str,
        use_metal_layer: bool = True,
        presentation_mode: PresentationMode | str = PresentationMode.STRETCH,
        lock_window_size: bool = False,
        menu_config=None,
        bar_color_rgba: tuple[int, int, int, int] | None = None,
    ) -> MacOSWindowHandle:
        _ = bar_color_rgba
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
            events = (out / "events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertTrue(any("capture_id" in line for line in events))
            captures = out / "captures"
            pngs = list(captures.glob("*.png"))
            self.assertTrue(pngs)

    def test_clipboard_screenshot_executes_without_filesystem_artifacts(self) -> None:
        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "debug_menu"
            backend.configure_debug_menu(app_id="examples.app", profile=self._profile(), artifact_dir=out)
            backend._write_png_bytes_to_clipboard = lambda _png: True  # type: ignore[attr-defined]
            result = backend.dispatch_debug_menu_action("debug.menu.capture.screenshot.clipboard")
            self.assertEqual(result.status, "EXECUTED")
            events = (out / "events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertTrue(any("debug.menu.capture.screenshot.clipboard" in line for line in events))
            payload = next(
                data
                for data in (json.loads(line) for line in events)
                if data.get("action_id") == "debug.menu.capture.screenshot.clipboard"
                and data.get("status") == "HANDLER_EXECUTED"
            )
            self.assertEqual(payload.get("clipboard_write"), "OK")
            captures = out / "captures"
            self.assertFalse(captures.exists())

    def test_recording_toggle_is_idempotent_start_stop(self) -> None:
        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "debug_menu"
            backend.configure_debug_menu(app_id="examples.app", profile=self._profile(), artifact_dir=out)
            start_result = backend.dispatch_debug_menu_action("debug.menu.capture.record.toggle")
            stop_result = backend.dispatch_debug_menu_action("debug.menu.capture.record.toggle")
            self.assertEqual(start_result.status, "EXECUTED")
            self.assertEqual(stop_result.status, "EXECUTED")
            manifests = list((out / "recordings").glob("*.json"))
            self.assertTrue(manifests)

    def test_frame_step_requires_replay_start_then_bundle_exports(self) -> None:
        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "debug_menu"
            backend.configure_debug_menu(app_id="examples.app", profile=self._profile(), artifact_dir=out)
            frame_step_before = backend.dispatch_debug_menu_action("debug.menu.frame.step")
            self.assertEqual(frame_step_before.status, "DISABLED")

            backend.dispatch_debug_menu_action("debug.menu.capture.screenshot")
            backend.dispatch_debug_menu_action("debug.menu.replay.start")
            backend.dispatch_debug_menu_action("debug.menu.perf.hud.toggle")
            frame_step_after = backend.dispatch_debug_menu_action("debug.menu.frame.step")
            self.assertEqual(frame_step_after.status, "EXECUTED")

            bundle = backend.dispatch_debug_menu_action("debug.menu.bundle.export")
            self.assertEqual(bundle.status, "EXECUTED")
            bundles = list((out / "bundles").glob("*.zip"))
            self.assertTrue(bundles)

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

    def test_origin_refs_toggle_updates_runtime_local_state(self) -> None:
        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "debug_menu"
            runtime_state = {"origin_refs_enabled": False}

            def _toggle() -> bool:
                runtime_state["origin_refs_enabled"] = not bool(runtime_state["origin_refs_enabled"])
                return bool(runtime_state["origin_refs_enabled"])

            backend.configure_debug_menu(
                app_id="examples.app",
                profile=self._profile(),
                artifact_dir=out,
                runtime_origin_refs_state_setter=_toggle,
            )
            first = backend.dispatch_debug_menu_action("debug.menu.overlay.origin_refs.toggle")
            second = backend.dispatch_debug_menu_action("debug.menu.overlay.origin_refs.toggle")
            self.assertEqual(first.status, "EXECUTED")
            self.assertEqual(second.status, "EXECUTED")
            self.assertFalse(runtime_state["origin_refs_enabled"])
            events = (out / "events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertTrue(any("debug.menu.overlay.origin_refs.toggle" in line for line in events))

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

    def test_functional_kill_switch_disables_actions(self) -> None:
        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        old = os.environ.get("LUVATRIX_MACOS_DEBUG_MENU_FUNCTIONAL_ACTIONS")
        os.environ["LUVATRIX_MACOS_DEBUG_MENU_FUNCTIONAL_ACTIONS"] = "0"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "debug_menu"
                backend.configure_debug_menu(app_id="examples.app", profile=self._profile(), artifact_dir=out)
                result = backend.dispatch_debug_menu_action("debug.menu.capture.screenshot")
                self.assertEqual(result.status, "DISABLED")
        finally:
            if old is None:
                os.environ.pop("LUVATRIX_MACOS_DEBUG_MENU_FUNCTIONAL_ACTIONS", None)
            else:
                os.environ["LUVATRIX_MACOS_DEBUG_MENU_FUNCTIONAL_ACTIONS"] = old
