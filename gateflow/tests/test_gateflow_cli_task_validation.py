from __future__ import annotations

from pathlib import Path

from gateflow.cli import main


def _seed(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path), "init", "scaffold", "--profile", "minimal"]) == 0


def test_task_update_rejects_gateflow_stage_skip(tmp_path: Path) -> None:
    _seed(tmp_path)
    assert main(["--root", str(tmp_path), "tasks", "create", "--body", '{"id":"T-9100","status":"Intake"}']) == 0
    assert main(["--root", str(tmp_path), "tasks", "update", "T-9100", "--body", '{"status":"Prototype Stage 1"}']) == 2


def test_task_done_requires_actuals_and_done_gate(tmp_path: Path) -> None:
    _seed(tmp_path)
    assert main(["--root", str(tmp_path), "tasks", "create", "--body", '{"id":"T-9101","status":"Intake"}']) == 0
    for stage in (
        "Success Criteria Spec",
        "Safety Tests Spec",
        "Implementation Tests Spec",
        "Edge Case Tests Spec",
        "Prototype Stage 1",
        "Prototype Stage 2+",
        "Verification Review",
        "Integration Ready",
    ):
        assert main(["--root", str(tmp_path), "tasks", "update", "T-9101", "--body", f'{{"status":"{stage}"}}']) == 0

    assert main(["--root", str(tmp_path), "tasks", "update", "T-9101", "--body", '{"status":"Done"}']) == 2
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "tasks",
                "update",
                "T-9101",
                "--body",
                '{"status":"Done","actuals":{"input_tokens":1,"output_tokens":2,"wall_time_sec":3,"tool_calls":4,"reopen_count":0},"done_gate":{"success_criteria_met":true,"safety_tests_passed":true,"implementation_tests_passed":true,"edge_case_tests_passed":true,"merged_to_main":true,"required_checks_passed_on_main":true}}',
            ]
        )
        == 0
    )
