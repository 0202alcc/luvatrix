from __future__ import annotations

import argparse
import json
from pathlib import Path


def validate(
    *,
    measured_summary_path: Path,
    determinism_matrix_path: Path,
) -> list[str]:
    errors: list[str] = []
    measured = json.loads(measured_summary_path.read_text(encoding="utf-8"))
    matrix = json.loads(determinism_matrix_path.read_text(encoding="utf-8"))

    if measured.get("milestone_id") != "P-026":
        errors.append("measured summary milestone_id must be P-026")

    policy = measured.get("policy_verdict", {})
    if not isinstance(policy, dict) or policy.get("pass") is not True:
        errors.append("policy_verdict.pass must be true")

    required = set(["scroll", "horizontal_pan", "drag_heavy", "mixed_burst", "sensor_overlay", "resize_overlap_incremental_required", "input_burst"])
    required_scenarios = set(policy.get("required_scenarios", [])) if isinstance(policy.get("required_scenarios"), list) else set()
    missing = sorted(required.difference(required_scenarios))
    if missing:
        errors.append(f"missing required scenarios in policy_verdict: {', '.join(missing)}")

    scenario_metrics = measured.get("scenario_metrics", {})
    if not isinstance(scenario_metrics, dict):
        errors.append("scenario_metrics must be an object")
    else:
        for scenario in required:
            node = scenario_metrics.get(scenario)
            if not isinstance(node, dict) or node.get("pass") is not True:
                errors.append(f"scenario {scenario} must have pass=true")

    if matrix.get("milestone_id") != "P-026":
        errors.append("determinism matrix milestone_id must be P-026")
    if int(matrix.get("mismatch_count", -1)) != 0:
        errors.append("determinism mismatch_count must be 0")
    if matrix.get("cross_seed_trace_fingerprints_distinct") is not True:
        errors.append("cross_seed_trace_fingerprints_distinct must be true")

    rows = matrix.get("rows")
    if not isinstance(rows, list) or len(rows) == 0:
        errors.append("determinism rows must be non-empty")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="CI-portable guard for P-026 non-regression evidence")
    parser.add_argument(
        "--measured-summary",
        type=Path,
        default=Path("artifacts/perf/closeout/measured_summary.json"),
    )
    parser.add_argument(
        "--determinism-matrix",
        type=Path,
        default=Path("artifacts/perf/closeout/determinism_replay_matrix.json"),
    )
    args = parser.parse_args()

    errors = validate(
        measured_summary_path=args.measured_summary,
        determinism_matrix_path=args.determinism_matrix,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print("PASS: p026 non-regression ci guard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
