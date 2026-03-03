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


def _check_threshold(
    *,
    scenario: str,
    observed: dict[str, Any],
    thresholds: dict[str, Any],
    errors: list[str],
) -> None:
    deterministic = bool(observed.get("deterministic", False))
    if not deterministic:
        errors.append(f"{scenario}: deterministic replay check failed")
    result = observed.get("result", {})
    if not isinstance(result, dict):
        errors.append(f"{scenario}: missing result payload")
        return
    checks = (
        ("p95_frame_total_ms", float),
        ("jitter_ms", float),
        ("p95_copy_bytes", int),
        ("p95_copy_count", int),
        ("p95_copy_pack_ms", float),
        ("p95_copy_map_ms", float),
        ("p95_copy_memcpy_ms", float),
    )
    for key, cast in checks:
        limit = thresholds.get(key)
        if limit is None:
            continue
        value = cast(result.get(key, 0))
        if value > cast(limit):
            errors.append(f"{scenario}: {key}={value} exceeds threshold={limit}")


def assert_thresholds(suite: str, baseline: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    scenarios = baseline.get("scenarios", {})
    if not isinstance(scenarios, dict):
        raise ValueError("baseline missing scenarios")
    scenario_thresholds = contract.get("scenarios", {})
    if not isinstance(scenario_thresholds, dict):
        raise ValueError("contract missing scenarios")

    errors: list[str] = []
    for name, observed in scenarios.items():
        if not isinstance(observed, dict):
            errors.append(f"{name}: malformed scenario payload")
            continue
        thresholds = scenario_thresholds.get(name)
        if not isinstance(thresholds, dict):
            errors.append(f"{name}: missing threshold contract")
            continue
        _check_threshold(
            scenario=str(name),
            observed=observed,
            thresholds=thresholds,
            errors=errors,
        )
    return {"suite": suite, "passed": len(errors) == 0, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description="P-021 baseline threshold assertions")
    parser.add_argument("--suite", default="baseline_contract")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--contract", default="tools/perf/baseline_contract.json")
    args = parser.parse_args()

    baseline = _load_json(args.baseline)
    contract = _load_json(args.contract)
    summary = assert_thresholds(str(args.suite), baseline, contract)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if bool(summary.get("passed", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
