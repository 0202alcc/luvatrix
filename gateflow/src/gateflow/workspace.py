from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gateflow.io import read_json, write_json

LEDGER_FILES = {
    "milestones": "milestones.json",
    "tasks": "tasks.json",
    "boards": "boards.json",
    "backlog": "backlog.json",
}


@dataclass(frozen=True)
class GateflowWorkspace:
    root: Path

    @property
    def gateflow_dir(self) -> Path:
        return self.root / ".gateflow"

    def ledger_path(self, resource: str) -> Path:
        if resource in LEDGER_FILES:
            return self.gateflow_dir / LEDGER_FILES[resource]
        if resource == "frameworks":
            return self.gateflow_dir / "config.json"
        raise ValueError(f"unsupported resource: {resource}")

    def list_items(self, resource: str) -> list[dict[str, Any]]:
        if resource == "frameworks":
            config = read_json(self.ledger_path("frameworks"))
            return list(config.get("frameworks", []))
        ledger = read_json(self.ledger_path(resource))
        return list(ledger.get("items", []))

    def write_items(self, resource: str, items: list[dict[str, Any]]) -> None:
        if resource == "frameworks":
            config_path = self.ledger_path("frameworks")
            config = read_json(config_path)
            config["frameworks"] = _sort_items(items)
            write_json(config_path, config)
            return
        ledger_path = self.ledger_path(resource)
        ledger = read_json(ledger_path)
        ledger["items"] = _sort_items(items)
        write_json(ledger_path, ledger)


def _sort_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda row: str(row.get("id", row.get("name", ""))))
