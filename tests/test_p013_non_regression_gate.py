from __future__ import annotations

from ops.ci.p013_non_regression_gate import command_pack, gateflow_ledger_available, run_gate_pack


def test_command_pack_contains_required_checks() -> None:
    names = [entry.name for entry in command_pack()]
    assert names == [
        "gateflow-links",
        "gateflow-closeout",
        "gateflow-all",
    ]


def test_dry_run_marks_checks_skipped_and_passed() -> None:
    summary = run_gate_pack(execute=False)
    assert summary["milestone_id"] == "P-013"
    assert bool(summary["passed"])
    statuses = [check["status"] for check in summary["checks"]]
    assert statuses == ["SKIPPED", "SKIPPED", "SKIPPED"]


def test_execute_skips_when_gateflow_ledger_is_absent() -> None:
    assert not gateflow_ledger_available()

    summary = run_gate_pack(execute=True)

    assert bool(summary["passed"])
    statuses = [check["status"] for check in summary["checks"]]
    assert statuses == ["SKIPPED", "SKIPPED", "SKIPPED"]
    assert all("gateflow ledger files are not present" in str(check["stdout"]) for check in summary["checks"])
