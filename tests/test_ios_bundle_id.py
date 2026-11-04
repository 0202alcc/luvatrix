"""Bundle-id resolution for iOS apps and the surfaces that consume it."""

from __future__ import annotations

import json
import plistlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from luvatrix_core.platform.ios.bundle_id import LEGACY_BUNDLE_ID, ios_bundle_id
from luvatrix_core.platform.ios.runner import (
    _run_ios_simulator,
    _sync_project_bundle_id,
    _write_ios_app_entitlements,
)
from luvatrix_core.scaffold import init_native_project

UDID = "UDID-17"


_APP_COUNTER = iter(range(1000))


def _app_with_id(tmp_path: Path, app_id: str | None) -> Path:
    app = tmp_path / f"app-{next(_APP_COUNTER)}"
    app.mkdir(exist_ok=True)
    if app_id is not None:
        (app / "app.toml").write_text(f'app_id = "{app_id}"\n', encoding="utf-8")
    return app


def test_ios_bundle_id_derives_last_segment_from_app_id(tmp_path: Path) -> None:
    assert ios_bundle_id(_app_with_id(tmp_path, "figma.nomic_app")) == "com.luvatrix.app.nomic-app"
    assert ios_bundle_id(_app_with_id(tmp_path, "examples.figma_app")) == "com.luvatrix.app.figma-app"
    assert ios_bundle_id(_app_with_id(tmp_path, "figma.captured_site")) == "com.luvatrix.app.captured-site"


def test_ios_bundle_id_handles_single_segment_and_sanitizes(tmp_path: Path) -> None:
    assert ios_bundle_id(_app_with_id(tmp_path, "nomic_app")) == "com.luvatrix.app.nomic-app"
    assert ios_bundle_id(_app_with_id(tmp_path, "My Cool App!")) == "com.luvatrix.app.my-cool-app"
    assert ios_bundle_id(_app_with_id(tmp_path, "a__b")) == "com.luvatrix.app.a-b"


def test_ios_bundle_id_falls_back_to_legacy_without_a_usable_app_id(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    missing.mkdir()
    assert ios_bundle_id(missing) == LEGACY_BUNDLE_ID
    assert ios_bundle_id(_app_with_id(tmp_path, "")) == LEGACY_BUNDLE_ID
    assert ios_bundle_id(_app_with_id(tmp_path, "...")) == LEGACY_BUNDLE_ID
    assert ios_bundle_id(tmp_path / "no-such-dir") == LEGACY_BUNDLE_ID


def test_ios_simulator_launch_and_interrupt_terminate_use_the_derived_bundle_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import luvatrix_core.platform.ios.runner as runner

    app = _app_with_id(tmp_path, "figma.nomic_app")
    (app / "app_main.py").write_text("def create(): pass\n", encoding="utf-8")
    ios_dir = app / ".luvatrix" / "ios"
    (ios_dir / "Luvatrix").mkdir(parents=True)
    (ios_dir / "PyPackages").mkdir()

    monkeypatch.setenv("LUVATRIX_ALLOW_PURE_PYTHON_IOS", "1")
    commands: list[tuple[list[str], dict]] = []

    def fake_run(cmd, **kwargs):
        cmd = [str(c) for c in cmd]
        commands.append((cmd, kwargs))
        if cmd[:2] == ["xcodegen", "generate"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[0] == "xcodebuild":
            derived = Path(str(cmd[cmd.index("-derivedDataPath") + 1]))
            (derived / "Build" / "Products" / "Debug-iphonesimulator" / "Luvatrix.app").mkdir(parents=True)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:4] == ["xcrun", "simctl", "list", "devices"]:
            devices = {"devices": {"iOS": [{"name": "iPhone 17", "udid": UDID, "state": "Booted", "isAvailable": True}]}}
            return SimpleNamespace(returncode=0, stdout=json.dumps(devices), stderr="")
        if cmd[:3] == ["xcrun", "simctl", "launch"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "_sync_luvatrix_packages", lambda packages_dir: None)

    runner._run_ios_simulator(app, "iPhone 17", render_scale=3.0)

    launches = [(cmd, kwargs) for cmd, kwargs in commands if cmd[:3] == ["xcrun", "simctl", "launch"]]
    assert len(launches) == 1
    launch_cmd, launch_kwargs = launches[0]
    assert launch_cmd == ["xcrun", "simctl", "launch", "--console", UDID, "com.luvatrix.app.nomic-app"]
    assert launch_kwargs["env"]["SIMCTL_CHILD_LUVATRIX_IOS_RENDER_SCALE"] == "3"


def test_run_ios_simulator_terminates_the_derived_bundle_id_on_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import luvatrix_core.platform.ios.runner as runner

    app = _app_with_id(tmp_path, "figma.nomic_app")
    (app / "app_main.py").write_text("def create(): pass\n", encoding="utf-8")
    ios_dir = app / ".luvatrix" / "ios"
    (ios_dir / "Luvatrix").mkdir(parents=True)
    (ios_dir / "PyPackages").mkdir()

    monkeypatch.setenv("LUVATRIX_ALLOW_PURE_PYTHON_IOS", "1")
    commands: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        cmd = [str(c) for c in cmd]
        commands.append(cmd)
        if cmd[:2] == ["xcodegen", "generate"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[0] == "xcodebuild":
            derived = Path(str(cmd[cmd.index("-derivedDataPath") + 1]))
            (derived / "Build" / "Products" / "Debug-iphonesimulator" / "Luvatrix.app").mkdir(parents=True)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:4] == ["xcrun", "simctl", "list", "devices"]:
            devices = {"devices": {"iOS": [{"name": "iPhone 17", "udid": UDID, "state": "Booted", "isAvailable": True}]}}
            return SimpleNamespace(returncode=0, stdout=json.dumps(devices), stderr="")
        if cmd[:3] == ["xcrun", "simctl", "launch"]:
            raise KeyboardInterrupt
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "_sync_luvatrix_packages", lambda packages_dir: None)

    runner._run_ios_simulator(app, "iPhone 17")

    terminates = [cmd for cmd in commands if cmd[:3] == ["xcrun", "simctl", "terminate"]]
    assert terminates == [["xcrun", "simctl", "terminate", UDID, "com.luvatrix.app.nomic-app"]]


