from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from planning_paths import PlanningPaths


@dataclass
class PlanningState:
    schedule: dict[str, Any]
    tasks_master: dict[str, Any]
    tasks_archived: dict[str, Any]
    boards: dict[str, Any]
    backlog: dict[str, Any]


class JsonPlanningStorage:
    def __init__(self, paths: PlanningPaths) -> None:
        self.paths = paths

    @staticmethod
    def load_json(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def write_json(path: Path, payload: dict[str, Any]) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)

    def load_state(self) -> PlanningState:
        return PlanningState(
            schedule=self.load_json(self.paths.schedule_path),
            tasks_master=self.load_json(self.paths.tasks_master_path),
            tasks_archived=self.load_json(self.paths.tasks_archived_path),
            boards=self.load_json(self.paths.boards_path),
            backlog=self.load_json(self.paths.backlog_path),
        )

    def write_state(self, state: PlanningState) -> None:
        self.write_json(self.paths.schedule_path, state.schedule)
        self.write_json(self.paths.tasks_master_path, state.tasks_master)
        self.write_json(self.paths.tasks_archived_path, state.tasks_archived)
        self.write_json(self.paths.boards_path, state.boards)
        self.write_json(self.paths.backlog_path, state.backlog)
