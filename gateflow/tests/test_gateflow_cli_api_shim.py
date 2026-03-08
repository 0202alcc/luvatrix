from __future__ import annotations

import json
from pathlib import Path

from gateflow.cli import main


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _seed(root: Path) -> None:
    assert main(["--root", str(root), "init", "scaffold", "--profile", "minimal"]) == 0


def test_api_method_path_crud_roundtrip(tmp_path: Path, capsys) -> None:
    _seed(tmp_path)
    _ = capsys.readouterr()

    assert main(["--root", str(tmp_path), "api", "POST", "/tasks", "--body", '{"id":"T-9000"}']) == 0
    assert main(["--root", str(tmp_path), "api", "PATCH", "/tasks/T-9000", "--body", '{"status":"Done"}']) == 2
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "api",
                "PATCH",
                "/tasks/T-9000",
                "--body",
                '{"status":"Success Criteria Spec"}',
            ]
        )
        == 0
    )
    assert main(["--root", str(tmp_path), "api", "GET", "/tasks/T-9000"]) == 0

    _ = capsys.readouterr()
    task = _load(tmp_path / ".gateflow" / "tasks.json")["items"][0]
    assert task == {"id": "T-9000", "status": "Success Criteria Spec"}


def test_api_lowercase_verb_supported(tmp_path: Path, capsys) -> None:
    _seed(tmp_path)
    _ = capsys.readouterr()
    assert main(["--root", str(tmp_path), "api", "get", "/milestones"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["compatibility_mode"] == "planning_api_shim_v1"
    assert payload["method"] == "GET"


def test_api_rejects_invalid_path(tmp_path: Path) -> None:
    _seed(tmp_path)
    assert main(["--root", str(tmp_path), "api", "GET", "tasks"]) == 2