def test_run_ios_simulator_launches_legacy_bundle_id_without_app_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import luvatrix_core.platform.ios.runner as runner

    app = tmp_path / "app"
    app.mkdir()
    (app / "app_main.py").write_text("def create(): pass\n", encoding="utf-8")
    ios_dir = app / ".luvatrix" / "ios"
    (ios_dir / "Luvatrix").mkdir(parents=True)
    (ios_dir / "PyPackages").mkdir()

    monkeypatch.setenv("LUVATRIX_ALLOW_PURE_PYTHON_IOS", "1")
    commands: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        cmd = [str(c) for c in cmd]
        commands.append(cmd)
        if cmd[:2] == ["xcodegen", "generate"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[0] == "xcodebuild":
            derived = Path(str(cmd[cmd.index("-derivedDataPath") + 1]))
            (derived / "Build" / "Products" / "Debug-iphonesimulator" / "Luvatrix.app").mkdir(parents=True)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:4] == ["xcrun", "simctl", "list", "devices"]:
            devices = {"devices": {"iOS": [{"name": "iPhone 17", "udid": UDID, "state": "Booted", "isAvailable": True}]}}
            return SimpleNamespace(returncode=0, stdout=json.dumps(devices), stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "_sync_luvatrix_packages", lambda packages_dir: None)

    runner._run_ios_simulator(app, "iPhone 17")

    launches = [cmd for cmd in commands if cmd[:3] == ["xcrun", "simctl", "launch"]]
    assert launches == [["xcrun", "simctl", "launch", "--console", UDID, LEGACY_BUNDLE_ID]]


_PROJECT_YML = """\
name: Luvatrix
targets:
  Luvatrix:
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: com.luvatrix.app
scripts:
  postbuild:
    - script: |
        PRODUCT_BUNDLE_IDENTIFIER="${PRODUCT_BUNDLE_IDENTIFIER:-com.luvatrix.app}"
        echo done
"""


