from __future__ import annotations

import subprocess
from unittest.mock import patch

from gateflow_cli.wrapper import main


def test_wrapper_uses_default_standalone_command() -> None:
    with patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0)) as run:
        rc = main(["--help"])
    assert rc == 0
    called = run.call_args
    assert called is not None
    assert called.args[0] == ["uvx", "--from", "./gateflow", "gateflow", "--help"]
    assert called.kwargs["check"] is False
    assert called.kwargs["env"]["UV_CACHE_DIR"] == "./.uv-cache"
    assert called.kwargs["env"]["UV_TOOL_DIR"] == "./gateflow/.uv-tools"


def test_wrapper_honors_env_override(monkeypatch) -> None:
    monkeypatch.setenv("LUVATRIX_GATEFLOW_WRAPPER_CMD", "gateflow")
    with patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=3)) as run:
        rc = main(["validate", "all"])
    assert rc == 3
    called = run.call_args
    assert called is not None
    assert called.args[0] == ["gateflow", "validate", "all"]
    assert called.kwargs["check"] is False
    assert "UV_TOOL_DIR" not in called.kwargs["env"]


def test_wrapper_returns_127_when_binary_missing(capsys) -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError("missing")):
        rc = main(["validate", "all"])
    err = capsys.readouterr().err
    assert rc == 127
    assert "LUVATRIX_GATEFLOW_WRAPPER_CMD" in err
