#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

STATUS_EMOJI = {
    "Planned": "⚪",
    "In Progress": "🔵",
    "At Risk": "🟠",
    "Blocked": "🔴",
    "Complete": "🟢",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate Discord-friendly pseudo-Gantt markdown.")
    p.add_argument("--schedule", default="discord/ops/milestone_schedule.json")
    p.add_argument("--out", default="discord/ops/milestones_gantt.md")
    return p.parse_args()


def render_markdown(data: dict) -> str:
    milestones = data["milestones"]
    max_week = max(int(m["end_week"]) for m in milestones)
    week_header = "Weeks: " + " ".join(f"W{w:02d}" for w in range(1, max_week + 1))

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
        status = ms.get("status", "Planned")
        emoji = STATUS_EMOJI.get(status, "⚪")
        bar = []
        for w in range(1, max_week + 1):
            bar.append("█" if start <= w <= end else "·")
        label = f"{ms['id']}".ljust(6)
        name = ms["name"][:34].ljust(34)
        lines.append(f"{label} {''.join(bar)} {emoji} {name}")
    lines.append("```")
    lines.append("")
    lines.append("Update policy: edit `discord/ops/milestone_schedule.json` and rerun posting scripts.")
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
