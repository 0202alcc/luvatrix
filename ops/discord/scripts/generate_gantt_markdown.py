#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

STATUS_EMOJI = {
    "Planned": "⚪",
    "In Progress": "🔵",
    "At Risk": "🟠",
    "Blocked": "🔴",
    "Complete": "🟢",
}


def milestone_label(ms: dict) -> str:
    icon = ms.get("emoji", "").strip()
    if icon:
        return f"{ms['id']} {icon} {ms['name']}"
    return f"{ms['id']} {ms['name']}"


def milestone_status_text(ms: dict) -> str:
    status = ms.get("status", "Planned")
    emoji = STATUS_EMOJI.get(status, "⚪")
    completed_on = ms.get("completed_on")
    if status == "Complete" and completed_on:
        return f"{emoji} Complete ({completed_on})"
    return f"{emoji} {status}"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate Discord-friendly pseudo-Gantt markdown.")
    p.add_argument("--schedule", default="ops/planning/gantt/milestone_schedule.json")
    p.add_argument("--out", default="ops/planning/gantt/milestones_gantt.md")
    return p.parse_args()


def render_milestone_details(milestones: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    lines.append("## Milestone Details")
    lines.append("")
    for ms in milestones:
        lines.append(f"### {milestone_label(ms)}")
        lines.append(f"- Status: {ms.get('status', 'Planned')}")
        lines.append(f"- Target window: Week {ms['start_week']}-{ms['end_week']}")
        if ms.get("completed_on"):
            lines.append(f"- Completed on: {ms['completed_on']}")
        if ms.get("task_ids"):
            task_ids = ", ".join(ms["task_ids"])
            lines.append(f"- Tasks: `{task_ids}`")
        if ms.get("success_criteria"):
            lines.append("- Success criteria:")
            for criterion in ms["success_criteria"]:
                lines.append(f"  - {criterion}")
        if ms.get("acceptance_checks"):
            lines.append("- Acceptance checks:")
            for task_id, check in ms["acceptance_checks"].items():
                lines.append(f"  - `{task_id}`: {check}")
        lines.append("")
    return lines


def render_markdown(data: dict) -> str:
    milestones = data["milestones"]
    max_week = max(int(m["end_week"]) for m in milestones)
    week_header = "Weeks: " + " ".join(f"W{w:02d}" for w in range(1, max_week + 1))
    max_label = max(len(milestone_label(ms)) for ms in milestones)

    lines: list[str] = []
    lines.append(f"# {data.get('title', 'Milestone Gantt')}")
    lines.append("")
    lines.append(week_header)
    lines.append("")
    lines.append("Legend: 🔵 In Progress | ⚪ Planned | 🟠 At Risk | 🔴 Blocked | 🟢 Complete")
    lines.append("")
    lines.append("```text")
    for ms in milestones:
        start = int(ms["start_week"])
        end = int(ms["end_week"])
        bar = []
        for w in range(1, max_week + 1):
            bar.append("█" if start <= w <= end else "·")
        label = milestone_label(ms).ljust(max_label)
        lines.append(f"{label}  {''.join(bar)}  {milestone_status_text(ms)}")
    lines.append("```")
    lines.append("")
    lines.append("Canonical schedule source: `ops/planning/gantt/milestone_schedule.json`")
    lines.append("")
    lines.extend(render_milestone_details(milestones))
    lines.append("## Branching and Merge Gate Policy")
    lines.append("1. Each milestone is implemented first on its own milestone branch.")
    lines.append("2. Cross-milestone dependencies are resolved by merge-to-main or explicit branch pull/cherry-pick with traceability notes.")
    lines.append("3. A milestone is not Complete until merged into main and required tests pass on main.")
    lines.append("")
    lines.append("## Weekly Update Format")
    lines.append("1. Milestone ID")
    lines.append("2. Planned vs actual progress")
    lines.append("3. New risks/blockers")
    lines.append("4. Dependency impact")
    lines.append("5. Branch integration status")
    lines.append("6. Main-branch test status")
    lines.append("7. Next-week focus")
    lines.append("")
    lines.append("Update policy: edit `ops/planning/gantt/milestone_schedule.json` and rerun posting scripts.")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    schedule_path = Path(args.schedule)
    out_path = Path(args.out)
    data = json.loads(schedule_path.read_text(encoding="utf-8"))
    markdown = render_markdown(data)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
