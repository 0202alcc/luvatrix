from __future__ import annotations

import unittest

from luvatrix_core.core.debug_menu import (
    build_debug_capability_registry,
    debug_menu_adapter_capability_matrix,
    default_debug_menu_adapter_specs,
)


class DebugMenuAdapterTests(unittest.TestCase):
    def test_adapter_specs_cover_macos_windows_linux(self) -> None:
        specs = default_debug_menu_adapter_specs()
        self.assertEqual(tuple(spec.platform for spec in specs), ("macos", "windows", "linux", "web"))

    def test_macos_adapter_declares_supported_menu_and_capabilities(self) -> None:
        specs = default_debug_menu_adapter_specs()
        macos = next(spec for spec in specs if spec.platform == "macos")
        registry = build_debug_capability_registry()
        self.assertTrue(macos.supported)
        self.assertEqual(tuple(registry.keys()), macos.supported_menu_ids)
        self.assertEqual(tuple(registry.values()), macos.declared_capabilities)
        self.assertIsNone(macos.unsupported_reason)

    def test_non_macos_adapters_are_explicit_stubs(self) -> None:
        specs = default_debug_menu_adapter_specs()
        for spec in specs:
            if spec.platform == "macos":
                continue
            self.assertFalse(spec.supported)
            self.assertEqual(spec.supported_menu_ids, ())
            self.assertGreaterEqual(len(spec.declared_capabilities), 1)
            self.assertTrue(spec.declared_capabilities[0].startswith(f"debug.adapter.{spec.platform}.stub"))
            self.assertIn("debug.overlay.origin_refs.stub", spec.declared_capabilities)
            self.assertEqual(spec.unsupported_reason, "macOS-first phase: explicit stub only")

    def test_matrix_uses_explicit_fields_for_unsupported_platforms(self) -> None:
        matrix = debug_menu_adapter_capability_matrix()
        self.assertEqual(matrix["windows"]["supported"], False)
        self.assertEqual(matrix["windows"]["supported_menu_ids"], [])
        self.assertEqual(matrix["linux"]["supported"], False)
        self.assertEqual(matrix["linux"]["supported_menu_ids"], [])
        self.assertEqual(matrix["web"]["supported"], False)
        self.assertEqual(matrix["web"]["supported_menu_ids"], [])
        self.assertIsInstance(matrix["windows"]["declared_capabilities"], list)
        self.assertIsInstance(matrix["linux"]["declared_capabilities"], list)
        self.assertIsInstance(matrix["web"]["declared_capabilities"], list)


if __name__ == "__main__":
    unittest.main()
