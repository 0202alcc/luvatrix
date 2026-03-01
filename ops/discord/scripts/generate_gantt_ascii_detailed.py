#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path


STATUS_CHAR = {
    "Complete": "=",
    "In Progress": "#",
    "Planned": "~",
    "At Risk": "!",
    "Blocked": "x",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a detailed day-level ASCII Gantt from milestone_schedule.json."
    )
    parser.add_argument("--schedule", default="ops/planning/gantt/milestone_schedule.json")
    parser.add_argument("--out", default="ops/planning/gantt/milestones_gantt_detailed.md")
    return parser.parse_args()


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
        if current.weekday() == 0:
            label = current.strftime("%m/%d")
            for j, ch in enumerate(label):
                if i + j < total_days:
                    date_header[i + j] = ch

    return "".join(week_header), "".join(date_header)


def build_row(
    chart_start: dt.date,
    total_days: int,
    start_week: int,
    end_week: int,
    fill_char: str,
) -> str:
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


def main() -> int:
    args = parse_args()
    schedule_path = Path(args.schedule)
    out_path = Path(args.out)

    data = json.loads(schedule_path.read_text(encoding="utf-8"))
    milestones = data["milestones"]
    baseline_start = dt.date.fromisoformat(data["baseline_start_date"])
    max_week = max(int(m["end_week"]) for m in milestones)
    total_days = max_week * 7

    week_line, date_line = build_headers(baseline_start, total_days)

    label_width = max(len(f"{m['id']} {m['name']}") for m in milestones) + 2

    lines: list[str] = []
    lines.append(data.get("title", "Milestone Gantt"))
    lines.append(f"Baseline start: {baseline_start.isoformat()}  |  Window: {max_week} weeks ({total_days} days)")
    lines.append("")
    lines.append(f"{'':<{label_width}}|{week_line}|")
    lines.append(f"{'':<{label_width}}|{date_line}|")
    lines.append(f"{'-' * label_width}+{'-' * total_days}+")

    for milestone in milestones:
        status = milestone.get("status", "Planned")
        fill = STATUS_CHAR.get(status, "~")
        bar = build_row(
            baseline_start,
            total_days,
            int(milestone["start_week"]),
            int(milestone["end_week"]),
            fill,
        )
        label = f"{milestone['id']} {milestone['name']}"
        suffix = status
        if status == "Complete" and milestone.get("completed_on"):
            suffix = f"Complete ({milestone['completed_on']})"
        lines.append(f"{label:<{label_width}}|{bar}| {suffix}")

    lines.append("")
    lines.append("Legend: '=' Complete, '#' In Progress, '~' Planned, '!' At Risk, 'x' Blocked")
    text_chart = "\n".join(lines)
    markdown = (
        "# Detailed ASCII Gantt\n\n"
        f"Canonical schedule source: `{args.schedule}`\n\n"
        "```text\n"
        f"{text_chart}\n"
        "```\n"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
