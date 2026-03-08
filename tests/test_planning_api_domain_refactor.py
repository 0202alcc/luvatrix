from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _seed_planning_tree(root: Path) -> None:
    planning = root / "ops" / "planning"
    (planning / "gantt").mkdir(parents=True, exist_ok=True)
    (planning / "agile").mkdir(parents=True, exist_ok=True)
    (planning / "closeout").mkdir(parents=True, exist_ok=True)

    schedule = {
        "milestones": [
            {
                "id": "F-041",
                "name": "Core Domain Extraction",
                "emoji": "🧱",
                "start_week": 1,
                "end_week": 1,
                "status": "In Progress",
                "task_ids": ["T-4101"],
                "success_criteria": ["Parity"],
                "closeout_criteria": {
                    "metric_id": "f-041-closeout-v1",
                    "metric_description": "desc",
                    "score_formula": "weighted_sum",
                    "score_components": ["correctness"],
                    "go_threshold": 85,
                    "hard_no_go_conditions": ["none"],
                    "required_evidence": ["ops/planning/closeout/f-041_closeout.md"],
                    "required_commands": ["uv run python ops/planning/api/validate_closeout_packet.py --milestone-id F-041"],
                    "rubric_version": "closeout_rubric_v1",
                },
                "ci_required_checks": ["uv run python ops/planning/agile/validate_milestone_task_links.py"],
            },
            {
                "id": "P-044",
                "name": "Policy/Validation Hardening",
                "emoji": "🛡️",
                "start_week": 1,
                "end_week": 1,
                "status": "Planned",
                "task_ids": [],
                "success_criteria": ["policy checks pass"],
                "closeout_criteria": {
                    "metric_id": "p-044-closeout-v1",
                    "metric_description": "desc",
                    "score_formula": "weighted_sum",
                    "score_components": ["correctness"],
                    "go_threshold": 85,
                    "hard_no_go_conditions": ["none"],
                    "required_evidence": ["ops/planning/closeout/p-044_closeout.md"],
                    "required_commands": [
                        "uv run python ops/planning/api/validate_closeout_packet.py --milestone-id P-044"
                    ],
                    "rubric_version": "closeout_rubric_v1",
                },
                "ci_required_checks": ["uv run python ops/planning/agile/validate_milestone_task_links.py"],
            },
        ]
    }
    tasks_master = {
        "tasks": [
            {
                "id": "T-4101",
                "title": "Extract planning domain services",
                "milestone_id": "F-041",
                "status": "Intake",
                "depends_on": [],
                "board_refs": ["milestone:F-041"],
            }
        ]
    }
    tasks_archived = {"tasks": []}
    boards = {
        "board_types": {"execution": {"description": "Milestone execution board"}},
        "framework_templates": {
            "gateflow_v1": {
                "description": "GateFlow",
                "status_columns": [
                    "Intake",
                    "Success Criteria Spec",
                    "Safety Tests Spec",
                    "Implementation Tests Spec",
                    "Edge Case Tests Spec",
                    "Prototype Stage 1",
                    "Prototype Stage 2+",
                    "Verification Review",
                    "Integration Ready",
                    "Done",
                    "Blocked",
                ],
                "wip_limits": {"Prototype Combined": 2, "Verification Review": 1},
            }
        },
        "default_framework_template": "gateflow_v1",
        "render_defaults": {
            "status_columns": ["Backlog", "Ready", "In Progress", "Review", "Done", "Blocked"]
        },
        "boards": [
            {
                "id": "milestone:F-041",
                "title": "F-041",
                "type": "execution",
                "source_filter": {"milestone_id": "F-041"},
                "framework_template": "gateflow_v1",
            },
            {
                "id": "milestone:P-044",
                "title": "P-044",
                "type": "execution",
                "source_filter": {"milestone_id": "P-044"},
                "framework_template": "gateflow_v1",
            },
        ],
    }
    backlog = {"items": []}

    (planning / "gantt" / "milestone_schedule.json").write_text(json.dumps(schedule), encoding="utf-8")
    (planning / "agile" / "tasks_master.json").write_text(json.dumps(tasks_master), encoding="utf-8")
    (planning / "agile" / "tasks_archived.json").write_text(json.dumps(tasks_archived), encoding="utf-8")
    (planning / "agile" / "boards_registry.json").write_text(json.dumps(boards), encoding="utf-8")
    (planning / "agile" / "backlog_misc.json").write_text(json.dumps(backlog), encoding="utf-8")
    (planning / "closeout" / "f-041_closeout.md").write_text(
        "\n".join(
            [
                "# Objective Summary",
                "# Task Final States",
                "# Evidence",
                "# Determinism",
                "# Protocol Compatibility",
                "# Modularity",
                "# Residual Risks",
            ]
        ),
        encoding="utf-8",
    )
    (planning / "closeout" / "p-044_closeout.md").write_text(
        "\n".join(
            [
                "# Objective Summary",
                "# Task Final States",
                "# Evidence",
                "# Determinism",
                "# Protocol Compatibility",
                "# Modularity",
                "# Residual Risks",
            ]
        ),
        encoding="utf-8",
    )


