"""The iOS userInterfaceStyle bridge: trait reports reach Python and the app.

setup_ui reads the window's initial trait collection, the native scaffold
forwards later traitCollectionDidChange callbacks, and the run-app CLI carries
an explicit LUVATRIX_APPEARANCE override into the bundled launch config.
"""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from luvatrix_core.platform.ios import runner
from luvatrix_core.platform.ios.appearance import set_user_interface_style, user_interface_style

ROOT = Path(__file__).resolve().parents[1]
NATIVE_IOS_DIRS = (
    ROOT / "ios",
    ROOT / "luvatrix_core" / "templates" / "native" / "ios",
    ROOT / "examples" / "nomic_ios" / "ios",
)


@pytest.fixture(autouse=True)
def _clean_appearance_state(monkeypatch):
    monkeypatch.delenv("LUVATRIX_IOS_USER_INTERFACE_STYLE", raising=False)
    monkeypatch.delenv("LUVATRIX_APPEARANCE", raising=False)
    yield
    set_user_interface_style("light")


class _Obj:
    def __init__(self, **attrs: object) -> None:
        self.__dict__.update(attrs)


# ── appearance module ────────────────────────────────────────────────────────


def test_reports_the_dark_trait_to_the_env() -> None:
    assert set_user_interface_style("dark") is True
    assert user_interface_style() == "dark"
    assert os.environ["LUVATRIX_IOS_USER_INTERFACE_STYLE"] == "dark"


def test_accepts_uikit_raw_trait_values() -> None:
    assert set_user_interface_style(2) is True
    assert user_interface_style() == "dark"
    assert set_user_interface_style(1) is True
    assert user_interface_style() == "light"


def test_normalizes_case_and_whitespace() -> None:
    assert set_user_interface_style(" Dark ") is True
    assert user_interface_style() == "dark"
    assert os.environ["LUVATRIX_IOS_USER_INTERFACE_STYLE"] == "dark"


def test_unknown_or_unspecified_styles_are_ignored() -> None:
    set_user_interface_style("dark")
    for bad in ("sepia", "", 0, 3, None):
        assert set_user_interface_style(bad) is False
        assert user_interface_style() == "dark"
        assert os.environ["LUVATRIX_IOS_USER_INTERFACE_STYLE"] == "dark"


# ── launch config passthrough ────────────────────────────────────────────────


def _launch_config(packages_dir: Path) -> dict:
    runner._write_ios_launch_config(
        packages_dir,
        render_scale=1.0,
        render_mode="auto",
        target_fps=None,
        present_fps=None,
        import_probe=False,
    )
    return json.loads((packages_dir / "luvatrix_ios_launch_config.json").read_text(encoding="utf-8"))


def test_launch_config_carries_the_appearance_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LUVATRIX_APPEARANCE", "dark")

    config = _launch_config(tmp_path)

    assert config["LUVATRIX_APPEARANCE"] == "dark"


def test_launch_config_omits_the_appearance_override_when_unset(tmp_path) -> None:
    config = _launch_config(tmp_path)

    assert "LUVATRIX_APPEARANCE" not in config


# ── setup_ui trait report ────────────────────────────────────────────────────


class _FakeWindow:
    def __init__(self, style: int) -> None:
        self.frame: object = None
        self.traitCollection = _Obj(userInterfaceStyle=style)

    def initWithFrame_(self, frame: object) -> "_FakeWindow":
        self.frame = frame
        return self

    def makeKeyAndVisible(self) -> None:
        pass


def _fake_rubicon(window: _FakeWindow) -> types.ModuleType:
    layer_parent = _Obj(addSublayer_=lambda layer: None)
    classes = {
        "UIScreen": _Obj(mainScreen=_Obj(bounds="screen-bounds", scale=3.0)),
        "UIWindow": _Obj(alloc=lambda: window),
        "UIViewController": _Obj(alloc=lambda: _Obj(init=lambda: _Obj(view=_Obj(layer=layer_parent)))),
        "CAMetalLayer": _Obj(alloc=lambda: _Obj(init=lambda: _Obj())),
        "UIWindowScene": object(),
        "UIApplication": _Obj(sharedApplication=_Obj(connectedScenes=_Obj(anyObject=lambda: None))),
    }
    objc = types.ModuleType("rubicon.objc")
    objc.ObjCClass = lambda name: classes[name]  # type: ignore[attr-defined]
    rubicon = types.ModuleType("rubicon")
    rubicon.objc = objc  # type: ignore[attr-defined]
    return rubicon


def test_setup_ui_reports_the_windows_initial_trait() -> None:
    names = ("_metal_layer", "_window", "_vc", "_touch_view", "_touch_view_class")
    saved = {name: getattr(runner, name) for name in names}
    rubicon = _fake_rubicon(_FakeWindow(style=2))
    try:
        with (
            patch.dict(sys.modules, {"rubicon": rubicon, "rubicon.objc": rubicon.objc}),
            patch.object(runner, "_setup_syslog_redirect"),
            patch.object(runner, "_ios_import_probe_requested", return_value=False),
        ):
            runner.setup_ui(402, 874)
        assert os.environ["LUVATRIX_IOS_USER_INTERFACE_STYLE"] == "dark"
        assert user_interface_style() == "dark"
    finally:
        for name, value in saved.items():
            setattr(runner, name, value)


# ── rubicon touch view forwards trait changes ────────────────────────────────


class _FakeUIView:
    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__()


def _touch_view_class() -> type:
    objc = types.ModuleType("rubicon.objc")
    objc.objc_method = lambda fn: fn  # type: ignore[attr-defined]
    api = types.ModuleType("rubicon.objc.api")
    api.ObjCInstance = object  # type: ignore[attr-defined]
    rubicon = types.ModuleType("rubicon")
    rubicon.objc = objc  # type: ignore[attr-defined]
    runner._make_touch_view_class.__dict__.pop("_cached", None)
    try:
        with patch.dict(
            sys.modules,
            {"rubicon": rubicon, "rubicon.objc": objc, "rubicon.objc.api": api},
        ):
            return runner._make_touch_view_class(_FakeUIView)
    finally:
        runner._make_touch_view_class.__dict__.pop("_cached", None)


def test_touch_view_forwards_trait_changes_to_python() -> None:
    view_class = _touch_view_class()
    view = view_class.__new__(view_class)
    view.traitCollection = _Obj(userInterfaceStyle=2)

    view.traitCollectionDidChange_(None)

    assert user_interface_style() == "dark"
    assert os.environ["LUVATRIX_IOS_USER_INTERFACE_STYLE"] == "dark"


# ── native scaffold forwards trait changes ───────────────────────────────────


def test_swift_scaffold_forwards_trait_changes_to_python() -> None:
    for native in NATIVE_IOS_DIRS:
        swift = (native / "Luvatrix" / "AppDelegate.swift").read_text(encoding="utf-8")
        assert "traitCollectionDidChange" in swift, native
        assert "callPythonSetUserInterfaceStyle" in swift, native
        assert "set_user_interface_style" in swift, native
