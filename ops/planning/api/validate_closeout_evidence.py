#!/usr/bin/env python3
"""Validate closeout evidence bundle presence, hashes, and provenance integrity."""

from __future__ import annotations

import argparse
import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any


ROOT = Path(".").resolve()
PLANNING_ROOT = ROOT / "ops" / "planning"
CLOSEOUT_ROOT = ROOT / "artifacts" / "perf" / "closeout"


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(131072), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def _extract_manifest(closeout_md: Path) -> dict[str, str]:
    text = closeout_md.read_text(encoding="utf-8")
    match = re.search(
        r"```json\s*\n(?P<body>\{[\s\S]*?\})\n```",
        text,
        flags=re.MULTILINE,
    )
    if not match:
        raise ValueError("closeout packet missing json manifest block")
    payload = json.loads(match.group("body"))
    if not isinstance(payload, dict):
        raise ValueError("manifest block must decode to object")
    artifacts = payload.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise ValueError("manifest artifacts must be a list")
    out: dict[str, str] = {}
    for node in artifacts:
        if not isinstance(node, dict):
            raise ValueError("manifest artifact entries must be objects")
        path = node.get("path")
        digest = node.get("sha256")
        if not isinstance(path, str) or not isinstance(digest, str):
            raise ValueError("manifest artifact entry missing path/sha256")
        out[path] = digest
    return out


