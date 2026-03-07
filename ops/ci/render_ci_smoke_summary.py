from __future__ import annotations

import argparse
import json
from pathlib import Path


def render_summary(index_payload: dict[str, object], artifact_base_url: str) -> str:
    checks = index_payload.get("checks")
    if not isinstance(checks, list):
        raise ValueError("checks must be a list")

    lines: list[str] = ["# P-013 CI Smoke Signals", "", "| Check | Status | Artifact |", "|---|---|---|"]
    for item in checks:
        if not isinstance(item, dict):
            raise ValueError("check entry must be an object")
        name = str(item.get("name", "unknown"))
        status = str(item.get("status", "unknown"))
        artifact = str(item.get("artifact", ""))
        artifact_link = artifact
        if artifact and artifact_base_url:
            artifact_link = f"[{artifact}]({artifact_base_url.rstrip('/')}/{artifact})"
        elif artifact:
            artifact_link = f"`{artifact}`"
        else:
            artifact_link = "n/a"
        lines.append(f"| {name} | {status} | {artifact_link} |")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render P-013 CI smoke summary markdown")
    parser.add_argument("--index", type=Path, required=True, help="path to smoke index json")
    parser.add_argument("--out", type=Path, required=True, help="output markdown path")
    parser.add_argument(
        "--artifact-base-url",
        type=str,
        default="",
        help="optional base URL for artifact links",
    )
    args = parser.parse_args()

    payload = json.loads(args.index.read_text(encoding="utf-8"))
    summary = render_summary(payload, args.artifact_base_url)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(summary, encoding="utf-8")
    print(f"WROTE: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
