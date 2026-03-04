#!/usr/bin/env python3
"""Validate closeout evidence bundle presence, hashes, and threshold claims."""

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
        "artifacts/perf/closeout/summary.json",
        "artifacts/perf/closeout/determinism_replay_seed1337.json",
        "artifacts/perf/closeout/incremental_present_matrix_seed1337.json",
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

    summary = _load_json(CLOSEOUT_ROOT / "summary.json")
    checks = summary.get("checks", {})
    if not isinstance(checks, dict):
        errors.append("summary.checks must be an object")
    else:
        for key in (
            "frame_p50_pass",
            "frame_p95_pass",
            "frame_p99_present",
            "input_p95_pass",
            "input_p99_present",
            "incremental_scroll_pass",
            "incremental_drag_pass",
            "resize_recovery_present",
            "dropped_frame_pass",
        ):
            if checks.get(key) is not True:
                errors.append(f"summary check failed: {key}")

    determinism = _load_json(CLOSEOUT_ROOT / "determinism_replay_seed1337.json")
    if int(determinism.get("seed_count_observed", 0)) < int(determinism.get("seed_count_required", 0)):
        errors.append("determinism seed coverage below required count")
    if int(determinism.get("runs_per_seed_observed", 0)) < int(determinism.get("runs_per_seed_required", 0)):
        errors.append("determinism runs/seed below required count")
    if int(determinism.get("mismatch_count", 1)) != 0:
        errors.append("determinism mismatch count must be zero")
    invariants = determinism.get("invariants", {})
    if not isinstance(invariants, dict):
        errors.append("determinism invariants missing")
    else:
        for key in ("snapshot_immutability", "no_torn_reads", "revision_stability"):
            if invariants.get(key) is not True:
                errors.append(f"determinism invariant failed: {key}")

    incremental = _load_json(CLOSEOUT_ROOT / "incremental_present_matrix_seed1337.json")
    missing_scenarios = incremental.get("missing_required_scenarios", [])
    if isinstance(missing_scenarios, list) and missing_scenarios:
        errors.append(f"incremental matrix missing required scenarios: {', '.join(missing_scenarios)}")
    observed = incremental.get("observed", {})
    targets = incremental.get("targets", {})
    if not isinstance(observed, dict) or not isinstance(targets, dict):
        errors.append("incremental matrix observed/targets must be objects")
    else:
        for key, target in targets.items():
            if not isinstance(target, (float, int)):
                errors.append(f"incremental target malformed: {key}")
                continue
            if key not in observed:
                errors.append(f"incremental observed missing: {key}")
                continue
            value = observed.get(key)
            if not isinstance(value, (float, int)):
                errors.append(f"incremental observed malformed: {key}")
                continue
            if float(value) < float(target):
                errors.append(f"incremental target miss: {key} observed={value} target={target}")

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
