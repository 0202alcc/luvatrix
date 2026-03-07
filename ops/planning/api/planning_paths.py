from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PlanningPaths:
    repo_root: Path
    planning_root: Path
    schedule_path: Path
    tasks_master_path: Path
    tasks_archived_path: Path
    boards_path: Path
    backlog_path: Path
    gantt_md_path: Path
    gantt_png_path: Path
    closeout_dir: Path


class PlanningPathResolver:
    """Resolves planning ledger paths from a configurable repository root."""

    def __init__(self, repo_root: Path | str | None = None) -> None:
        root = Path.cwd() if repo_root is None else Path(repo_root)
        self._repo_root = root.expanduser().resolve()

    def resolve(self) -> PlanningPaths:
        planning_root = self._repo_root / "ops" / "planning"
        return PlanningPaths(
            repo_root=self._repo_root,
            planning_root=planning_root,
            schedule_path=planning_root / "gantt" / "milestone_schedule.json",
            tasks_master_path=planning_root / "agile" / "tasks_master.json",
            tasks_archived_path=planning_root / "agile" / "tasks_archived.json",
            boards_path=planning_root / "agile" / "boards_registry.json",
            backlog_path=planning_root / "agile" / "backlog_misc.json",
            gantt_md_path=planning_root / "gantt" / "milestones_gantt.md",
            gantt_png_path=planning_root / "gantt" / "milestones_gantt.png",
            closeout_dir=planning_root / "closeout",
        )
