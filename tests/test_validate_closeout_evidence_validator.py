from __future__ import annotations

import importlib.util
import json
from hashlib import sha256
from pathlib import Path
from typing import Any


def _load_validator_module():
    path = Path(__file__).resolve().parents[1] / "ops" / "planning" / "api" / "validate_closeout_evidence.py"
    spec = importlib.util.spec_from_file_location("validate_closeout_evidence_module", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hash_file(path: Path) -> str:
    digest = sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _build_result(incremental: float, full: float, max_streak: int = 1) -> dict[str, Any]:
    compose_modes = ["partial_dirty", "idle_skip"] + (["full_frame"] * max_streak) + ["partial_dirty"]
    return {
        "deterministic": True,
        "result": {
            "incremental_present_pct": float(incremental),
            "full_present_pct": float(full),
            "compose_modes": compose_modes,
        },
    }


def _base_summary_scenario() -> dict[str, float | None]:
    return {
        "p50_frame_total_ms": 0.1,
        "p95_frame_total_ms": 0.2,
        "p99_frame_total_ms": 0.3,
        "dropped_frame_ratio": 0.0,
        "p95_input_to_present_ms": 16.67,
        "p99_input_to_present_ms": 16.67,
        "resize_recovery_sec": None,
    }


def _write_closeout_bundle(
    root: Path,
    *,
    scenario_overrides: dict[str, dict[str, Any]] | None = None,
    summary_exception_overrides: dict[str, dict[str, Any]] | None = None,
) -> None:
    closeout_root = root / "artifacts" / "perf" / "closeout"
    planning_closeout = root / "ops" / "planning" / "closeout"
    closeout_root.mkdir(parents=True, exist_ok=True)
    planning_closeout.mkdir(parents=True, exist_ok=True)

    scenarios: dict[str, dict[str, Any]] = {
        "scroll": _build_result(99.0, 1.0),
        "horizontal_pan": _build_result(99.0, 1.0),
        "drag_heavy": _build_result(99.0, 1.0),
        "mixed_burst": _build_result(99.0, 1.0),
        "sensor_overlay": _build_result(99.0, 1.0),
        "resize_overlap_incremental_required": _build_result(99.0, 1.0),
        "resize_stress_fullframe_allowed": _build_result(0.0, 100.0),
        "input_burst": _build_result(90.0, 10.0),
    }
    if scenario_overrides:
        scenarios.update(scenario_overrides)

    raw = {
        "provenance": {
            "command": "run_suite",
            "commit_sha": "abc123",
            "timestamp_utc": "2026-03-05T00:00:00+00:00",
            "seed_list": [1337],
            "run_count": 2,
        },
        "scenarios": scenarios,
    }

    summary_scenarios: dict[str, dict[str, Any]] = {
        "scroll": _base_summary_scenario(),
        "horizontal_pan": _base_summary_scenario(),
        "drag_heavy": _base_summary_scenario(),
        "mixed_burst": _base_summary_scenario(),
        "sensor_overlay": _base_summary_scenario(),
        "resize_overlap_incremental_required": {
            **_base_summary_scenario(),
            "incremental_present_pct": 99.0,
        },
        "resize_stress_fullframe_allowed": {
            **_base_summary_scenario(),
            "resize_recovery_sec": 0.02,
        },
        "input_burst": _base_summary_scenario(),
    }
    if summary_exception_overrides:
        for scenario, payload in summary_exception_overrides.items():
            summary_scenarios.setdefault(scenario, _base_summary_scenario())
            summary_scenarios[scenario]["exception"] = payload

    summary = {
        "summary_type": "measured_only",
        "metrics": {
            "frame_time_ms": {"p50": 0.1, "p95": 0.2, "p99": 0.3},
            "input_to_present_ms": {"p95": 16.67, "p99": 16.67},
            "resize_recovery_sec": 0.02,
            "dropped_frame_ratio": 0.0,
        },
        "scenario_metrics": summary_scenarios,
        "provenance": {
            "raw_artifact": "artifacts/perf/closeout/raw_closeout_required.json",
            "raw_command": "run_suite",
            "raw_commit_sha": "abc123",
            "raw_timestamp_utc": "2026-03-05T00:00:00+00:00",
            "seed_list": [1337],
            "run_count": 2,
        },
    }

    det_log_rel = "artifacts/perf/closeout/determinism_log_seed1337_run1.json"
    det_log_abs = root / det_log_rel
    det_log = {
        "event_order_digest": "digest-a",
        "revision_sequence_digest": "digest-b",
        "provenance": {
            "command": "build_replay",
            "commit_sha": "abc123",
            "timestamp_utc": "2026-03-05T00:00:00+00:00",
            "seed_list": [1337],
            "run_counts": {"1337": 1},
        },
    }
    determinism = {
        "seed_count_observed": 1,
        "seed_count_required": 1,
        "runs_per_seed_observed": 1,
        "runs_per_seed_required": 1,
        "mismatch_count": 0,
        "rows": [
            {
                "log_path": det_log_rel,
                "event_order_digest": "digest-a",
                "revision_sequence_digest": "digest-b",
            }
        ],
        "provenance": {
            "command": "build_replay",
            "commit_sha": "abc123",
            "timestamp_utc": "2026-03-05T00:00:00+00:00",
            "seed_list": [1337],
            "run_counts": {"1337": 1},
            "raw_file_refs": ["artifacts/perf/closeout/raw_closeout_required.json"],
        },
    }

    raw_path = closeout_root / "raw_closeout_required.json"
    summary_path = closeout_root / "measured_summary.json"
    det_path = closeout_root / "determinism_replay_matrix.json"
    _write_json(raw_path, raw)
    _write_json(summary_path, summary)
    _write_json(det_log_abs, det_log)
    _write_json(det_path, determinism)

    manifest = {
        "artifacts": [
            {"path": "artifacts/perf/closeout/raw_closeout_required.json", "sha256": _hash_file(raw_path)},
            {"path": "artifacts/perf/closeout/measured_summary.json", "sha256": _hash_file(summary_path)},
            {"path": "artifacts/perf/closeout/determinism_replay_matrix.json", "sha256": _hash_file(det_path)},
        ]
    }
    closeout_md = planning_closeout / "p-026_closeout.md"
    closeout_md.write_text(
        "# P-026 Closeout\n\n```json\n" + json.dumps(manifest, indent=2) + "\n```\n",
        encoding="utf-8",
    )


def test_validator_policy_passes_for_compliant_payload(tmp_path: Path, monkeypatch) -> None:
    mod = _load_validator_module()
    _write_closeout_bundle(tmp_path)
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "PLANNING_ROOT", tmp_path / "ops" / "planning")
    monkeypatch.setattr(mod, "CLOSEOUT_ROOT", tmp_path / "artifacts" / "perf" / "closeout")
    ok, errors = mod.validate("P-026")
    assert ok
    assert errors == []


