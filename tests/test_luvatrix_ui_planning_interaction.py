from __future__ import annotations

import datetime as dt
import unittest

from luvatrix_ui.planning.interaction import (
    PlanningInteractionState,
    apply_task_filters,
    apply_week_viewport,
    milestone_clickthrough_map,
    pan_week_window,
    zoom_week_window,
)
from luvatrix_ui.planning.schema import AgileTaskCard, PlanningTimeline, TimelineMilestone


def _model() -> PlanningTimeline:
    return PlanningTimeline(
        title="Interaction Test",
        baseline_start_date=dt.date(2026, 2, 23),
        milestones=(
            TimelineMilestone(milestone_id="M-008", name="Plot UX", start_week=4, end_week=8, status="In Progress"),
            TimelineMilestone(milestone_id="M-011", name="Native Gantt", start_week=10, end_week=13, status="Planned"),
        ),
        tasks=(
            AgileTaskCard(
                task_id="T-1103",
                milestone_id="M-011",
                title="Agile board renderer",
                status="In Progress",
                owners=("AI-Rendering",),
            ),
            AgileTaskCard(
                task_id="T-1104",
                milestone_id="M-011",
                title="Interaction layer",
                status="Backlog",
                dependencies=("T-1103",),
                owners=("AI-Runtime",),
            ),
            AgileTaskCard(
                task_id="T-805",
                milestone_id="M-008",
                title="Table UI",
                status="Review",
                owners=("AI-Runtime",),
            ),
        ),
    )


class PlanningInteractionTests(unittest.TestCase):
    def test_pan_and_zoom_week_window_clamp_to_bounds(self) -> None:
        model = _model()
        state = PlanningInteractionState(week_start=10, week_span=3)
        moved = pan_week_window(model, state, delta_weeks=10)
        self.assertEqual(moved.week_start, 11)

        zoomed = zoom_week_window(model, moved, delta_span=10)
        self.assertEqual(zoomed.week_span, 13)
        self.assertEqual(zoomed.week_start, 1)

    def test_apply_week_viewport_clips_milestones(self) -> None:
        model = _model()
        state = PlanningInteractionState(week_start=9, week_span=2)
        windowed = apply_week_viewport(model, state)
        self.assertEqual(len(windowed.milestones), 1)
        self.assertEqual(windowed.milestones[0].milestone_id, "M-011")
        self.assertEqual((windowed.milestones[0].start_week, windowed.milestones[0].end_week), (10, 10))

    def test_apply_task_filters_by_status_owner_and_query(self) -> None:
        model = _model()
        state = PlanningInteractionState(
            status_filter=("Backlog",),
            owner_filter=("AI-Runtime",),
            text_query="interaction",
        )
        filtered = apply_task_filters(model, state)
        self.assertEqual([task.task_id for task in filtered], ["T-1104"])

    def test_clickthrough_map_groups_tasks_by_milestone(self) -> None:
        mapping = milestone_clickthrough_map(_model())
        self.assertIn("M-011", mapping)
        self.assertEqual([task.task_id for task in mapping["M-011"]], ["T-1103", "T-1104"])


if __name__ == "__main__":
    unittest.main()
