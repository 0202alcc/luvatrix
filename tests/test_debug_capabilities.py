from __future__ import annotations

import unittest

from luvatrix_core.core.debug_menu import (
    DEFAULT_DEBUG_MENU_ACTIONS,
    DebugMenuActionSpec,
    build_debug_capability_registry,
    validate_debug_menu_actions,
)


class DebugCapabilityRegistryTests(unittest.TestCase):
    def test_default_registry_is_one_to_one(self) -> None:
        registry = build_debug_capability_registry()
        self.assertEqual(len(registry), len(DEFAULT_DEBUG_MENU_ACTIONS))
        self.assertEqual(len(set(registry.keys())), len(DEFAULT_DEBUG_MENU_ACTIONS))
        self.assertEqual(len(set(registry.values())), len(DEFAULT_DEBUG_MENU_ACTIONS))

    def test_default_ids_follow_canonical_format(self) -> None:
        validate_debug_menu_actions(DEFAULT_DEBUG_MENU_ACTIONS)

    def test_clipboard_screenshot_action_is_declared(self) -> None:
        registry = build_debug_capability_registry()
        self.assertIn("debug.menu.capture.screenshot.clipboard", registry)
        self.assertEqual(
            registry["debug.menu.capture.screenshot.clipboard"],
            "debug.capture.screenshot.clipboard",
        )

    def test_duplicate_menu_ids_are_rejected(self) -> None:
        duplicated = DEFAULT_DEBUG_MENU_ACTIONS + (
            DebugMenuActionSpec(
                menu_id=DEFAULT_DEBUG_MENU_ACTIONS[0].menu_id,
                capability_id="debug.capture.new",
                label="Duplicate Menu ID",
            ),
        )
        with self.assertRaises(ValueError):
            validate_debug_menu_actions(duplicated)

    def test_duplicate_capability_ids_are_rejected(self) -> None:
        duplicated = DEFAULT_DEBUG_MENU_ACTIONS + (
            DebugMenuActionSpec(
                menu_id="debug.menu.capture.new",
                capability_id=DEFAULT_DEBUG_MENU_ACTIONS[0].capability_id,
                label="Duplicate Capability ID",
            ),
        )
        with self.assertRaises(ValueError):
            validate_debug_menu_actions(duplicated)


if __name__ == "__main__":
    unittest.main()
