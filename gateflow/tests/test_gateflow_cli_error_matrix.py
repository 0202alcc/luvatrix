from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from gateflow.cli import main


def _seed(root: Path) -> None:
    assert main(["--root", str(root), "init", "scaffold", "--profile", "minimal"]) == 0


def test_json_error_payload_for_validation_failure(tmp_path: Path, capsys) -> None:
    rc = main(["--root", str(tmp_path), "--json-errors", "config", "set", "profile", '"minimal"'])
    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_type"] == "validation"
    assert payload["exit_code"] == 2


def test_json_error_payload_for_policy_failure(tmp_path: Path, capsys) -> None:
    _seed(tmp_path)
    _ = capsys.readouterr()
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True, text=True)
    rc = main(["--root", str(tmp_path), "--json-errors", "tasks", "create", "--body", '{"id":"T-5001"}'])
    assert rc == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_type"] == "policy"
    assert payload["exit_code"] == 3
    assert "POLICY_PROTECTED_BRANCH" in payload["message"]


def test_json_error_payload_for_internal_failure(tmp_path: Path, capsys) -> None:
    with patch("gateflow.cli._dispatch", side_effect=RuntimeError("boom")):
        rc = main(["--root", str(tmp_path), "--json-errors", "init", "doctor"])
    assert rc == 4
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_type"] == "internal"
    assert payload["exit_code"] == 4
    assert payload["message"] == "boom"
