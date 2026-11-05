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


class _ChainedFake:
    """AppKit stand-in: records `<tag>.<selector>` calls and returns itself for chaining."""

    def __init__(self, calls: list[str], tag: str) -> None:
        self._calls = calls
        self._tag = tag

    def __getattr__(self, attr: str):
        if attr.startswith("_"):
            raise AttributeError(attr)

        def _method(*args, **kwargs):
            self._calls.append(f"{self._tag}.{attr}")
            return self

        return _method

    def __call__(self, *args, **kwargs):
        return self


class MacOSWindowPlacementTests(unittest.TestCase):
    def _fake_ns(self, calls: list[str]) -> dict[str, object]:
        return {
            "NSApp": _ChainedFake(calls, "nsapp"),
            "NSApplication": _ChainedFake(calls, "nsapplication"),
            "NSApplicationActivationPolicyRegular": 0,
            "NSWindowStyleMaskTitled": 1,
            "NSWindowStyleMaskClosable": 2,
            "NSWindowStyleMaskMiniaturizable": 4,
            "NSWindowStyleMaskResizable": 8,
            "NSBackingStoreBuffered": 2,
            "NSMakeRect": _ChainedFake(calls, "rect"),
            "NSWindow": _ChainedFake(calls, "window"),
            "CAMetalLayer": _ChainedFake(calls, "layer"),
            "CALayer": _ChainedFake(calls, "layer"),
        }

    def test_create_window_centers_before_ordering_front(self) -> None:
        calls: list[str] = []
        ws = window_system.AppKitWindowSystem()
        with (
            patch.object(ws, "_imports", return_value=self._fake_ns(calls)),
            patch.object(ws, "_install_main_menu", lambda **kwargs: None),
        ):
            ws.create_window(1440, 900, "Nomic")

        window_calls = [c for c in calls if c.startswith("window.")]
        self.assertIn("window.center", window_calls)
        self.assertLess(
            window_calls.index("window.center"),
            window_calls.index("window.makeKeyAndOrderFront_"),
            "window must be centered before it is shown",
        )


if __name__ == "__main__":
    unittest.main()
