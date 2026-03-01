from __future__ import annotations

import datetime as dt
import unittest

from luvatrix_ui.planning.agile_renderer import AgileRenderConfig, render_agile_board_ascii, render_agile_board_markdown
from luvatrix_ui.planning.schema import AgileTaskCard, PlanningTimeline, TimelineMilestone


def _model() -> PlanningTimeline:
    return PlanningTimeline(
        title="Agile Renderer Test",
        baseline_start_date=dt.date(2026, 2, 23),
        milestones=(
            TimelineMilestone(
                milestone_id="M-011",
                name="Native Gantt + Agile",
                start_week=10,
                end_week=13,
                status="Planned",
            ),
        ),
        tasks=(
            AgileTaskCard(
                task_id="T-1103",
                milestone_id="M-011",
                epic_id="E-1101",
                title="Build agile board renderer core.",
                status="In Progress",
                owners=("AI-Rendering",),
            ),
            AgileTaskCard(
                task_id="T-1104",
                milestone_id="M-011",
                epic_id="E-1101",
                title="Add interaction layer for filters and click-through.",
                status="Backlog",
                dependencies=("T-1103",),
                blockers=("M-008 viewport controls",),
                owners=("AI-Runtime",),
            ),
            AgileTaskCard(
                task_id="T-1105",
                milestone_id="M-011",
                epic_id="E-1101",
                title="Add export adapters.",
                status="Review",
            ),
        ),
    )


class AgileRendererTests(unittest.TestCase):
    def test_ascii_renderer_outputs_columns_and_swimlane(self) -> None:
        text = render_agile_board_ascii(_model(), AgileRenderConfig(lane_mode="milestone"))
        self.assertIn("Columns: Backlog | Ready | In Progress | Review | Done", text)
        self.assertIn("[swimlane:M-011]", text)
        self.assertIn("T-1103 Build agile board renderer core.", text)
        self.assertIn("Blockers:", text)
        self.assertIn("blocked_by=M-008 viewport controls", text)

    def test_ascii_renderer_supports_owner_swimlanes(self) -> None:
        text = render_agile_board_ascii(_model(), AgileRenderConfig(lane_mode="owner"))
        self.assertIn("[swimlane:AI-Rendering]", text)
        self.assertIn("[swimlane:AI-Runtime]", text)
        self.assertIn("[swimlane:unassigned]", text)

    def test_markdown_renderer_outputs_table(self) -> None:
        markdown = render_agile_board_markdown(_model())
        self.assertIn("# Agile Renderer Test Agile Board", markdown)
        self.assertIn("| Backlog | Ready | In Progress | Review | Done |", markdown)
        self.assertIn("## Swimlane `M-011`", markdown)


if __name__ == "__main__":
    unittest.main()
