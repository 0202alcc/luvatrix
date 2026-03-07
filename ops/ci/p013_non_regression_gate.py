from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GateCommand:
    name: str
    command: list[str]


def command_pack() -> list[GateCommand]:
    return [
        GateCommand(
            name="debug-manifest-compat",
            command=[
                "uv",
                "run",
                "--with",
                "pytest",
                "pytest",
                "tests/test_app_runtime.py",
                "tests/test_debug_manifest_policy.py",
                "-k",
                "debug_manifest or legacy_debug_conformance",
                "-q",
            ],
        ),
        GateCommand(
            name="p026-non-regression-evidence",
            command=[
                "uv",
                "run",
                "python",
                "ops/ci/p026_non_regression_ci_guard.py",
            ],
        ),
        GateCommand(
            name="milestone-task-links",
            command=[
                "uv",
                "run",
                "python",
                "ops/planning/agile/validate_milestone_task_links.py",
            ],
        ),
    ]


def run_gate_pack(*, execute: bool) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    for item in command_pack():
        check = {
            "name": item.name,
            "command": " ".join(item.command),
            "status": "SKIPPED",
            "returncode": 0,
            "stdout": "",
            "stderr": "",
        }
        if execute:
            proc = subprocess.run(
                item.command,
                text=True,
                capture_output=True,
                env={**os.environ, "PYTHONPATH": "."},
            )
            check["returncode"] = int(proc.returncode)
            check["stdout"] = proc.stdout
            check["stderr"] = proc.stderr
            check["status"] = "PASS" if proc.returncode == 0 else "FAIL"
        checks.append(check)

    passed = all(c["status"] in {"PASS", "SKIPPED"} for c in checks)
    return {
        "milestone_id": "P-013",
        "checks": checks,
        "passed": bool(passed),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run P-013 non-regression gate pack")
    parser.add_argument("--execute", action="store_true", help="execute commands (default is dry-run plan)")
    parser.add_argument("--out", type=Path, default=Path("artifacts/p013/non_regression_gate_summary.json"))
    args = parser.parse_args()

    summary = run_gate_pack(execute=bool(args.execute))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if bool(summary["passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
