#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_SCENARIOS = (
    "scroll",
    "horizontal_pan",
    "drag_heavy",
    "mixed_burst",
    "sensor_overlay",
    "resize_stress_fullframe_allowed",
    "resize_overlap_incremental_required",
    "input_burst",
    "sensor_polling",
)
OVERLAP_INCREMENTAL_TARGET_PCT = 75.0

REQUIRED_MEASURED_FIELDS = (
    "p50_frame_total_ms",
    "p95_frame_total_ms",
    "p99_frame_total_ms",
    "dropped_frame_ratio",
)

REQUIRED_POLICY_TARGETS: dict[str, float] = {
    "scroll": 95.0,
    "horizontal_pan": 92.0,
    "drag_heavy": 85.0,
    "mixed_burst": 88.0,
    "sensor_overlay": 90.0,
    "resize_overlap_incremental_required": 75.0,
    "input_burst": 85.0,
}
FULL_PCT_CAP = 15.0
CONSECUTIVE_FULL_CAP = 8


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def _require_number(node: dict[str, Any], key: str) -> float:
    if key not in node:
        raise ValueError(f"missing measured field: {key}")
    value = node.get(key)
    if not isinstance(value, (int, float)):
        raise ValueError(f"measured field not numeric: {key}")
    return float(value)


def _max_consecutive_full_frame(compose_modes: list[Any]) -> int:
    max_seen = 0
    streak = 0
    for mode in compose_modes:
        if str(mode) == "full_frame":
            streak += 1
            if streak > max_seen:
                max_seen = streak
        else:
            streak = 0
    return max_seen


def _find_exception_node(scenario_node: dict[str, Any], result_node: dict[str, Any]) -> dict[str, Any] | None:
    for candidate in (
        scenario_node.get("exception"),
        scenario_node.get("policy_exception"),
        result_node.get("exception"),
        result_node.get("policy_exception"),
    ):
        if isinstance(candidate, dict):
            return candidate
    return None


def _exception_applied(exception_node: dict[str, Any] | None) -> bool:
    if exception_node is None:
        return False
    if exception_node.get("approved") is not True:
        return False
    reason = exception_node.get("reason", exception_node.get("rationale", exception_node.get("note")))
    approver = exception_node.get("approver", exception_node.get("approved_by"))
    ticket = exception_node.get("ticket", exception_node.get("ticket_id", exception_node.get("incident_id")))
    return (
        isinstance(reason, str)
        and bool(reason.strip())
        and isinstance(approver, str)
        and bool(approver.strip())
        and isinstance(ticket, str)
        and bool(ticket.strip())
    )