def _run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=merged_env)


def test_planning_api_get_with_root_reads_custom_tree(tmp_path: Path) -> None:
    _seed_planning_tree(tmp_path)
    proc = _run(
        [
            sys.executable,
            "ops/planning/api/planning_api.py",
            "GET",
            "/milestones/F-041",
            "--root",
            str(tmp_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["id"] == "F-041"
    assert payload["task_ids"] == ["T-4101"]
    assert "DEPRECATION: ops/planning/api/planning_api.py is a legacy compatibility endpoint." in proc.stderr
    assert "Sunset date: 2026-06-30" in proc.stderr


def test_planning_api_rejects_gateflow_stage_skips(tmp_path: Path) -> None:
    _seed_planning_tree(tmp_path)
    proc = _run(
        [
            sys.executable,
            "ops/planning/api/planning_api.py",
            "PATCH",
            "/tasks/T-4101",
            "--body",
            '{"status":"Prototype Stage 1"}',
            "--root",
            str(tmp_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
    )

    assert proc.returncode == 2
    assert "cannot skip GateFlow stages" in proc.stderr


def test_validate_closeout_packet_supports_root(tmp_path: Path) -> None:
    _seed_planning_tree(tmp_path)
    proc = _run(
        [
            sys.executable,
            "ops/planning/api/validate_closeout_packet.py",
            "--milestone-id",
            "F-041",
            "--root",
            str(tmp_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "validation: PASS" in proc.stdout


def test_harness_first_is_warning_by_default(tmp_path: Path) -> None:
    _seed_planning_tree(tmp_path)
    proc = _run(
        [
            sys.executable,
            "ops/planning/api/planning_api.py",
            "POST",
            "/tasks",
            "--body",
            '{"id":"T-4401","title":"test","milestone_id":"P-044","status":"Intake","depends_on":[],"board_refs":["milestone:P-044"]}',
            "--root",
            str(tmp_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
    )

    assert proc.returncode == 0, proc.stderr
    assert "warning mode: warn" in proc.stdout


def test_harness_first_can_escalate_to_strict(tmp_path: Path) -> None:
    _seed_planning_tree(tmp_path)
    proc = _run(
        [
            sys.executable,
            "ops/planning/api/planning_api.py",
            "POST",
            "/tasks",
            "--body",
            '{"id":"T-4401","title":"test","milestone_id":"P-044","status":"Intake","depends_on":[],"board_refs":["milestone:P-044"]}',
            "--root",
            str(tmp_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={"PLANNING_API_HARNESS_FIRST_MODE": "strict"},
    )

    assert proc.returncode == 2
    assert "requires a closeout harness task" in proc.stderr


def test_planning_api_writes_deprecation_telemetry_and_dashboard(tmp_path: Path) -> None:
    _seed_planning_tree(tmp_path)
    repo_root = Path(__file__).resolve().parents[1]
    proc = _run(
        [
            sys.executable,
            "ops/planning/api/planning_api.py",
            "GET",
            "/milestones/F-041",
            "--root",
            str(tmp_path),
        ],
        cwd=repo_root,
    )
    assert proc.returncode == 0, proc.stderr

    telemetry_file = tmp_path / "ops" / "planning" / "telemetry" / "planning_api_deprecation_usage.jsonl"
    assert telemetry_file.exists()
    first = json.loads(telemetry_file.read_text(encoding="utf-8").strip().splitlines()[0])
    assert first["method"] == "GET"
    assert first["path"] == "/milestones/F-041"
    assert first["sunset_date"] == "2026-06-30"

    dashboard = _run(
        [
            sys.executable,
            "ops/planning/api/planning_api_deprecation_dashboard.py",
            "--root",
            str(tmp_path),
        ],
        cwd=repo_root,
    )
    assert dashboard.returncode == 0, dashboard.stderr
    payload = json.loads(dashboard.stdout)
    assert payload["status"] == "ok"
    assert payload["entries_total"] >= 1
