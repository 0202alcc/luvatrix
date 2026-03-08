#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

SUNSET_DATE = date(2026, 6, 30)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize legacy planning_api.py deprecation usage telemetry.")
    parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="How many top commands to show (default: 10).",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    log_path = root / "ops" / "planning" / "telemetry" / "planning_api_deprecation_usage.jsonl"
    if not log_path.exists():
        print(json.dumps({"status": "no_data", "log_path": str(log_path)}, indent=2, sort_keys=True))
        return 0

    entries = []
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    method_path = Counter(f"{e.get('method', '?')} {e.get('path', '?')}" for e in entries)
    day_counter = Counter()
    for e in entries:
        ts = e.get("ts_utc")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            continue
        day_counter[dt.date().isoformat()] += 1

    today = date.today()
    payload = {
        "status": "ok",
        "log_path": str(log_path),
        "entries_total": len(entries),
        "sunset_date": SUNSET_DATE.isoformat(),
        "days_until_sunset": (SUNSET_DATE - today).days,
        "top_commands": [{"command": cmd, "count": count} for cmd, count in method_path.most_common(args.limit)],
        "daily_counts": [{"date": day, "count": count} for day, count in sorted(day_counter.items())],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
