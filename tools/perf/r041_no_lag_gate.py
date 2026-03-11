from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def evaluate_no_lag_gate(*, perf_summary: dict[str, Any], baseline_summary: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    drag = perf_summary.get("scenarios", {}).get("drag", {})
    result = drag.get("result", {}) if isinstance(drag, dict) else {}
    if not isinstance(result, dict):
        raise ValueError("missing drag result payload")
    thresholds = contract.get("thresholds", {})
    if not isinstance(thresholds, dict):
        thresholds = {}
    checks: dict[str, bool] = {}
    checks["deterministic"] = bool(drag.get("deterministic", False))
    checks["no_full_frame_drag"] = float(result.get("full_present_pct", 100.0)) <= float(thresholds.get("full_present_pct_max", 8.0))
    checks["frame_budget"] = float(result.get("p95_frame_total_ms", 9999.0)) <= float(thresholds.get("p95_frame_total_ms_max", 16.7))
    checks["jitter_budget"] = float(result.get("jitter_ms", 9999.0)) <= float(thresholds.get("jitter_ms_max", 5.5))
    checks["input_to_present_budget"] = float(result.get("p95_input_to_present_ms", 9999.0)) <= float(
        thresholds.get("p95_input_to_present_ms_max", 33.4)
    )
    baseline_dirty = float(baseline_summary.get("p95_dirty_area_ratio", 9999.0))
    current_dirty = float(result.get("p95_dirty_area_ratio", 9999.0))
    checks["dirty_rect_efficiency_improved"] = current_dirty <= baseline_dirty
    blockers = [name for name, ok in checks.items() if not ok]
    return {
        "decision": "GO" if not blockers else "NO-GO",
        "checks": checks,
        "blockers": blockers,
        "metrics": {
            "p95_frame_total_ms": float(result.get("p95_frame_total_ms", 0.0)),
            "jitter_ms": float(result.get("jitter_ms", 0.0)),
            "p95_input_to_present_ms": float(result.get("p95_input_to_present_ms", 0.0)),
            "full_present_pct": float(result.get("full_present_pct", 0.0)),
            "p95_dirty_area_ratio": current_dirty,
            "baseline_p95_dirty_area_ratio": baseline_dirty,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="R-041 no-lag gate")
    parser.add_argument("--perf", required=True, help="Path to drag perf suite output JSON")
    parser.add_argument("--baseline", required=True, help="Path to baseline drag summary JSON")
    parser.add_argument("--contract", default="tools/perf/r041_drag_contract.json", help="Path to R-041 contract JSON")
    parser.add_argument("--out", default="", help="Optional output path for gate result JSON")
    args = parser.parse_args()

    result = evaluate_no_lag_gate(
        perf_summary=_load_json(args.perf),
        baseline_summary=_load_json(args.baseline),
        contract=_load_json(args.contract),
    )
    encoded = json.dumps(result, indent=2, sort_keys=True)
    print(encoded)
    out = str(args.out).strip()
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(encoded + "\n", encoding="utf-8")
    return 0 if result.get("decision") == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
