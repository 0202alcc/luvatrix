#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
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

STATUS_CHAR = {
    "Complete": "=",
    "In Progress": "#",
    "Planned": "~",
    "At Risk": "!",
    "Blocked": "x",
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
    p = argparse.ArgumentParser(description="Generate detailed ASCII Gantt markdown with emoji milestone labels.")
    p.add_argument("--schedule", default="ops/planning/gantt/milestone_schedule.json")
    p.add_argument("--out", default="ops/planning/gantt/milestones_gantt.md")
    return p.parse_args()


def week_to_date(baseline_start: dt.date, week: int) -> dt.date:
    return baseline_start + dt.timedelta(days=(week - 1) * 7)


def build_headers(chart_start: dt.date, total_days: int) -> tuple[str, str]:
    week_header = [" "] * total_days
    date_header = [" "] * total_days

    for i in range(total_days):
        current = chart_start + dt.timedelta(days=i)
        if i % 7 == 0:
            week_num = (i // 7) + 1
            label = f"W{week_num:02d}"
            for j, ch in enumerate(label):
                if i + j < total_days:
                    week_header[i + j] = ch

            date_label = current.strftime("%m/%d")
            for j, ch in enumerate(date_label):
                if i + j < total_days:
                    date_header[i + j] = ch

    return "".join(week_header), "".join(date_header)


def build_row(chart_start: dt.date, total_days: int, start_week: int, end_week: int, fill_char: str) -> str:
    row = [" "] * total_days
    start_date = week_to_date(chart_start, start_week)
    end_date = week_to_date(chart_start, end_week) + dt.timedelta(days=6)
    start_idx = (start_date - chart_start).days
    end_idx = (end_date - chart_start).days
    start_idx = max(0, start_idx)
    end_idx = min(total_days - 1, end_idx)
    for i in range(start_idx, end_idx + 1):
        row[i] = fill_char
    return "".join(row)


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
        lifecycle = ms.get("lifecycle_events", [])
        if lifecycle:
            lines.append("- Lifecycle events:")
            for ev in lifecycle:
                when = ev.get("date", "unknown")
                event = ev.get("event", "event")
                framework = ev.get("framework")
                note = ev.get("note")
                parts = [f"{when} {event}"]
                if framework:
                    parts.append(f"(framework={framework})")
                if note:
                    parts.append(f"- {note}")
                lines.append(f"  - {' '.join(parts)}")
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
    baseline_start = dt.date.fromisoformat(data["baseline_start_date"])
    total_days = max_week * 7
    week_line, date_line = build_headers(baseline_start, total_days)
    max_label = max(len(milestone_label(ms)) for ms in milestones)
    label_width = max_label + 2

    lines: list[str] = []
    lines.append("# Detailed ASCII Gantt")
    lines.append("")
    lines.append(f"Canonical schedule source: `ops/planning/gantt/milestone_schedule.json`")
    lines.append("")
    lines.append("```text")
    lines.append(f"{'':<{label_width}}|{week_line}|")
    lines.append(f"{'':<{label_width}}|{date_line}|")
    lines.append(f"{'-' * label_width}+{'-' * total_days}+")
    for ms in milestones:
        status = ms.get("status", "Planned")
        fill = STATUS_CHAR.get(status, "~")
        bar = build_row(
            baseline_start,
            total_days,
            int(ms["start_week"]),
            int(ms["end_week"]),
            fill,
        )
        label = milestone_label(ms)
        suffix = status
        if status == "Complete" and ms.get("completed_on"):
            suffix = f"Complete ({ms['completed_on']})"
        lines.append(f"{label:<{label_width}}|{bar}| {suffix}")
    lines.append("")
    lines.append("Legend: '=' Complete, '#' In Progress, '~' Planned, '!' At Risk, 'x' Blocked")
    lines.append("```")
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
