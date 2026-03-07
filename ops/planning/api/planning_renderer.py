from __future__ import annotations

import subprocess
import sys
from typing import Protocol

from planning_paths import PlanningPaths


class PlanningRenderer(Protocol):
    def regenerate_gantt_artifacts(self, paths: PlanningPaths) -> None:
        ...


class SubprocessPlanningRenderer:
    """Default renderer bridge used by planning CLI scripts."""

    def regenerate_gantt_artifacts(self, paths: PlanningPaths) -> None:
        commands = [
            [
                sys.executable,
                "ops/discord/scripts/generate_gantt_markdown.py",
                "--schedule",
                str(paths.schedule_path),
                "--out",
                str(paths.gantt_md_path),
            ],
            [
                sys.executable,
                "ops/discord/scripts/generate_gantt_png.py",
                "--schedule",
                str(paths.schedule_path),
                "--out",
                str(paths.gantt_png_path),
            ],
        ]
        for cmd in commands:
            subprocess.run(cmd, check=True, cwd=paths.repo_root)
