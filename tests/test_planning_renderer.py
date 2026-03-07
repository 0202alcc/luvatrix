from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import sys


API_DIR = Path(__file__).resolve().parents[1] / "ops" / "planning" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from planning_paths import PlanningPathResolver  # noqa: E402
from planning_renderer import SubprocessPlanningRenderer  # noqa: E402


def test_renderer_regenerates_text_only_gantt_artifacts(tmp_path: Path) -> None:
    paths = PlanningPathResolver(tmp_path).resolve()
    renderer = SubprocessPlanningRenderer()

    with patch("planning_renderer.subprocess.run") as run_mock:
        renderer.regenerate_gantt_artifacts(paths)

    assert run_mock.call_count == 1
    cmd = run_mock.call_args.args[0]
    assert "ops/discord/scripts/generate_gantt_markdown.py" in cmd
    assert "generate_gantt_png.py" not in " ".join(cmd)
