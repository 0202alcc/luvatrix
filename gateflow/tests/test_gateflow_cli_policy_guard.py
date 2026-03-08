from __future__ import annotations

import json
import subprocess
from pathlib import Path

from gateflow.cli import main


def _seed(root: Path) -> None:
    assert main(["--root", str(root), "init", "scaffold", "--profile", "minimal"]) == 0


def _init_git_main(root: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True, text=True)


def _write_config(root: Path, payload: dict) -> None:
    config_path = root / ".gateflow" / "config.json"
    config_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_mutations_blocked_on_protected_branch(tmp_path: Path) -> None:
    _init_git_main(tmp_path)
    _seed(tmp_path)

    rc = main(["--root", str(tmp_path), "tasks", "create", "--body", '{"id":"T-1001"}'])
    assert rc == 3


def test_mutations_allowed_when_branch_not_protected(tmp_path: Path) -> None:
    _init_git_main(tmp_path)
    _seed(tmp_path)
    config = json.loads((tmp_path / ".gateflow" / "config.json").read_text(encoding="utf-8"))
    config["policy"]["protected_branches"] = ["release"]
    _write_config(tmp_path, config)

    rc = main(["--root", str(tmp_path), "tasks", "create", "--body", '{"id":"T-1002"}'])
    assert rc == 0


def test_mutations_blocked_on_protected_pattern(tmp_path: Path) -> None:
    _init_git_main(tmp_path)
    _seed(tmp_path)
    config = json.loads((tmp_path / ".gateflow" / "config.json").read_text(encoding="utf-8"))
    config["policy"]["protected_branches"] = []
    config["policy"]["protected_branch_patterns"] = ["main|release"]
    _write_config(tmp_path, config)

    rc = main(["--root", str(tmp_path), "tasks", "create", "--body", '{"id":"T-1003"}'])
    assert rc == 3
