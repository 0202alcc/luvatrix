from __future__ import annotations

import json
from pathlib import Path

from gateflow.cli import main


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_init_scaffold_creates_core_files(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path), "init", "scaffold", "--profile", "minimal"]) == 0

    gateflow = tmp_path / ".gateflow"
    assert (gateflow / "config.json").exists()
    assert (gateflow / "milestones.json").exists()
    assert (gateflow / "tasks.json").exists()
    assert (gateflow / "boards.json").exists()
    assert (gateflow / "backlog.json").exists()
    assert (gateflow / "closeout").is_dir()


def test_init_scaffold_is_idempotent(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path), "init", "scaffold", "--profile", "minimal"]) == 0
    first = (tmp_path / ".gateflow" / "config.json").read_text(encoding="utf-8")

    assert main(["--root", str(tmp_path), "init", "scaffold", "--profile", "minimal"]) == 0
    second = (tmp_path / ".gateflow" / "config.json").read_text(encoding="utf-8")

    assert first == second


def test_init_doctor_reports_missing_core_files(tmp_path: Path, capsys) -> None:
    assert main(["--root", str(tmp_path), "init", "doctor"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is False
    assert "config.json" in payload["missing"]


def test_init_preserves_existing_ledger_items(tmp_path: Path) -> None:
    gateflow = tmp_path / ".gateflow"
    gateflow.mkdir(parents=True)
    (gateflow / "closeout").mkdir()
    (gateflow / "tasks.json").write_text(
        json.dumps({"items": [{"id": "T-1"}], "updated_at": "2026-03-07", "version": "gateflow_v1"}, indent=2) + "\n",
        encoding="utf-8",
    )

    assert main(["--root", str(tmp_path), "init", "scaffold", "--profile", "minimal"]) == 0
    payload = _load(gateflow / "tasks.json")
    assert payload["items"] == [{"id": "T-1"}]


def test_discord_profile_adds_overlay_namespace(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path), "init", "scaffold", "--profile", "discord"]) == 0
    config = _load(tmp_path / ".gateflow" / "config.json")
    assert config["overlays"] == ["discord"]
    assert "discord" in config["profiles"]


def test_enterprise_overlay_is_additive_and_applies_strict_defaults(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path), "init", "scaffold", "--profile", "discord"]) == 0
    assert main(["--root", str(tmp_path), "init", "scaffold", "--profile", "enterprise"]) == 0

    config = _load(tmp_path / ".gateflow" / "config.json")
    assert config["overlays"] == ["discord", "enterprise"]
    assert config["defaults"]["warning_mode"] == "strict"
    assert "release" in config["policy"]["protected_branches"]
