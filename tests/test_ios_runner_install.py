"""Terminate-then-install ordering for the iOS simulator run flow.

A kept-open app instance killed by ``simctl install`` can be auto-relaunched
by the simulator with the PREVIOUS launch's retained environment; the
env-carrying ``simctl launch`` that follows then no-ops and the run's
configuration (tour steps, render scale) never reaches the app. Terminating
before install closes that race.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from luvatrix_core.platform.ios.runner import _install_fresh


def test_install_fresh_terminates_before_installing(tmp_path) -> None:
    commands: list[list[str]] = []

    def run(cmd, **_kwargs):
        commands.append([str(c) for c in cmd])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    app = tmp_path / "Luvatrix.app"
    _install_fresh("UDID", app, "com.luvatrix.app", run=run)

    assert commands == [
        ["xcrun", "simctl", "terminate", "UDID", "com.luvatrix.app"],
        ["xcrun", "simctl", "install", "UDID", str(app)],
    ]


def test_install_fresh_tolerates_terminate_failure(tmp_path) -> None:
    def run(cmd, **_kwargs):
        if "terminate" in cmd:
            return SimpleNamespace(returncode=3, stdout="", stderr="not running")
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
