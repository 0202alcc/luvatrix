from __future__ import annotations

import unittest

from luvatrix_core.core.debug_capture import (
    REQUIRED_BUNDLE_MANIFEST_KEYS,
    build_debug_bundle_export,
    build_debug_bundle_manifest,
    bundle_has_required_artifact_classes,
    debug_capture_platform_capability_matrix,
)
from luvatrix_core.core.debug_menu import build_debug_capability_registry


class DebugBundleContractTests(unittest.TestCase):
    def test_bundle_manifest_has_required_fields(self) -> None:
        manifest = build_debug_bundle_manifest(
            bundle_id="bundle-001",
            platform="macos",
            exported_at_utc="2026-03-05T22:00:00Z",
            provenance_id="run-001",
            artifact_paths=("captures/screen.png", "replay/replay.json", "perf/hud.json", "provenance/meta.json"),
            artifact_classes=("captures", "replay", "perf", "provenance"),
        )
        for key in REQUIRED_BUNDLE_MANIFEST_KEYS:
            self.assertIn(key, manifest)

    def test_bundle_export_zip_path_is_deterministic_for_bundle_id(self) -> None:
        export = build_debug_bundle_export(
            bundle_id="bundle-abc",
            platform="macos",
            exported_at_utc="2026-03-05T22:00:00Z",
            provenance_id="run-002",
            artifact_paths=("captures/screen.png", "replay/replay.json", "perf/hud.json", "provenance/meta.json"),
            artifact_classes=("captures", "replay", "perf", "provenance"),
            output_dir="artifacts/debug",
        )
        self.assertEqual(export.zip_path, "artifacts/debug/bundle-abc.zip")
        self.assertEqual(export.manifest["bundle_id"], "bundle-abc")

    def test_bundle_validator_requires_all_artifact_classes(self) -> None:
        complete_manifest = build_debug_bundle_manifest(
            bundle_id="bundle-complete",
            platform="macos",
            exported_at_utc="2026-03-05T22:00:00Z",
            provenance_id="run-003",
            artifact_paths=("captures/screen.png", "replay/replay.json", "perf/hud.json", "provenance/meta.json"),
            artifact_classes=("captures", "replay", "perf", "provenance"),
        )
        incomplete_manifest = build_debug_bundle_manifest(
            bundle_id="bundle-incomplete",
            platform="macos",
            exported_at_utc="2026-03-05T22:00:00Z",
            provenance_id="run-004",
            artifact_paths=("captures/screen.png", "replay/replay.json", "perf/hud.json"),
            artifact_classes=("captures", "replay", "perf"),
        )
        self.assertTrue(bundle_has_required_artifact_classes(complete_manifest))
        self.assertFalse(bundle_has_required_artifact_classes(incomplete_manifest))

    def test_debug_menu_declares_bundle_export_capability(self) -> None:
        registry = build_debug_capability_registry()
        self.assertEqual(registry["debug.menu.bundle.export"], "debug.bundle.export")

    def test_bundle_non_macos_is_explicit_stub(self) -> None:
        matrix = debug_capture_platform_capability_matrix()
        self.assertIn("debug.bundle.stub", matrix["windows"]["declared_capabilities"])
        self.assertIn("debug.bundle.stub", matrix["linux"]["declared_capabilities"])


if __name__ == "__main__":
    unittest.main()
