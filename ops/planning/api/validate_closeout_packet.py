#!/usr/bin/env python3
"""Validate milestone closeout packet structure."""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path("ops/planning")
CLOSEOUT_DIR = ROOT / "closeout"
REQUIRED_SECTIONS = [
    "Objective Summary",
    "Task Final States",
    "Evidence",
    "Determinism",
    "Protocol Compatibility",
    "Modularity",
    "Residual Risks",
]


def normalize_heading(line: str) -> str:
    return line.strip().lstrip("#").strip().lower()


def validate_packet(milestone_id: str) -> tuple[bool, list[str], Path]:
    path = CLOSEOUT_DIR / f"{milestone_id.lower()}_closeout.md"
    if not path.exists():
        return False, [f"missing closeout file: {path}"], path
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return False, [f"empty closeout file: {path}"], path
    headings = {
        normalize_heading(line)
        for line in text.splitlines()
        if line.strip().startswith("#")
    }
    missing = [s for s in REQUIRED_SECTIONS if s.lower() not in headings]
    if missing:
        return False, [f"missing sections: {', '.join(missing)}"], path
    return True, [], path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate milestone closeout packet.")
    parser.add_argument("--milestone-id", required=True)
    args = parser.parse_args()

    ok, errors, path = validate_packet(args.milestone_id)
    if ok:
        print(f"validation: PASS ({path})")
        return 0
    print("validation: FAIL")
    for err in errors:
        print(f"- {err}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
