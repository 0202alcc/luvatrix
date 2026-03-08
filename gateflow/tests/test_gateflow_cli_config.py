from __future__ import annotations

import json
from pathlib import Path

from gateflow.cli import main


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _seed(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path), "init", "scaffold", "--profile", "minimal"]) == 0


def test_config_show_and_get(tmp_path: Path, capsys) -> None:
    _seed(tmp_path)
    _ = capsys.readouterr()

    assert main(["--root", str(tmp_path), "config", "show"]) == 0
    show_payload = json.loads(capsys.readouterr().out)
    assert show_payload["policy"]["protected_branches"] == ["main"]

    assert main(["--root", str(tmp_path), "config", "get", "render.format"]) == 0
    assert json.loads(capsys.readouterr().out) == "md"


def test_config_set_updates_protected_branch_defaults_and_render(tmp_path: Path) -> None:
    _seed(tmp_path)

    assert main(["--root", str(tmp_path), "config", "set", "policy.protected_branches", '["main","release"]']) == 0
    assert main(["--root", str(tmp_path), "config", "set", "defaults.warning_mode", '"strict"']) == 0
    assert main(["--root", str(tmp_path), "config", "set", "render.format", '"ascii"']) == 0

    config = _load(tmp_path / ".gateflow" / "config.json")
    assert config["policy"]["protected_branches"] == ["main", "release"]
    assert config["defaults"]["warning_mode"] == "strict"
    assert config["render"]["format"] == "ascii"


def test_config_set_rejects_unsupported_keys(tmp_path: Path) -> None:
    _seed(tmp_path)
    assert main(["--root", str(tmp_path), "config", "set", "profile", '"minimal"']) == 2
