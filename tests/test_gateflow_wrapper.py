from __future__ import annotations

import subprocess
from unittest.mock import patch

from gateflow_cli.wrapper import main


def test_wrapper_uses_default_standalone_command() -> None:
    with patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0)) as run:
        rc = main(["--help"])
    assert rc == 0
    run.assert_called_once_with(["uvx", "--from", "./gateflow", "gateflow", "--help"], check=False)


def test_wrapper_honors_env_override(monkeypatch) -> None:
    monkeypatch.setenv("LUVATRIX_GATEFLOW_WRAPPER_CMD", "gateflow")
    with patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=3)) as run:
        rc = main(["validate", "all"])
    assert rc == 3
    run.assert_called_once_with(["gateflow", "validate", "all"], check=False)


def test_wrapper_returns_127_when_binary_missing(capsys) -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError("missing")):
        rc = main(["validate", "all"])
    err = capsys.readouterr().err
    assert rc == 127
    assert "LUVATRIX_GATEFLOW_WRAPPER_CMD" in err