def test_validator_fails_threshold_miss_without_exception(tmp_path: Path, monkeypatch) -> None:
    mod = _load_validator_module()
    _write_closeout_bundle(tmp_path, scenario_overrides={"input_burst": _build_result(80.0, 10.0)})
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "PLANNING_ROOT", tmp_path / "ops" / "planning")
    monkeypatch.setattr(mod, "CLOSEOUT_ROOT", tmp_path / "artifacts" / "perf" / "closeout")
    ok, errors = mod.validate("P-026")
    assert not ok
    assert any(
        "scenario=input_burst" in err
        and "metric=incremental_present_pct" in err
        and "target_min=85.0" in err
        and "exception=missing" in err
        for err in errors
    )


def test_validator_allows_threshold_miss_with_approved_exception(tmp_path: Path, monkeypatch) -> None:
    mod = _load_validator_module()
    _write_closeout_bundle(
        tmp_path,
        scenario_overrides={"input_burst": _build_result(80.0, 10.0)},
        summary_exception_overrides={
            "input_burst": {
                "approved": True,
                "reason": "temporary mitigation while T-2820 is in progress",
                "approver": "arch-review",
                "ticket": "INC-2820-1",
            }
        },
    )
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "PLANNING_ROOT", tmp_path / "ops" / "planning")
    monkeypatch.setattr(mod, "CLOSEOUT_ROOT", tmp_path / "artifacts" / "perf" / "closeout")
    ok, errors = mod.validate("P-026")
    assert ok
    assert errors == []


def test_validator_fails_cap_miss_even_with_exception(tmp_path: Path, monkeypatch) -> None:
    mod = _load_validator_module()
    _write_closeout_bundle(
        tmp_path,
        scenario_overrides={"input_burst": _build_result(90.0, 20.0, max_streak=9)},
        summary_exception_overrides={
            "input_burst": {
                "approved": True,
                "reason": "temporary mitigation while T-2820 is in progress",
                "approver": "arch-review",
                "ticket": "INC-2820-2",
            }
        },
    )
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "PLANNING_ROOT", tmp_path / "ops" / "planning")
    monkeypatch.setattr(mod, "CLOSEOUT_ROOT", tmp_path / "artifacts" / "perf" / "closeout")
    ok, errors = mod.validate("P-026")
    assert not ok
    assert any(
        "scenario=input_burst" in err and "metric=full_present_pct" in err and "cap_max=15.0" in err for err in errors
    )
    assert any(
        "scenario=input_burst" in err
        and "metric=max_consecutive_full_frame_outside_exception" in err
        and "cap_max=8" in err
        for err in errors
    )


def test_validator_fails_when_exception_metadata_is_incomplete(tmp_path: Path, monkeypatch) -> None:
    mod = _load_validator_module()
    _write_closeout_bundle(
        tmp_path,
        scenario_overrides={"input_burst": _build_result(80.0, 10.0)},
        summary_exception_overrides={
            "input_burst": {
                "approved": True,
                "reason": "missing approver and ticket fields",
            }
        },
    )
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "PLANNING_ROOT", tmp_path / "ops" / "planning")
    monkeypatch.setattr(mod, "CLOSEOUT_ROOT", tmp_path / "artifacts" / "perf" / "closeout")
    ok, errors = mod.validate("P-026")
    assert not ok
    assert any(
        "scenario=input_burst" in err
        and "metric=incremental_present_pct" in err
        and "exception=incomplete(" in err
        for err in errors
    )


def test_validator_fails_when_required_scenario_is_missing(tmp_path: Path, monkeypatch) -> None:
    mod = _load_validator_module()
    _write_closeout_bundle(tmp_path, scenario_overrides={"input_burst": None})  # type: ignore[arg-type]
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "PLANNING_ROOT", tmp_path / "ops" / "planning")
    monkeypatch.setattr(mod, "CLOSEOUT_ROOT", tmp_path / "artifacts" / "perf" / "closeout")
    ok, errors = mod.validate("P-026")
    assert not ok
    assert any("scenario=input_burst" in err and "observed=missing" in err for err in errors)
