from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from luvatrix_ui.planning.schema import (
    AgileTaskCard,
    PlanningTimeline,
    build_m011_task_cards,
    load_timeline_model,
    load_task_cards_from_ledger,
    planning_timeline_schema,
    timeline_from_dict,
)


class PlanningSchemaTests(unittest.TestCase):
    def test_timeline_from_dict_parses_milestones_and_tasks(self) -> None:
        payload = {
            "title": "Demo Timeline",
            "baseline_start_date": "2026-02-23",
            "milestones": [
                {
                    "id": "M-011",
                    "name": "Native Gantt",
                    "start_week": 10,
                    "end_week": 13,
                    "status": "Planned",
                    "dependencies": ["M-008", "M-009"],
                    "owners": ["Rendering", "Runtime"],
                }
            ],
            "tasks": [
                {
                    "id": "T-1101",
                    "milestone_id": "M-011",
                    "title": "Define schema",
                    "status": "In Progress",
                    "deps": ["T-1100"],
                    "owner": "AI-Architect",
                }
            ],
        }

        model = timeline_from_dict(payload)

        self.assertIsInstance(model, PlanningTimeline)
        self.assertEqual(model.title, "Demo Timeline")
        self.assertEqual(model.baseline_start_date, dt.date(2026, 2, 23))
        self.assertEqual(model.milestones[0].dependencies, ("M-008", "M-009"))
        self.assertEqual(model.tasks[0].owners, ("AI-Architect",))
        self.assertEqual(model.tasks[0].dependencies, ("T-1100",))

    def test_load_timeline_model_reads_json_file(self) -> None:
        payload = {
            "title": "From File",
            "baseline_start_date": "2026-02-23",
            "milestones": [
                {
                    "id": "M-001",
                    "name": "Governance",
                    "start_week": 1,
                    "end_week": 2,
                    "status": "In Progress",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "schedule.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            model = load_timeline_model(path)
        self.assertEqual(model.milestones[0].milestone_id, "M-001")
        self.assertEqual(model.max_week(), 2)

    def test_schema_has_required_timeline_fields(self) -> None:
        schema = planning_timeline_schema()
        self.assertIn("required", schema)
        self.assertIn("milestones", schema["required"])
        self.assertIn("baseline_start_date", schema["required"])

    def test_m011_task_chain_is_ordered(self) -> None:
        cards = build_m011_task_cards()
        self.assertEqual(len(cards), 6)
        self.assertIsInstance(cards[0], AgileTaskCard)
        self.assertEqual(cards[0].task_id, "T-1101")
        self.assertEqual(cards[0].milestone_id, "APU-020")
        self.assertEqual(cards[1].dependencies, ("T-1101",))
        self.assertEqual(cards[-1].dependencies, ("T-1105",))

    def test_load_task_cards_from_ledger_filters_by_milestone(self) -> None:
        payload = {
            "tasks": [
                {
                    "id": "T-1101",
                    "title": "Schema contract",
                    "milestone_id": "APU-020",
                    "status": "Backlog",
                    "depends_on": [],
                },
                {
                    "id": "T-1102",
                    "title": "Renderer",
                    "milestone_id": "APU-020",
                    "status": "Backlog",
                    "depends_on": ["T-1101"],
                },
                {
                    "id": "T-9999",
                    "title": "Other milestone task",
                    "milestone_id": "X-001",
                    "status": "Backlog",
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            cards = load_task_cards_from_ledger(path, milestone_id="APU-020")
        self.assertEqual([card.task_id for card in cards], ["T-1101", "T-1102"])
        self.assertEqual(cards[1].dependencies, ("T-1101",))


if __name__ == "__main__":
    unittest.main()
