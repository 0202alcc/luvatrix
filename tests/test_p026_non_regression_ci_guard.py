from __future__ import annotations

import json
from pathlib import Path

from ops.ci.p026_non_regression_ci_guard import validate


def test_guard_passes_on_current_artifacts(tmp_path: Path) -> None:
    measured_src = Path("artifacts/perf/closeout/measured_summary.json")
    matrix_src = Path("artifacts/perf/closeout/determinism_replay_matrix.json")
    measured = json.loads(measured_src.read_text(encoding="utf-8"))
    matrix = json.loads(matrix_src.read_text(encoding="utf-8"))

    measured_path = tmp_path / "measured.json"
    matrix_path = tmp_path / "matrix.json"
    measured_path.write_text(json.dumps(measured), encoding="utf-8")
    matrix_path.write_text(json.dumps(matrix), encoding="utf-8")

    assert validate(measured_summary_path=measured_path, determinism_matrix_path=matrix_path) == []


def test_guard_fails_when_policy_or_determinism_breaks(tmp_path: Path) -> None:
    measured = {
        "milestone_id": "P-026",
        "policy_verdict": {"pass": False, "required_scenarios": []},
        "scenario_metrics": {},
    }
    matrix = {
        "milestone_id": "P-026",
        "mismatch_count": 2,
        "cross_seed_trace_fingerprints_distinct": False,
        "rows": [],
    }
    measured_path = tmp_path / "measured.json"
    matrix_path = tmp_path / "matrix.json"
    measured_path.write_text(json.dumps(measured), encoding="utf-8")
    matrix_path.write_text(json.dumps(matrix), encoding="utf-8")

    errors = validate(measured_summary_path=measured_path, determinism_matrix_path=matrix_path)
    assert any("policy_verdict.pass" in e for e in errors)
    assert any("mismatch_count" in e for e in errors)
