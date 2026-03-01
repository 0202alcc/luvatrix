from __future__ import annotations

import datetime as dt
import unittest

from luvatrix_ui.planning.schema import AgileTaskCard, PlanningTimeline, TimelineMilestone
from luvatrix_ui.planning.validation import (
    require_valid_planning_suite,
    validate_dependency_integrity,
    validate_planning_suite,
)


def _valid_model() -> PlanningTimeline:
    return PlanningTimeline(
        title="Validation Test",
        baseline_start_date=dt.date(2026, 2, 23),
        milestones=(
            TimelineMilestone(milestone_id="M-008", name="Plot UX", start_week=4, end_week=8, status="In Progress"),
            TimelineMilestone(
                milestone_id="M-011",
                name="Native Planning",
                start_week=10,
                end_week=13,
                status="Planned",
                dependencies=("M-008",),
            ),
        ),
        tasks=(
            AgileTaskCard(task_id="T-1103", milestone_id="M-011", title="Agile renderer", status="Review"),
            AgileTaskCard(
                task_id="T-1104",
                milestone_id="M-011",
                title="Interaction layer",
                status="Review",
                dependencies=("T-1103",),
            ),
        ),
    )


class PlanningValidationTests(unittest.TestCase):
    def test_validate_planning_suite_passes_for_consistent_model(self) -> None:
        report = validate_planning_suite(_valid_model())
        self.assertTrue(report.ok)
        self.assertEqual(report.errors, ())

    def test_dependency_integrity_flags_missing_task_dep(self) -> None:
        bad = PlanningTimeline(
            title="Missing dep",
            baseline_start_date=dt.date(2026, 2, 23),
            milestones=(TimelineMilestone(milestone_id="M-011", name="Native", start_week=10, end_week=13, status="Planned"),),
            tasks=(
                AgileTaskCard(
                    task_id="T-1105",
                    milestone_id="M-011",
                    title="Exports",
                    status="In Progress",
                    dependencies=("T-9999",),
                ),
            ),
        )
        report = validate_dependency_integrity(bad)
        self.assertFalse(report.ok)
        self.assertTrue(any("unresolved dependencies" in message for message in report.errors))

    def test_dependency_integrity_flags_cycles(self) -> None:
        cyc = PlanningTimeline(
            title="Cyclic",
            baseline_start_date=dt.date(2026, 2, 23),
            milestones=(
                TimelineMilestone(
                    milestone_id="M-008",
                    name="A",
                    start_week=1,
                    end_week=2,
                    status="Planned",
                    dependencies=("M-011",),
                ),
                TimelineMilestone(
                    milestone_id="M-011",
                    name="B",
                    start_week=3,
                    end_week=4,
                    status="Planned",
                    dependencies=("M-008",),
                ),
            ),
            tasks=(
                AgileTaskCard(task_id="T-1", milestone_id="M-011", title="A", dependencies=("T-2",)),
                AgileTaskCard(task_id="T-2", milestone_id="M-011", title="B", dependencies=("T-1",)),
            ),
        )
        report = validate_dependency_integrity(cyc)
        self.assertFalse(report.ok)
        self.assertTrue(any("cycle" in message.lower() for message in report.errors))

    def test_require_valid_raises_when_invalid(self) -> None:
        bad = PlanningTimeline(
            title="Bad",
            baseline_start_date=dt.date(2026, 2, 23),
            milestones=(TimelineMilestone(milestone_id="M-011", name="Native", start_week=10, end_week=13, status="Planned"),),
            tasks=(AgileTaskCard(task_id="T-1", milestone_id="M-011", title="X", dependencies=("T-2",)),),
        )
        with self.assertRaisesRegex(ValueError, "Planning validation failed"):
            require_valid_planning_suite(bad)


if __name__ == "__main__":
    unittest.main()
