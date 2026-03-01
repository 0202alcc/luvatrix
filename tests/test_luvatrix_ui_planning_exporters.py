from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from luvatrix_ui.planning.exporters import build_discord_payload, export_planning_bundle
from luvatrix_ui.planning.schema import AgileTaskCard, PlanningTimeline, TimelineMilestone


def _model() -> PlanningTimeline:
    return PlanningTimeline(
        title="Export Test",
        baseline_start_date=dt.date(2026, 2, 23),
        milestones=(
            TimelineMilestone(milestone_id="M-011", name="Native Planning", start_week=10, end_week=13, status="Planned"),
        ),
        tasks=(
            AgileTaskCard(
                task_id="T-1105",
                milestone_id="M-011",
                title="Export adapters",
                status="In Progress",
            ),
        ),
    )


class PlanningExportersTests(unittest.TestCase):
    def test_export_bundle_writes_ascii_markdown_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            bundle = export_planning_bundle(_model(), out_dir=out_dir, prefix="unit")

            self.assertTrue(bundle.ascii_gantt_expanded.exists())
            self.assertTrue(bundle.ascii_gantt_collapsed.exists())
            self.assertTrue(bundle.ascii_agile.exists())
            self.assertTrue(bundle.markdown_overview.exists())
            self.assertTrue(bundle.markdown_agile.exists())
            self.assertTrue(bundle.png_overview.exists())
            self.assertGreater(bundle.png_overview.stat().st_size, 0)

    def test_build_discord_payload_contains_attachment_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = export_planning_bundle(_model(), out_dir=Path(tmp), prefix="discord")
            payload = build_discord_payload(
                title="M-011",
                summary="Export complete",
                bundle=bundle,
            )
            self.assertIn("content", payload)
            self.assertIn("attachments", payload)
            self.assertIn("files", payload)
            self.assertEqual(len(payload["attachments"]), 6)
            self.assertEqual(len(payload["files"]), 6)


if __name__ == "__main__":
    unittest.main()
