#!/usr/bin/env python3
"""Check whether ops/planning differs from a base ref (default: origin/main)."""

from __future__ import annotations

import argparse
import subprocess
import sys


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def ensure_ref(ref: str) -> None:
    proc = run(["git", "rev-parse", "--verify", ref])
    if proc.returncode != 0:
        raise RuntimeError(f"ref not found: {ref}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect planning drift vs base ref.")
    parser.add_argument("--base", default="origin/main", help="Base git ref to compare against.")
    parser.add_argument("--path", default="ops/planning", help="Path to compare.")
    parser.add_argument("--fetch", action="store_true", help="Fetch origin before comparison.")
    args = parser.parse_args()

    if args.fetch:
        fetch = run(["git", "fetch", "origin", "main"])
        if fetch.returncode != 0:
            print(fetch.stderr.strip() or fetch.stdout.strip(), file=sys.stderr)
            return 2

    try:
        ensure_ref(args.base)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    current_branch = branch.stdout.strip() if branch.returncode == 0 else "<unknown>"

    changed = run(["git", "diff", "--name-status", f"{args.base}...HEAD", "--", args.path])
    if changed.returncode != 0:
        print(changed.stderr.strip() or changed.stdout.strip(), file=sys.stderr)
        return 2

    lines = [line for line in changed.stdout.splitlines() if line.strip()]
    if not lines:
        print(f"[OK] planning in sync with {args.base} (branch={current_branch})")
        return 0

    print(f"[DRIFT] planning differs from {args.base} (branch={current_branch})")
    print("changed files:")
    for line in lines:
        print(f"- {line}")
    print("hint: run ops/planning/api/sync_planning_from_main.sh")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
