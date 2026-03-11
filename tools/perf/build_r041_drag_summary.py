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


def build_summary(perf_summary: dict[str, Any]) -> dict[str, Any]:
    scenarios = perf_summary.get("scenarios", {})
    if not isinstance(scenarios, dict):
        raise ValueError("perf summary missing scenarios object")
    drag_node = scenarios.get("drag", {})
    if not isinstance(drag_node, dict):
        raise ValueError("perf summary missing drag scenario")
    result = drag_node.get("result", {})
    if not isinstance(result, dict):
        raise ValueError("drag scenario missing result payload")
    hot_path = result.get("hot_path_p95_ms", {})
    if not isinstance(hot_path, dict):
        hot_path = {}
    shares = result.get("hot_path_share_pct", {})
    if not isinstance(shares, dict):
        shares = {}
    top_stage = max(hot_path.items(), key=lambda kv: float(kv[1]))[0] if hot_path else "unknown"
    return {
        "scenario": "drag",
        "deterministic": bool(drag_node.get("deterministic", False)),
        "p95_frame_total_ms": float(result.get("p95_frame_total_ms", 0.0)),
        "p99_frame_total_ms": float(result.get("p99_frame_total_ms", 0.0)),
        "jitter_ms": float(result.get("jitter_ms", 0.0)),
        "p95_input_to_present_ms": float(result.get("p95_input_to_present_ms", 0.0)),
        "incremental_present_pct": float(result.get("incremental_present_pct", 0.0)),
        "full_present_pct": float(result.get("full_present_pct", 0.0)),
        "p95_dirty_area_ratio": float(result.get("p95_dirty_area_ratio", 0.0)),
        "hot_path_p95_ms": {k: float(v) for k, v in hot_path.items()},
        "hot_path_share_pct": {k: float(v) for k, v in shares.items()},
        "top_hot_path_stage": str(top_stage),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build R-041 drag hot-path baseline summary from perf output")
    parser.add_argument("--in", dest="inp", required=True, help="Input perf JSON path")
    parser.add_argument("--out", required=True, help="Output summary JSON path")
    args = parser.parse_args()

    summary = build_summary(_load_json(args.inp))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
