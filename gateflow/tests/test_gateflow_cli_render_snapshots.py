from __future__ import annotations

import json
from pathlib import Path

from gateflow.render import render_board, render_gantt
from gateflow.workspace import GateflowWorkspace


SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots" / "gateflow_cli"


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _seed_workspace(root: Path) -> GateflowWorkspace:
    gateflow = root / ".gateflow"
    gateflow.mkdir(parents=True)
    _write_json(
        gateflow / "config.json",
        {
            "frameworks": [{"name": "gateflow_v1", "status": "active"}],
            "render": {"format": "md", "lane_mode": "milestone"},
            "version": "gateflow_v1",
        },
    )
    _write_json(
        gateflow / "milestones.json",
        {
            "items": [
                {"id": "U-043", "name": "Rendering v1 (Text-Only)", "status": "Planned", "start_week": 50, "end_week": 52, "task_ids": ["T-4300", "T-4301"]},
                {"id": "P-040", "name": "Program Setup", "status": "Complete", "start_week": 43, "end_week": 44, "task_ids": ["T-4000"]},
            ],
            "version": "gateflow_v1",
        },
    )
    _write_json(
        gateflow / "tasks.json",
        {
            "items": [
                {"id": "T-4303", "title": "Remove PNG path", "status": "Intake"},
                {"id": "T-4301", "title": "Render gantt md|ascii", "status": "Done"},
                {"id": "T-4302", "title": "Render board md|ascii", "status": "In Progress"},
            ],
            "version": "gateflow_v1",
        },
    )
    for name in ("boards", "backlog"):
        _write_json(gateflow / f"{name}.json", {"items": [], "version": "gateflow_v1"})
    return GateflowWorkspace(root)


def _snapshot(name: str) -> str:
    return (SNAPSHOT_DIR / name).read_text(encoding="utf-8")


def test_gantt_markdown_snapshot(tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path)
    assert render_gantt(workspace, out_path=None, fmt="md") == _snapshot("gantt.md")


def test_gantt_ascii_snapshot(tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path)
    assert render_gantt(workspace, out_path=None, fmt="ascii") == _snapshot("gantt.ascii")


def test_board_markdown_snapshot(tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path)
    assert render_board(workspace, out_path=None, fmt="md") == _snapshot("board.md")


def test_board_ascii_snapshot(tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path)
    assert render_board(workspace, out_path=None, fmt="ascii") == _snapshot("board.ascii")
