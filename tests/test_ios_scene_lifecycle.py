from __future__ import annotations

import os
import plistlib
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from luvatrix_core.platform.ios import runner


ROOT = Path(__file__).resolve().parents[1]
NATIVE_IOS_DIRS = (
    ROOT / "ios",
    ROOT / "luvatrix_core" / "templates" / "native" / "ios",
    ROOT / "examples" / "hello_ios" / "ios",
)


def _project_yml_scene_delegate(project_yml: Path) -> str | None:
    match = re.search(r"UISceneDelegateClassName:\s*(\S+)", project_yml.read_text(encoding="utf-8"))
    return match.group(1) if match else None


class IOSSceneManifestTests(unittest.TestCase):
    """iOS 27 SDK apps refuse to launch without adopting the UIScene life cycle."""

    def test_info_plist_declares_single_window_scene_with_luvatrix_delegate(self) -> None:
        for native in NATIVE_IOS_DIRS:
            with self.subTest(native=str(native.relative_to(ROOT))):
                with (native / "Luvatrix" / "Info.plist").open("rb") as fh:
                    plist = plistlib.load(fh)
                manifest = plist["UIApplicationSceneManifest"]
                self.assertIs(manifest["UIApplicationSupportsMultipleScenes"], False)
                configs = manifest["UISceneConfigurations"]["UIWindowSceneSessionRoleApplication"]
                self.assertEqual(len(configs), 1)
                self.assertEqual(configs[0]["UISceneDelegateClassName"], "LuvatrixSceneDelegate")

    def test_xcodegen_spec_keeps_scene_manifest_when_regenerating_info_plist(self) -> None:
        for native in NATIVE_IOS_DIRS:
            with self.subTest(native=str(native.relative_to(ROOT))):
                self.assertEqual(_project_yml_scene_delegate(native / "project.yml"), "LuvatrixSceneDelegate")

    def test_swift_exports_the_scene_delegate_named_in_the_manifest(self) -> None:
        for native in NATIVE_IOS_DIRS:
            with self.subTest(native=str(native.relative_to(ROOT))):
                swift = (native / "Luvatrix" / "AppDelegate.swift").read_text(encoding="utf-8")
                self.assertRegex(
                    swift,
                    r"@objc\(LuvatrixSceneDelegate\)\s+(final\s+)?class\s+\w+\s*:\s*UIResponder,\s*UIWindowSceneDelegate",
                )


class _Obj:
    def __init__(self, **attrs: object) -> None:
        self.__dict__.update(attrs)


class _FakeWindow:
    def __init__(self) -> None:
        self.scene: object = None
        self.frame: object = None
        self.rootViewController: object = None
        self.key_and_visible = False

    def initWithWindowScene_(self, scene: object) -> "_FakeWindow":
        self.scene = scene
        return self

    def initWithFrame_(self, frame: object) -> "_FakeWindow":
        self.frame = frame
        return self

    def makeKeyAndVisible(self) -> None:
        self.key_and_visible = True


def _fake_rubicon(connected_scene: object) -> tuple[types.ModuleType, _FakeWindow]:
    window = _FakeWindow()
    window_scene_class = object()
    layer_parent = _Obj(addSublayer_=lambda layer: None)
    classes = {
        "UIScreen": _Obj(mainScreen=_Obj(bounds="screen-bounds", scale=3.0)),
        "UIWindow": _Obj(alloc=lambda: window),
        "UIViewController": _Obj(alloc=lambda: _Obj(init=lambda: _Obj(view=_Obj(layer=layer_parent)))),
        "CAMetalLayer": _Obj(alloc=lambda: _Obj(init=lambda: _Obj())),
        "UIWindowScene": window_scene_class,
        "UIApplication": _Obj(
            sharedApplication=_Obj(connectedScenes=_Obj(anyObject=lambda: connected_scene))
        ),
    }
    if connected_scene is not None:
        connected_scene.isKindOfClass_ = lambda cls: cls is window_scene_class  # type: ignore[attr-defined]
    objc = types.ModuleType("rubicon.objc")
    objc.ObjCClass = lambda name: classes[name]  # type: ignore[attr-defined]
    rubicon = types.ModuleType("rubicon")
    rubicon.objc = objc  # type: ignore[attr-defined]
    return rubicon, window


class IOSSetupUISceneTests(unittest.TestCase):
    def setUp(self) -> None:
        names = ("_metal_layer", "_window", "_vc", "_touch_view", "_touch_view_class")
        saved = {name: getattr(runner, name) for name in names}
        self.addCleanup(lambda: [setattr(runner, k, v) for k, v in saved.items()])

    def _setup_ui(self, connected_scene: object) -> _FakeWindow:
        rubicon, window = _fake_rubicon(connected_scene)
        env = {k: v for k, v in os.environ.items() if k != "LUVATRIX_IOS_ENABLE_HDI"}
        with (
            patch.dict(sys.modules, {"rubicon": rubicon, "rubicon.objc": rubicon.objc}),
            patch.dict(os.environ, env, clear=True),
            patch.object(runner, "_setup_syslog_redirect"),
            patch.object(runner, "_ios_import_probe_requested", return_value=False),
        ):
            runner.setup_ui(393, 852)
        return window

    def test_setup_ui_attaches_window_to_connected_window_scene(self) -> None:
        scene = _Obj()
        window = self._setup_ui(scene)

        self.assertIs(window.scene, scene)
        self.assertTrue(window.key_and_visible)
        self.assertIs(runner._window, window)

    def test_setup_ui_falls_back_to_screen_frame_without_a_scene(self) -> None:
        window = self._setup_ui(None)

        self.assertIsNone(window.scene)
        self.assertEqual(window.frame, "screen-bounds")
        self.assertTrue(window.key_and_visible)


if __name__ == "__main__":
    unittest.main()
