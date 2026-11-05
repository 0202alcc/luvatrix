"""Terminate-uninstall-install ordering for the iOS simulator run flow.

The simulator retains a launched app's environment per bundle id. When an app
is reinstalled over a previous install, the retained environment survives and
the next spawn (whether an auto-relaunch after the install or a ``simctl
launch`` that attaches to an already-running instance) can deliver the
PREVIOUS launch's environment instead of the caller's — a tour then runs with
a stale run id and the harness waits forever. ``simctl uninstall`` removes the
retained environment along with the app, so reinstall + launch starts clean.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from luvatrix_core.platform.ios.runner import _install_fresh


def test_install_fresh_terminates_uninstalls_then_installs(tmp_path) -> None:
    commands: list[list[str]] = []

    def run(cmd, **_kwargs):
        commands.append([str(c) for c in cmd])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    app = tmp_path / "Luvatrix.app"
    _install_fresh("UDID", app, "com.luvatrix.app", run=run)

    assert commands == [
        ["xcrun", "simctl", "terminate", "UDID", "com.luvatrix.app"],
        ["xcrun", "simctl", "uninstall", "UDID", "com.luvatrix.app"],
        ["xcrun", "simctl", "install", "UDID", str(app)],
    ]


def test_install_fresh_tolerates_terminate_and_uninstall_failure(tmp_path) -> None:
    def run(cmd, **_kwargs):
        if "terminate" in cmd:
            return SimpleNamespace(returncode=3, stdout="", stderr="not running")
        if "uninstall" in cmd:
            return SimpleNamespace(returncode=3, stdout="", stderr="not installed")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    _install_fresh("UDID", tmp_path / "Luvatrix.app", "com.luvatrix.app", run=run)


def test_install_fresh_raises_when_install_fails(tmp_path) -> None:
    def run(cmd, **kwargs):
        if "install" in cmd:
            assert kwargs.get("check") is True
            raise subprocess.CalledProcessError(1, cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises(subprocess.CalledProcessError):
        _install_fresh("UDID", tmp_path / "Luvatrix.app", "com.luvatrix.app", run=run)
