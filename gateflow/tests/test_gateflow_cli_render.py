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


def test_render_gantt_markdown_uses_deterministic_order(tmp_path: Path, capsys) -> None:
    _seed_workspace(tmp_path)
    assert main(["--root", str(tmp_path), "render", "gantt", "--format", "md"]) == 0
    out = capsys.readouterr().out
    assert "| ID | Name | Status | Start Week | End Week | Task Count |" in out
    assert out.index("| P-040 | Program Setup | Complete | 43 | 44 | 1 |") < out.index(
        "| U-043 | Rendering v1 (Text-Only) | Planned | 50 | 52 | 2 |"
    )


def test_render_gantt_ascii_can_write_file(tmp_path: Path) -> None:
    _seed_workspace(tmp_path)
    out_path = tmp_path / "artifacts" / "gantt.txt"
    assert main(["--root", str(tmp_path), "render", "gantt", "--format", "ascii", "--out", str(out_path)]) == 0
    text = out_path.read_text(encoding="utf-8")
    assert "ID" in text
    assert "P-040" in text
    assert "U-043" in text


def test_render_gantt_uses_config_default_format(tmp_path: Path, capsys) -> None:
    _seed_workspace(tmp_path)
    assert main(["--root", str(tmp_path), "render", "gantt"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("| ID | Name | Status | Start Week | End Week | Task Count |")


def test_render_board_markdown_outputs_grouped_rows(tmp_path: Path, capsys) -> None:
    _seed_workspace(tmp_path)
    assert main(["--root", str(tmp_path), "render", "board", "--format", "md"]) == 0
    out = capsys.readouterr().out
    assert "| Status | Tasks |" in out
    assert "| Done | T-4301: Render gantt md|ascii |" in out
    assert "| In Progress | T-4302: Render board md|ascii |" in out


def test_render_board_ascii_writes_file(tmp_path: Path) -> None:
    _seed_workspace(tmp_path)
    out_path = tmp_path / "artifacts" / "board.txt"
    assert main(["--root", str(tmp_path), "render", "board", "--format", "ascii", "--out", str(out_path)]) == 0
    text = out_path.read_text(encoding="utf-8")
    assert "[Done]" in text
    assert "T-4301: Render gantt md|ascii" in text
