from __future__ import annotations

import subprocess
from pathlib import Path


def test_gateflow_validate_all_cli_continuity() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        ["uv", "run", "gateflow", "--root", ".", "validate", "all"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "validation: PASS (all)" in proc.stdout