def validate(milestone_id: str) -> tuple[bool, list[str]]:
    errors: list[str] = []
    closeout_md = PLANNING_ROOT / "closeout" / f"{milestone_id.lower()}_closeout.md"
    if not closeout_md.exists():
        return False, [f"missing closeout file: {closeout_md}"]

    required_files = {
        "artifacts/perf/closeout/raw_closeout_required.json",
        "artifacts/perf/closeout/measured_summary.json",
        "artifacts/perf/closeout/determinism_replay_matrix.json",
    }
    try:
        manifest = _extract_manifest(closeout_md)
    except Exception as exc:  # pragma: no cover - defensive parse reporting
        return False, [f"manifest parse error: {exc}"]

    for rel in sorted(required_files):
        path = ROOT / rel
        if not path.exists():
            errors.append(f"missing artifact: {rel}")
            continue
        expected = manifest.get(rel)
        if expected is None:
            errors.append(f"manifest missing artifact hash entry: {rel}")
            continue
        actual = _hash_file(path)
        if actual != expected:
            errors.append(f"hash mismatch: {rel} expected={expected} actual={actual}")

    raw = _load_json(CLOSEOUT_ROOT / "raw_closeout_required.json")
    raw_provenance = raw.get("provenance", {})
    if not isinstance(raw_provenance, dict):
        errors.append("raw artifact missing provenance object")
    else:
        for field in ("command", "commit_sha", "timestamp_utc", "seed_list", "run_count"):
            if field not in raw_provenance:
                errors.append(f"raw provenance missing field: {field}")

    summary = _load_json(CLOSEOUT_ROOT / "measured_summary.json")
    if summary.get("summary_type") != "measured_only":
        errors.append("measured summary must declare summary_type=measured_only")
    summary_metrics = summary.get("metrics", {})
    if not isinstance(summary_metrics, dict):
        errors.append("measured summary metrics must be an object")
    else:
        frame = summary_metrics.get("frame_time_ms", {})
        if not isinstance(frame, dict):
            errors.append("measured summary missing frame_time_ms object")
        else:
            for key in ("p50", "p95", "p99"):
                if not isinstance(frame.get(key), (int, float)):
                    errors.append(f"measured frame metric missing/non-numeric: {key}")
        input_latency = summary_metrics.get("input_to_present_ms", {})
        if not isinstance(input_latency, dict):
            errors.append("measured summary missing input_to_present_ms object")
        else:
            for key in ("p95", "p99"):
                if not isinstance(input_latency.get(key), (int, float)):
                    errors.append(f"measured input metric missing/non-numeric: {key}")
        if not isinstance(summary_metrics.get("resize_recovery_sec"), (int, float)):
            errors.append("measured resize_recovery_sec missing/non-numeric")
        if not isinstance(summary_metrics.get("dropped_frame_ratio"), (int, float)):
            errors.append("measured dropped_frame_ratio missing/non-numeric")

    scenario_metrics = summary.get("scenario_metrics", {})
    if not isinstance(scenario_metrics, dict):
        errors.append("measured summary scenario_metrics must be an object")
    else:
        for scenario in ("scroll", "horizontal_pan", "drag_heavy", "mixed_burst", "sensor_overlay", "resize_stress", "input_burst"):
            node = scenario_metrics.get(scenario)
            if not isinstance(node, dict):
                errors.append(f"required measured scenario missing: {scenario}")
                continue
            for key in ("p50_frame_total_ms", "p95_frame_total_ms", "p99_frame_total_ms", "dropped_frame_ratio"):
                if not isinstance(node.get(key), (int, float)):
                    errors.append(f"{scenario} missing measured field: {key}")
            for key in ("p95_input_to_present_ms", "p99_input_to_present_ms"):
                if not isinstance(node.get(key), (int, float)):
                    errors.append(f"{scenario} missing measured field: {key}")
        resize_node = scenario_metrics.get("resize_stress")
        if isinstance(resize_node, dict) and not isinstance(resize_node.get("resize_recovery_sec"), (int, float)):
            errors.append("resize_stress missing measured field: resize_recovery_sec")

    summary_provenance = summary.get("provenance", {})
    if not isinstance(summary_provenance, dict):
        errors.append("measured summary missing provenance object")
    else:
        for field in ("raw_artifact", "raw_command", "raw_commit_sha", "raw_timestamp_utc", "seed_list", "run_count"):
            if field not in summary_provenance:
                errors.append(f"measured summary provenance missing field: {field}")
    if isinstance(raw_provenance, dict) and isinstance(summary_provenance, dict):
        if summary_provenance.get("raw_commit_sha") != raw_provenance.get("commit_sha"):
            errors.append("measured summary provenance commit_sha does not match raw artifact provenance")

    determinism = _load_json(CLOSEOUT_ROOT / "determinism_replay_matrix.json")
    if int(determinism.get("seed_count_observed", 0)) < int(determinism.get("seed_count_required", 0)):
        errors.append("determinism seed coverage below required count")
    if int(determinism.get("runs_per_seed_observed", 0)) < int(determinism.get("runs_per_seed_required", 0)):
        errors.append("determinism runs/seed below required count")
    if int(determinism.get("mismatch_count", 1)) != 0:
        errors.append("determinism mismatch count must be zero")
    rows = determinism.get("rows", [])
    if not isinstance(rows, list) or not rows:
        errors.append("determinism matrix rows missing")
    else:
        for row in rows:
            if not isinstance(row, dict):
                errors.append("determinism row malformed")
                continue
            log_path_raw = row.get("log_path")
            if not isinstance(log_path_raw, str):
                errors.append("determinism row missing log_path")
                continue
            log_path = Path(log_path_raw)
            if not log_path.is_absolute():
                log_path = ROOT / log_path_raw
            if not log_path.exists():
                errors.append(f"determinism log missing: {log_path_raw}")
                continue
            log_payload = _load_json(log_path)
            if log_payload.get("event_order_digest") != row.get("event_order_digest"):
                errors.append(f"determinism digest mismatch for log: {log_path_raw}")
            if log_payload.get("revision_sequence_digest") != row.get("revision_sequence_digest"):
                errors.append(f"determinism revision digest mismatch for log: {log_path_raw}")
            log_provenance = log_payload.get("provenance", {})
            if not isinstance(log_provenance, dict):
                errors.append(f"determinism log provenance missing: {log_path_raw}")
            else:
                for field in ("command", "commit_sha", "timestamp_utc", "seed_list", "run_counts"):
                    if field not in log_provenance:
                        errors.append(f"determinism log provenance missing field {field}: {log_path_raw}")

    det_provenance = determinism.get("provenance", {})
    if not isinstance(det_provenance, dict):
        errors.append("determinism matrix missing provenance object")
    else:
        for field in ("command", "commit_sha", "timestamp_utc", "seed_list", "run_counts", "raw_file_refs"):
            if field not in det_provenance:
                errors.append(f"determinism matrix provenance missing field: {field}")

    return (len(errors) == 0), errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate closeout perf evidence for milestone packet.")
    parser.add_argument("--milestone-id", required=True)
    args = parser.parse_args()

    ok, errors = validate(str(args.milestone_id))
    if ok:
        print("validation: PASS (evidence)")
        return 0
    print("validation: FAIL (evidence)")
    for err in errors:
        print(f"- {err}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
