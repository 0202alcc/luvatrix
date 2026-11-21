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


class _FakeNSMenuItem:
    def __init__(self) -> None:
        self.title = None
        self.action = None
        self.key_equivalent = None
        self.enabled = True
        self.target = None
        self.tag = 0
        self.submenu = None

    @classmethod
    def alloc(cls):
        return cls()

    def initWithTitle_action_keyEquivalent_(self, title, action, key_equivalent):
        self.title = title
        self.action = action
        self.key_equivalent = key_equivalent
        return self

    def setEnabled_(self, enabled):
        self.enabled = enabled

    def setTarget_(self, target):
        self.target = target

    def setTag_(self, tag):
        self.tag = tag


class _FakeNSMenu:
    def __init__(self) -> None:
        self.title = None
        self.items: list[_FakeNSMenuItem] = []

    @classmethod
    def alloc(cls):
        return cls()

    def initWithTitle_(self, title):
        self.title = title
        return self

    def addItem_(self, item):
        self.items.append(item)

    def setSubmenu_forItem_(self, menu, item):
        item.submenu = menu


class _FakeApp:
    def __init__(self) -> None:
        self.main_menu = None

    def setMainMenu_(self, menu):
        self.main_menu = menu


def _install_menu_with_fake_appkit(menu_config=None) -> tuple[_FakeApp, _FakeNSMenu]:
    app = _FakeApp()
    fake_appkit = type("AppKit", (), {"NSMenu": _FakeNSMenu, "NSMenuItem": _FakeNSMenuItem})
    with patch.dict("sys.modules", {"AppKit": fake_appkit}):
        window_system.AppKitWindowSystem()._install_main_menu(app=app, menu_config=menu_config)
    return app, app.main_menu


class MacOSMainMenuEditSectionTests(unittest.TestCase):
    """The Edit menu must carry real standard items: key equivalents only reach
    the first responder (e.g. an NSTextField) when menu traversal finds a menu
    item with that equivalent. A disabled placeholder swallows ⌘V/⌘X/⌘C/⌘A."""

    def _edit_menu(self) -> _FakeNSMenu:
        _, main_menu = _install_menu_with_fake_appkit()
        edit_item = next(item for item in main_menu.items if item.title == "Edit")
        return edit_item.submenu

    def test_edit_menu_spec_is_standard_editing_items(self) -> None:
        self.assertEqual(
            window_system._STANDARD_EDIT_MENU_ITEMS,
            (
                ("Cut", "cut:", "x"),
                ("Copy", "copy:", "c"),
                ("Paste", "paste:", "v"),
                ("Select All", "selectAll:", "a"),
            ),
        )

    def test_edit_menu_has_standard_items_with_key_equivalents(self) -> None:
        edit_menu = self._edit_menu()
        entries = [(item.title, item.action, item.key_equivalent) for item in edit_menu.items]
        self.assertEqual(
            entries,
            [
                ("Cut", "cut:", "x"),
                ("Copy", "copy:", "c"),
                ("Paste", "paste:", "v"),
                ("Select All", "selectAll:", "a"),
            ],
        )

    def test_edit_menu_items_use_responder_chain_dispatch(self) -> None:
        # Nil target routes cut:/copy:/paste:/selectAll: down the responder
        # chain, so the focused NSTextField receives them; items stay enabled
        # for AppKit's automatic menu validation.
        for item in self._edit_menu().items:
            self.assertIsNone(item.target)
            self.assertTrue(item.enabled)

    def test_other_sections_keep_disabled_placeholder(self) -> None:
        _, main_menu = _install_menu_with_fake_appkit()
        file_item = next(item for item in main_menu.items if item.title == "File")
        placeholders = file_item.submenu.items
        self.assertEqual(len(placeholders), 1)
        self.assertEqual(placeholders[0].title, "No Action")
        self.assertFalse(placeholders[0].enabled)


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


class _FakeRenderContentView:
    def __init__(self) -> None:
        self.subviews: list = []
        self.wants_layer = False

    def addSubview_(self, view):
        self.subviews.append(view)

    def bounds(self):
        size = type("S", (), {"width": 1280.0, "height": 800.0})()
        return type("B", (), {"size": size})()


class _FakeRenderHostView:
    def __init__(self) -> None:
        self.frame = None
        self.wants_layer = False
        self.layer = None
        self.autoresizing_mask = None

    @classmethod
    def alloc(cls):
        return cls()

    def initWithFrame_(self, frame):
        self.frame = frame
        return self

    def setWantsLayer_(self, wants):
        self.wants_layer = wants

    def setLayer_(self, layer):
        self.layer = layer

    def setAutoresizingMask_(self, mask):
        self.autoresizing_mask = mask


class TestRenderHostInstall(unittest.TestCase):
    """SL-36: every macOS window gets a render-host view covering the content
    view; the Metal/Quartz layer lives on the host so a glass plate can slot
    in UNDER it while native controls attach above. With no glass installed
    the host is the content view's only subview and the structure renders
    pixel-identically to the pre-split hierarchy."""

    def _ns(self):
        return {
            "NSView": _FakeRenderHostView,
            "NSMakeRect": lambda x, y, w, h: (x, y, w, h),
            "NSViewWidthSizable": 2,
            "NSViewHeightSizable": 16,
        }

    def test_host_covers_content_and_owns_layer(self):
        content = _FakeRenderContentView()
        layer = object()
        host = window_system._install_render_host(content, layer, self._ns())
        assert host in content.subviews
        assert host.frame == (0.0, 0.0, 1280.0, 800.0)
        assert host.autoresizing_mask == 2 | 16
        assert host.wants_layer is True
        assert host.layer is layer

    def test_handle_carries_render_view_fields(self):
        handle = window_system.MacOSWindowHandle(window=object(), layer=object())
        assert handle.render_view is None
        assert handle.under_glass_capable is False
        capable = window_system.MacOSWindowHandle(
            window=object(), layer=object(), render_view=object(),
            under_glass_capable=True)
        assert capable.render_view is not None
        assert capable.under_glass_capable is True


class _FakeAppearanceWindow:
    def __init__(self) -> None:
        self.appearance = None

    def setAppearance_(self, appearance):
        self.appearance = appearance


class _FakeWSAppearance:
    """Mirrors AppKit: appearanceNamed: returns nil for unknown names."""

    def __init__(self, name) -> None:
        self.name = name

    @classmethod
    def appearanceNamed_(cls, name):
        if name == "NSAppearanceNameDarkAqua":
            return cls(name)
        return None


class TestWindowDarkAppearance(unittest.TestCase):
    """SL-36 eyeball follow-up: the window itself pins dark Aqua so EVERY
    native descendant — glass plates, web views, buttons, fields, popovers —
    inherits the dark material instead of the default light appearance that
    rendered the pill glass white over the near-black scene."""

    def _ns(self):
        return {
            "NSAppearance": _FakeWSAppearance,
            "NSAppearanceNameDarkAqua": "NSAppearanceNameDarkAqua",
        }

    def test_window_pins_dark_appearance(self):
        window = _FakeAppearanceWindow()
        window_system._pin_window_appearance(window, self._ns())
        assert window.appearance is not None
        assert window.appearance.name == "NSAppearanceNameDarkAqua"

    def test_missing_appearance_class_is_tolerated(self):
        # A stripped-down AppKit must not break window creation — the pin is
        # best-effort and the scene renders identically without it.
        window = _FakeAppearanceWindow()
        window_system._pin_window_appearance(window, {})
        assert window.appearance is None


if __name__ == "__main__":
    unittest.main()