def test_sync_project_bundle_id_rewrites_stale_ids(tmp_path: Path) -> None:
    ios_dir = tmp_path / "ios"
    ios_dir.mkdir()
    (ios_dir / "project.yml").write_text(_PROJECT_YML, encoding="utf-8")

    _sync_project_bundle_id(ios_dir, "com.luvatrix.app.nomic-app")

    text = (ios_dir / "project.yml").read_text(encoding="utf-8")
    assert "PRODUCT_BUNDLE_IDENTIFIER: com.luvatrix.app.nomic-app" in text
    assert 'PRODUCT_BUNDLE_IDENTIFIER="${PRODUCT_BUNDLE_IDENTIFIER:-com.luvatrix.app.nomic-app}"' in text
    assert "com.luvatrix.app\n" not in text.replace("com.luvatrix.app.nomic-app", "")


def test_sync_project_bundle_id_is_a_noop_when_already_current(tmp_path: Path) -> None:
    ios_dir = tmp_path / "ios"
    ios_dir.mkdir()
    path = ios_dir / "project.yml"
    path.write_text(_PROJECT_YML, encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    _sync_project_bundle_id(ios_dir, LEGACY_BUNDLE_ID)

    assert path.read_text(encoding="utf-8") == before


def test_sync_project_bundle_id_leaves_an_already_derived_id_alone(tmp_path: Path) -> None:
    ios_dir = tmp_path / "ios"
    ios_dir.mkdir()
    path = ios_dir / "project.yml"
    path.write_text(
        "PRODUCT_BUNDLE_IDENTIFIER: com.luvatrix.app.nomic-app\n"
        'PRODUCT_BUNDLE_IDENTIFIER="${PRODUCT_BUNDLE_IDENTIFIER:-com.luvatrix.app}"\n',
        encoding="utf-8",
    )

    _sync_project_bundle_id(ios_dir, "com.luvatrix.app.nomic-app")

    text = path.read_text(encoding="utf-8")
    assert "com.luvatrix.app.nomic-app.nomic-app" not in text
    assert text.count("com.luvatrix.app.nomic-app") == 2


def test_init_native_ios_project_emits_the_derived_bundle_id(tmp_path: Path) -> None:
    app = _app_with_id(tmp_path, "figma.nomic_app")

    init_native_project(app, target="ios", out=tmp_path / "native")

    text = (tmp_path / "native" / "project.yml").read_text(encoding="utf-8")
    assert "PRODUCT_BUNDLE_IDENTIFIER: com.luvatrix.app.nomic-app" in text
    assert 'PRODUCT_BUNDLE_IDENTIFIER="${PRODUCT_BUNDLE_IDENTIFIER:-com.luvatrix.app.nomic-app}"' in text
    assert "PRODUCT_BUNDLE_IDENTIFIER: com.luvatrix.app\n" not in text


def test_init_native_ios_project_keeps_the_legacy_bundle_id_without_app_id(tmp_path: Path) -> None:
    app = tmp_path / "app"
    app.mkdir()

    init_native_project(app, target="ios", out=tmp_path / "native")

    text = (tmp_path / "native" / "project.yml").read_text(encoding="utf-8")
    assert "PRODUCT_BUNDLE_IDENTIFIER: com.luvatrix.app\n" in text


def test_ios_app_entitlements_use_the_given_bundle_id(tmp_path: Path) -> None:
    app_path = tmp_path / "Luvatrix.app"
    app_path.mkdir()

    entitlements_path = _write_ios_app_entitlements(app_path, "TEAM1234", bundle_id="com.luvatrix.app.nomic-app")

    with entitlements_path.open("rb") as fh:
        entitlements = plistlib.load(fh)
    assert entitlements["application-identifier"] == "TEAM1234.com.luvatrix.app.nomic-app"
    assert entitlements["keychain-access-groups"] == ["TEAM1234.com.luvatrix.app.nomic-app"]


def test_ios_app_entitlements_default_to_the_legacy_bundle_id(tmp_path: Path) -> None:
    app_path = tmp_path / "Luvatrix.app"
    app_path.mkdir()

    entitlements_path = _write_ios_app_entitlements(app_path, "TEAM1234")

    with entitlements_path.open("rb") as fh:
        entitlements = plistlib.load(fh)
    assert entitlements["application-identifier"] == f"TEAM1234.{LEGACY_BUNDLE_ID}"