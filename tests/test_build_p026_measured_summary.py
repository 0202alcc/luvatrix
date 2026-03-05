from __future__ import annotations

import pytest

from tools.perf.build_p026_measured_summary import build_measured_summary


def _frame_result(*, incremental: float = 100.0, full: float = 0.0, compose_modes: list[str] | None = None) -> dict[str, float | list[str] | int]:
    return {
        "p50_frame_total_ms": 0.1,
        "p95_frame_total_ms": 0.2,
        "p99_frame_total_ms": 0.3,
        "dropped_frame_ratio": 0.0,
        "p95_input_to_present_ms": 16.666666666666668,
        "p99_input_to_present_ms": 16.666666666666668,
        "incremental_present_pct": float(incremental),
        "full_present_pct": float(full),
        "compose_modes": compose_modes if compose_modes is not None else ["partial_dirty", "partial_dirty"],
        "app_reinit_count": 0,
    }


def _raw_fixture() -> dict:
    return {
        "provenance": {
            "command": "tools/perf/run_suite.py --scenario closeout_required",
            "commit_sha": "abc123",
            "timestamp_utc": "2026-03-05T00:00:00+00:00",
            "seed_list": [1337],
            "run_count": 1,
        },
        "scenarios": {
            "scroll": {"result": _frame_result(incremental=95.0, full=5.0)},
            "horizontal_pan": {"result": _frame_result(incremental=92.0, full=5.0)},
            "drag_heavy": {"result": _frame_result(incremental=85.0, full=5.0)},
            "mixed_burst": {"result": _frame_result(incremental=88.0, full=5.0)},
            "sensor_overlay": {"result": _frame_result(incremental=90.0, full=5.0)},
            "resize_stress_fullframe_allowed": {
                "result": {**_frame_result(incremental=0.0, full=100.0), "resize_recovery_sec": 0.02}
            },
            "resize_overlap_incremental_required": {"result": _frame_result(incremental=75.0, full=5.0)},
            "input_burst": {"result": _frame_result(incremental=85.0, full=5.0)},
            "sensor_polling": {"result": {"cycle_cost_p95_ms": 8.0}},
        },
    }


def test_build_measured_summary_embeds_policy_verdicts() -> None:
    summary = build_measured_summary(_raw_fixture())
    assert summary["policy_verdict"]["pass"] is True
    for scenario in (
        "scroll",
        "horizontal_pan",
        "drag_heavy",
        "mixed_burst",
        "sensor_overlay",
        "resize_overlap_incremental_required",
        "input_burst",
    ):
        node = summary["scenario_metrics"][scenario]
        assert set(
            (
                "observed_incremental_pct",
                "target_incremental_pct",
                "observed_full_pct",
                "full_pct_cap",
                "max_consecutive_full_frame",
                "consecutive_full_cap",
                "exception_applied",
                "pass",
            )
        ).issubset(node.keys())


def test_build_measured_summary_fails_when_policy_inputs_missing() -> None:
    raw = _raw_fixture()
    del raw["scenarios"]["input_burst"]["result"]["compose_modes"]
    with pytest.raises(ValueError, match="input_burst missing measured policy field: compose_modes"):
        build_measured_summary(raw)
