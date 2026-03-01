#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt

STATUS_COLORS = {
    "Planned": "#94A3B8",
    "In Progress": "#2563EB",
    "At Risk": "#F59E0B",
    "Blocked": "#DC2626",
    "Complete": "#16A34A",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate Gantt PNG from milestone schedule JSON.")
    p.add_argument("--schedule", default="ops/planning/gantt/milestone_schedule.json")
    p.add_argument("--out", default="ops/planning/gantt/milestones_gantt.png")
    return p.parse_args()


def week_to_date(baseline_start: dt.date, week: int) -> dt.date:
    return baseline_start + dt.timedelta(days=(week - 1) * 7)


def main() -> int:
    args = parse_args()
    schedule_path = Path(args.schedule)
    out_path = Path(args.out)

    data = json.loads(schedule_path.read_text(encoding="utf-8"))
    baseline_start = dt.date.fromisoformat(data["baseline_start_date"])
    milestones = data["milestones"]

    labels: list[str] = []
    starts: list[float] = []
    durations: list[int] = []
    colors: list[str] = []

    for ms in milestones:
        s = week_to_date(baseline_start, int(ms["start_week"]))
        e = week_to_date(baseline_start, int(ms["end_week"])) + dt.timedelta(days=6)
        icon = ms.get("emoji", "").strip()
        if icon and icon.isascii():
            labels.append(f"{ms['id']} {icon} {ms['name']}")
        else:
            labels.append(f"{ms['id']} {ms['name']}")
        starts.append(mdates.date2num(s))
        durations.append((e - s).days + 1)
        colors.append(STATUS_COLORS.get(ms.get("status", "Planned"), STATUS_COLORS["Planned"]))

    fig_h = max(5, 0.7 * len(labels) + 2)
    fig, ax = plt.subplots(figsize=(14, fig_h))
    y = list(range(len(labels)))
    ax.barh(y, durations, left=starts, color=colors, edgecolor="#1f2937")
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()

    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO, interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    plt.xticks(rotation=0)
    ax.grid(axis="x", linestyle="--", alpha=0.35)

    title = data.get("title", "Milestone Gantt")
    ax.set_title(title)
    ax.set_xlabel("Timeline")

    for i, ms in enumerate(milestones):
        status = ms.get("status", "Planned")
        completed_on = ms.get("completed_on")
        status_text = status
        if status == "Complete" and completed_on:
            status_text = f"Complete ({completed_on})"
        ax.text(starts[i] + durations[i] + 0.4, i, status_text, va="center", fontsize=9, color="#111827")

    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=180)
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
