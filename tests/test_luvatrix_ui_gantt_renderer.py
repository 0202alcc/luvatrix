from __future__ import annotations

import datetime as dt
import unittest

from luvatrix_ui.planning.gantt_renderer import GanttRenderConfig, render_gantt_ascii
from luvatrix_ui.planning.schema import PlanningTimeline, TimelineMilestone


def _sample_timeline() -> PlanningTimeline:
    return PlanningTimeline(
        title="Native Gantt Test",
        baseline_start_date=dt.date(2026, 2, 23),
        milestones=(
            TimelineMilestone(
                milestone_id="M-008",
                name="Plot UX",
                start_week=4,
                end_week=7,
                status="In Progress",
            ),
            TimelineMilestone(
                milestone_id="M-009",
                name="Data Workspace UI",
                start_week=7,
                end_week=9,
                status="Planned",
                dependencies=("M-008",),
            ),
            TimelineMilestone(
                milestone_id="M-011",
                name="Native Gantt + Agile",
                start_week=10,
                end_week=13,
                status="Planned",
                dependencies=("M-008", "M-009"),
            ),
        ),
    )


class GanttRendererTests(unittest.TestCase):
    def test_expanded_mode_includes_axis_and_milestones(self) -> None:
        text = render_gantt_ascii(_sample_timeline(), GanttRenderConfig(collapsed_lanes=False))
        self.assertIn("Weeks:", text)
        self.assertIn("Dates:", text)
        self.assertIn("M-011 Native Gantt + Agile", text)
        self.assertIn("Status colors:", text)

    def test_collapsed_mode_renders_lane_rows(self) -> None:
        text = render_gantt_ascii(_sample_timeline(), GanttRenderConfig(collapsed_lanes=True))
        self.assertIn("mode=collapsed", text)
        self.assertIn("lane:M", text)
        self.assertIn("members=M-008,M-009,M-011", text)

    def test_dependency_lines_render_arrows(self) -> None:
        text = render_gantt_ascii(_sample_timeline(), GanttRenderConfig(show_dependency_lines=True))
        self.assertIn("Dependency lines:", text)
        self.assertIn("M-008 -> M-009", text)
        self.assertIn("M-009 -> M-011", text)
        self.assertIn(">", text)


if __name__ == "__main__":
    unittest.main()
