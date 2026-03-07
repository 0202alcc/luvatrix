from __future__ import annotations

import unittest
from unittest.mock import patch

from luvatrix_core.platform.macos import window_system


class _FakeNSObject:
    @classmethod
    def alloc(cls):
        return cls()


class _ExistingTarget:
    @classmethod
    def alloc(cls):
        return cls()


class MacOSWindowSystemTargetClassTests(unittest.TestCase):
    def setUp(self) -> None:
        window_system._MENU_ACTION_TARGET_CLASS = None

    def tearDown(self) -> None:
        window_system._MENU_ACTION_TARGET_CLASS = None

    def test_alloc_uses_existing_objc_target_class_when_registered(self) -> None:
        class _FakeObjC:
            @staticmethod
            def lookUpClass(name: str):
                if name != "_LuvatrixDebugMenuTarget":
                    raise LookupError(name)
                return _ExistingTarget

        with patch.dict("sys.modules", {"Foundation": type("F", (), {"NSObject": _FakeNSObject}), "objc": _FakeObjC}):
            target = window_system._MenuActionTarget.alloc()
        self.assertIsInstance(target, _ExistingTarget)
        self.assertIs(window_system._MENU_ACTION_TARGET_CLASS, _ExistingTarget)

    def test_resolver_caches_dynamic_target_class(self) -> None:
        class _FakeObjC:
            calls = 0

            @classmethod
            def lookUpClass(cls, _name: str):
                cls.calls += 1
                raise LookupError("missing")

        with patch.dict("sys.modules", {"Foundation": type("F", (), {"NSObject": _FakeNSObject}), "objc": _FakeObjC}):
            first = window_system._resolve_menu_action_target_class()
            second = window_system._resolve_menu_action_target_class()
        self.assertIsNotNone(first)
        self.assertIs(first, second)
        self.assertEqual(_FakeObjC.calls, 1)

    def test_alloc_falls_back_without_foundation(self) -> None:
        with patch.dict("sys.modules", {"Foundation": None}):
            target = window_system._MenuActionTarget.alloc()
        self.assertIsInstance(target, window_system._MenuActionTarget)


if __name__ == "__main__":
    unittest.main()