def build_measured_summary(raw: dict[str, Any]) -> dict[str, Any]:
    scenarios = raw.get("scenarios")
    if not isinstance(scenarios, dict):
        raise ValueError("raw suite missing scenarios object")

    missing = [name for name in REQUIRED_SCENARIOS if name not in scenarios]
    if missing:
        raise ValueError("required scenarios missing: " + ", ".join(missing))

    provenance = raw.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("raw suite missing provenance object")
    for field in ("command", "commit_sha", "timestamp_utc", "seed_list", "run_count"):
        if field not in provenance:
            raise ValueError(f"raw suite missing provenance field: {field}")

    scenario_metrics: dict[str, dict[str, float | int | bool | None]] = {}
    scenario_policy_verdicts: dict[str, dict[str, float | int | bool]] = {}
    for name in REQUIRED_SCENARIOS:
        payload = scenarios.get(name)
        if not isinstance(payload, dict):
            raise ValueError(f"scenario payload malformed: {name}")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ValueError(f"scenario result malformed: {name}")

        if name == "sensor_polling":
            cycle_p95 = _require_number(result, "cycle_cost_p95_ms")
            scenario_metrics[name] = {
                "cycle_cost_p95_ms": cycle_p95,
                "p50_frame_total_ms": None,
                "p95_frame_total_ms": None,
                "p99_frame_total_ms": None,
                "dropped_frame_ratio": None,
                "p95_input_to_present_ms": None,
                "p99_input_to_present_ms": None,
                "resize_recovery_sec": None,
            }
            continue

        metrics: dict[str, float | int | bool | None] = {}
        for field in REQUIRED_MEASURED_FIELDS:
            metrics[field] = _require_number(result, field)
        metrics["p95_input_to_present_ms"] = _require_number(result, "p95_input_to_present_ms")
        metrics["p99_input_to_present_ms"] = _require_number(result, "p99_input_to_present_ms")
        resize_recovery = result.get("resize_recovery_sec")
        if name == "resize_stress_fullframe_allowed":
            if not isinstance(resize_recovery, (int, float)):
                raise ValueError("resize_stress_fullframe_allowed missing measured resize_recovery_sec")
            metrics["resize_recovery_sec"] = float(resize_recovery)
        else:
            metrics["resize_recovery_sec"] = float(resize_recovery) if isinstance(resize_recovery, (int, float)) else None
        if name == "resize_overlap_incremental_required":
            incremental_pct = _require_number(result, "incremental_present_pct")
            if incremental_pct < OVERLAP_INCREMENTAL_TARGET_PCT:
                raise ValueError(
                    "resize_overlap_incremental_required incremental_present_pct below policy threshold: "
                    f"{incremental_pct:.3f} < {OVERLAP_INCREMENTAL_TARGET_PCT:.1f}"
                )
            metrics["incremental_present_pct"] = incremental_pct
        if name in REQUIRED_POLICY_TARGETS:
            observed_incremental = _require_number(result, "incremental_present_pct")
            observed_full = _require_number(result, "full_present_pct")
            compose_modes = result.get("compose_modes")
            if not isinstance(compose_modes, list):
                raise ValueError(f"{name} missing measured policy field: compose_modes")
            max_consecutive_full = _max_consecutive_full_frame(compose_modes)
            exception_applied = _exception_applied(_find_exception_node(payload, result))
            target_incremental = float(REQUIRED_POLICY_TARGETS[name])
            policy_pass = (
                (observed_incremental >= target_incremental or exception_applied)
                and observed_full <= FULL_PCT_CAP
                and max_consecutive_full <= CONSECUTIVE_FULL_CAP
            )
            policy_verdict = {
                "observed_incremental_pct": observed_incremental,
                "target_incremental_pct": target_incremental,
                "observed_full_pct": observed_full,
                "full_pct_cap": FULL_PCT_CAP,
                "max_consecutive_full_frame": max_consecutive_full,
                "consecutive_full_cap": CONSECUTIVE_FULL_CAP,
                "exception_applied": exception_applied,
                "pass": policy_pass,
            }
            metrics.update(policy_verdict)
            scenario_policy_verdicts[name] = policy_verdict
        scenario_metrics[name] = metrics

    frame_scenarios = [s for s in REQUIRED_SCENARIOS if s != "sensor_polling"]
    frame_p50 = max(float(scenario_metrics[s]["p50_frame_total_ms"]) for s in frame_scenarios)
    frame_p95 = max(float(scenario_metrics[s]["p95_frame_total_ms"]) for s in frame_scenarios)
    frame_p99 = max(float(scenario_metrics[s]["p99_frame_total_ms"]) for s in frame_scenarios)
    input_p95 = max(float(scenario_metrics[s]["p95_input_to_present_ms"]) for s in frame_scenarios)
    input_p99 = max(float(scenario_metrics[s]["p99_input_to_present_ms"]) for s in frame_scenarios)
    dropped_ratio = max(float(scenario_metrics[s]["dropped_frame_ratio"]) for s in frame_scenarios)
    resize_recovery = float(scenario_metrics["resize_stress_fullframe_allowed"]["resize_recovery_sec"])

    policy_required_scenarios = list(REQUIRED_POLICY_TARGETS.keys())
    missing_policy = [name for name in policy_required_scenarios if name not in scenario_policy_verdicts]
    if missing_policy:
        raise ValueError("required policy verdict data missing: " + ", ".join(missing_policy))
    policy_pass = all(bool(scenario_policy_verdicts[name]["pass"]) for name in policy_required_scenarios)

    return {
        "milestone_id": "P-026",
        "suite": "closeout_required",
        "summary_type": "measured_only",
        "required_scenarios": list(REQUIRED_SCENARIOS),
        "metrics": {
            "frame_time_ms": {"p50": frame_p50, "p95": frame_p95, "p99": frame_p99},
            "input_to_present_ms": {"p95": input_p95, "p99": input_p99},
            "dropped_frame_ratio": dropped_ratio,
            "resize_recovery_sec": resize_recovery,
            "sensor_cycle_p95_ms": float(scenario_metrics["sensor_polling"]["cycle_cost_p95_ms"]),
        },
        "scenario_metrics": scenario_metrics,
        "policy_verdict": {
            "required_scenarios": policy_required_scenarios,
            "full_pct_cap": FULL_PCT_CAP,
            "consecutive_full_cap": CONSECUTIVE_FULL_CAP,
            "pass": policy_pass,
        },
        "provenance": {
            "raw_artifact": "artifacts/perf/closeout/raw_closeout_required.json",
            "measurement_policy": "no synthetic, derived, estimated, or normalized fallbacks",
            "resize_overlap_incremental_threshold_pct": OVERLAP_INCREMENTAL_TARGET_PCT,
            "raw_command": provenance.get("command"),
            "raw_commit_sha": provenance.get("commit_sha"),
            "raw_timestamp_utc": provenance.get("timestamp_utc"),
            "seed_list": provenance.get("seed_list"),
            "run_count": provenance.get("run_count"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build measured-only P-026 summary from raw closeout runs.")
    parser.add_argument("--raw", default="artifacts/perf/closeout/raw_closeout_required.json")
    parser.add_argument("--out", default="artifacts/perf/closeout/measured_summary.json")
    args = parser.parse_args()

    raw_path = Path(args.raw).resolve()
    out_path = Path(args.out).resolve()
    raw = _load_json(raw_path)
    summary = build_measured_summary(raw)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
