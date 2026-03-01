from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from luvatrix_ui.planning import (
    attach_dependency_defaults,
    build_m011_task_cards,
    build_discord_payload,
    export_planning_bundle,
    load_timeline_model,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Native M-011 planning demo renderer.")
    parser.add_argument("--schedule", default="ops/planning/gantt/milestone_schedule.json")
    parser.add_argument("--out", default="ops/planning/gantt/m011_native_gantt_demo.txt")
    parser.add_argument("--export-dir", default="ops/planning/gantt/m011_native_exports")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model = load_timeline_model(args.schedule, tasks=build_m011_task_cards())
    model = attach_dependency_defaults(model)

    bundle = export_planning_bundle(model, out_dir=args.export_dir, prefix="m011_native")
    payload = build_discord_payload(
        title="M-011 Native Planning Export",
        summary="ASCII/Markdown/PNG artifacts generated from milestone_schedule.json.",
        bundle=bundle,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "M-011 Native Planning Demo\n"
        + f"Export root: {args.export_dir}\n\n"
        + "Artifacts:\n"
        + "\n".join(f"- {key}: {value}" for key, value in bundle.as_dict().items())
        + "\n\n"
        + "Discord payload preview:\n"
        + str(payload)
        + "\n",
        encoding="utf-8",
    )
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
