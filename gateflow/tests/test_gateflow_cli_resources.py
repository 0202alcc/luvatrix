from __future__ import annotations

import json
from pathlib import Path

from gateflow.cli import main


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _seed_workspace(root: Path) -> None:
    gateflow = root / ".gateflow"
    gateflow.mkdir(parents=True)
    _write_json(
        gateflow / "config.json",
        {
            "frameworks": [{"name": "gateflow_v1", "status": "active"}],
            "version": "gateflow_v1",
        },
    )
    for name in ("milestones", "tasks", "boards", "backlog"):
        _write_json(gateflow / f"{name}.json", {"items": [], "version": "gateflow_v1"})


def test_resource_crud_for_id_ledgers(tmp_path: Path) -> None:
    _seed_workspace(tmp_path)

    assert main(["--root", str(tmp_path), "milestones", "create", "--body", '{"id":"F-100","name":"One"}']) == 0
    assert main(["--root", str(tmp_path), "milestones", "update", "F-100", "--body", '{"status":"Planned"}']) == 0
    assert main(["--root", str(tmp_path), "milestones", "get", "F-100"]) == 0
    assert main(["--root", str(tmp_path), "milestones", "delete", "F-100"]) == 0


def test_frameworks_use_name_key(tmp_path: Path) -> None:
    _seed_workspace(tmp_path)

    assert main(["--root", str(tmp_path), "frameworks", "create", "--body", '{"name":"kanban_v1"}']) == 0
    assert main(["--root", str(tmp_path), "frameworks", "get", "kanban_v1"]) == 0
    assert main(["--root", str(tmp_path), "frameworks", "delete", "kanban_v1"]) == 0


def test_list_is_deterministically_sorted(tmp_path: Path, capsys) -> None:
    _seed_workspace(tmp_path)

    assert main(["--root", str(tmp_path), "tasks", "create", "--body", '{"id":"T-4202"}']) == 0
    assert main(["--root", str(tmp_path), "tasks", "create", "--body", '{"id":"T-4201"}']) == 0
    _ = capsys.readouterr()
    assert main(["--root", str(tmp_path), "tasks", "list"]) == 0

    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert [row["id"] for row in parsed] == ["T-4201", "T-4202"]
