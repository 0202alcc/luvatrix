#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from tools.perf.run_suite import run_suite


DEFAULT_SEEDS = [1337, 2024, 7, 11, 42, 314, 9001, 2718]


def _scenario_digest(result: dict[str, Any]) -> str:
    payload = {
        "compose_modes": result.get("compose_modes", []),
        "dirty_counts": result.get("dirty_counts", []),
        "copy_counts": result.get("copy_counts", []),
        "copy_bytes": result.get("copy_bytes", []),
        "event_order_digest_trace": result.get("event_order_digest_trace", []),
        "event_poll_trace": result.get("event_poll_trace", []),
        "events_processed": result.get("events_processed", []),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _revision_digest(result: dict[str, Any]) -> str:
    payload = {
        "copy_counts": result.get("copy_counts", []),
        "copy_bytes": result.get("copy_bytes", []),
        "dirty_counts": result.get("dirty_counts", []),
        "pending_after_trace": result.get("pending_after_trace", []),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_matrix(*, seeds: list[int], runs_per_seed: int, samples: int, width: int, height: int, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = out_dir / "replay_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    try:
        commit_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        commit_sha = "unknown"

    rows: list[dict[str, Any]] = []
    mismatch_count = 0

    for seed in seeds:
        baseline_event_digest: str | None = None
        baseline_revision_digest: str | None = None
        for run_idx in range(1, runs_per_seed + 1):
            suite = run_suite("all_interactive", samples=samples, width=width, height=height)
            scenarios = suite.get("scenarios", {})
            if not isinstance(scenarios, dict):
                raise ValueError("run_suite output missing scenarios map")

            digest_material: dict[str, dict[str, str]] = {}
            for scenario_name in ("idle", "scroll", "drag", "resize_stress"):
                scenario_payload = scenarios.get(scenario_name, {})
                if not isinstance(scenario_payload, dict):
                    raise ValueError(f"missing scenario payload: {scenario_name}")
                result = scenario_payload.get("result", {})
                if not isinstance(result, dict):
                    raise ValueError(f"missing scenario result: {scenario_name}")
                digest_material[scenario_name] = {
                    "event_order_digest": _scenario_digest(result),
                    "revision_sequence_digest": _revision_digest(result),
                }

            event_digest = hashlib.sha256(
                "".join(v["event_order_digest"] for _, v in sorted(digest_material.items())).encode("utf-8")
            ).hexdigest()
            revision_digest = hashlib.sha256(
                "".join(v["revision_sequence_digest"] for _, v in sorted(digest_material.items())).encode("utf-8")
            ).hexdigest()

            if baseline_event_digest is None:
                baseline_event_digest = event_digest
                baseline_revision_digest = revision_digest
            mismatch = bool(event_digest != baseline_event_digest or revision_digest != baseline_revision_digest)
            if mismatch:
                mismatch_count += 1

            run_log = {
                "seed": seed,
                "run_index": run_idx,
                "samples": samples,
                "matrix": {"width": width, "height": height},
                "digest_material": digest_material,
                "event_order_digest": event_digest,
                "revision_sequence_digest": revision_digest,
                "mismatch_against_seed_baseline": mismatch,
                "provenance": {
                    "command": "tools/perf/build_p026_replay_matrix.py",
                    "commit_sha": commit_sha,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "seed_list": [seed],
                    "run_counts": {"per_seed": runs_per_seed},
                },
            }
            log_path = logs_dir / f"seed_{seed}_run_{run_idx:02d}.json"
            log_path.write_text(json.dumps(run_log, indent=2, sort_keys=True), encoding="utf-8")
            rows.append(
                {
                    "seed": seed,
                    "run_index": run_idx,
                    "event_order_digest": event_digest,
                    "revision_sequence_digest": revision_digest,
                    "log_path": str(log_path),
                    "mismatch": mismatch,
                }
            )

    matrix = {
        "milestone_id": "P-026",
        "seed_count_required": 8,
        "seed_count_observed": len(seeds),
        "runs_per_seed_required": 10,
        "runs_per_seed_observed": runs_per_seed,
        "mismatch_count": mismatch_count,
        "rows": rows,
        "provenance": {
            "command": "tools/perf/build_p026_replay_matrix.py",
            "commit_sha": commit_sha,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "seed_list": seeds,
            "run_counts": {"per_seed": runs_per_seed, "total_runs": len(seeds) * runs_per_seed},
            "raw_file_refs": [str(r["log_path"]) for r in rows],
        },
    }
    out_path = out_dir / "determinism_replay_matrix.json"
    out_path.write_text(json.dumps(matrix, indent=2, sort_keys=True), encoding="utf-8")
    return matrix


def main() -> int:
    parser = argparse.ArgumentParser(description="Build provenance-backed P-026 determinism replay matrix.")
    parser.add_argument("--seeds", default=",".join(str(s) for s in DEFAULT_SEEDS))
    parser.add_argument("--runs-per-seed", type=int, default=10)
    parser.add_argument("--samples", type=int, default=80)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--out-dir", default="artifacts/perf/closeout")
    args = parser.parse_args()

    seeds = [int(part.strip()) for part in str(args.seeds).split(",") if part.strip()]
    matrix = build_matrix(
        seeds=seeds,
        runs_per_seed=max(1, int(args.runs_per_seed)),
        samples=max(1, int(args.samples)),
        width=max(64, int(args.width)),
        height=max(64, int(args.height)),
        out_dir=Path(args.out_dir).resolve(),
    )
    print(json.dumps(matrix, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
