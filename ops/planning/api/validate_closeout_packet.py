#!/usr/bin/env python3
"""Validate milestone closeout packet structure."""

from __future__ import annotations

import argparse

from planning_paths import PlanningPathResolver


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


def validate_packet(milestone_id: str, *, root: str) -> tuple[bool, list[str], str]:
    closeout_dir = PlanningPathResolver(root).resolve().closeout_dir
    path = closeout_dir / f"{milestone_id.lower()}_closeout.md"
    if not path.exists():
        return False, [f"missing closeout file: {path}"], str(path)
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return False, [f"empty closeout file: {path}"], str(path)
    headings = {
        normalize_heading(line)
        for line in text.splitlines()
        if line.strip().startswith("#")
    }
    missing = [s for s in REQUIRED_SECTIONS if s.lower() not in headings]
    if missing:
        return False, [f"missing sections: {', '.join(missing)}"], str(path)
    return True, [], str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate milestone closeout packet.")
    parser.add_argument("--milestone-id", required=True)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()

    ok, errors, path = validate_packet(args.milestone_id, root=args.root)
    if ok:
        print(f"validation: PASS ({path})")
        return 0
    print("validation: FAIL")
    for err in errors:
        print(f"- {err}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
