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


def _as_float(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if value is None:
        return 0.0
    return float(value)


def _ratio_score(value: float, threshold: float, *, higher_is_better: bool) -> float:
    if higher_is_better:
        if threshold <= 0.0:
            return 100.0
        ratio = value / threshold
    else:
        if value <= 0.0:
            return 100.0
        ratio = threshold / value
    return max(0.0, min(100.0, ratio * 100.0))


def evaluate_go_no_go(*, perf_summary: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    scenarios = perf_summary.get("scenarios", {})
    if not isinstance(scenarios, dict):
        raise ValueError("perf summary missing scenarios payload")

    scenario_name = str(contract.get("scenario", "drag"))
    scenario_node = scenarios.get(scenario_name, {})
    if not isinstance(scenario_node, dict):
        raise ValueError(f"missing scenario node: {scenario_name}")
    result = scenario_node.get("result", {})
    if not isinstance(result, dict):
        raise ValueError(f"missing result payload for scenario: {scenario_name}")

    deterministic = bool(scenario_node.get("deterministic", False))
    thresholds = contract.get("thresholds", {})
    if not isinstance(thresholds, dict):
        raise ValueError("contract missing thresholds object")
    weights = contract.get("weights", {})
    if not isinstance(weights, dict):
        raise ValueError("contract missing weights object")

    p95_frame_total_ms = _as_float(result, "p95_frame_total_ms")
    p99_frame_total_ms = _as_float(result, "p99_frame_total_ms")
    jitter_ms = _as_float(result, "jitter_ms")
    p95_input_to_present_ms = _as_float(result, "p95_input_to_present_ms")
    full_present_pct = _as_float(result, "full_present_pct")
    p95_dirty_area_ratio = _as_float(result, "p95_dirty_area_ratio")
    incremental_present_pct = _as_float(result, "incremental_present_pct")

    metric_scores = {
        "frame_latency": _ratio_score(
            p95_frame_total_ms,
            float(thresholds.get("p95_frame_total_ms_max", 16.7)),
            higher_is_better=False,
        ),
        "jitter": _ratio_score(
            jitter_ms,
            float(thresholds.get("jitter_ms_max", 5.5)),
            higher_is_better=False,
        ),
        "input_to_present": _ratio_score(
            p95_input_to_present_ms,
            float(thresholds.get("p95_input_to_present_ms_max", 33.4)),
            higher_is_better=False,
        ),
        "dirty_rect_efficiency": _ratio_score(
            p95_dirty_area_ratio,
            float(thresholds.get("p95_dirty_area_ratio_max", 0.42)),
            higher_is_better=False,
        ),
        "incremental_present": _ratio_score(
            100.0 - full_present_pct,
            100.0 - float(thresholds.get("full_present_pct_max", 8.0)),
            higher_is_better=True,
        ),
    }

    weighted_score = 0.0
    for key, score in metric_scores.items():
        weighted_score += float(weights.get(key, 0.0)) * float(score)

    blockers: list[str] = []
    if not deterministic:
        blockers.append("deterministic replay check failed for drag scenario")
    if full_present_pct > 20.0:
        blockers.append(f"full_present_pct hard cap exceeded: {full_present_pct:.3f} > 20.0")
    if p95_frame_total_ms > 22.0:
        blockers.append(f"p95_frame_total_ms hard cap exceeded: {p95_frame_total_ms:.3f} > 22.0")
    if p95_input_to_present_ms > 45.0:
        blockers.append(f"p95_input_to_present_ms hard cap exceeded: {p95_input_to_present_ms:.3f} > 45.0")
    if p99_frame_total_ms > float(thresholds.get("p99_frame_total_ms_max", 22.0)):
        blockers.append(
            "p99_frame_total_ms threshold exceeded: "
            f"{p99_frame_total_ms:.3f} > {float(thresholds.get('p99_frame_total_ms_max', 22.0)):.3f}"
        )

    go_threshold = float(contract.get("go_threshold", 90.0))
    go = (len(blockers) == 0) and (weighted_score >= go_threshold)
    decision = "GO" if go else "NO-GO"

    return {
        "milestone_id": str(contract.get("milestone_id", "R-041")),
        "scenario": scenario_name,
        "decision": decision,
        "go_threshold": go_threshold,
        "score": float(round(weighted_score, 3)),
        "deterministic": deterministic,
        "metrics": {
            "p95_frame_total_ms": p95_frame_total_ms,
            "p99_frame_total_ms": p99_frame_total_ms,
            "jitter_ms": jitter_ms,
            "p95_input_to_present_ms": p95_input_to_present_ms,
            "full_present_pct": full_present_pct,
            "incremental_present_pct": incremental_present_pct,
            "p95_dirty_area_ratio": p95_dirty_area_ratio,
        },
        "metric_scores": {k: float(round(v, 3)) for k, v in metric_scores.items()},
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="R-041 drag scenario GO/NO-GO harness")
    parser.add_argument("--perf", required=True, help="Path to perf suite output JSON")
    parser.add_argument("--contract", default="tools/perf/r041_drag_contract.json", help="Path to contract JSON")
    parser.add_argument("--out", default="", help="Optional output JSON path")
    args = parser.parse_args()

    perf_summary = _load_json(args.perf)
    contract = _load_json(args.contract)
    result = evaluate_go_no_go(perf_summary=perf_summary, contract=contract)
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
