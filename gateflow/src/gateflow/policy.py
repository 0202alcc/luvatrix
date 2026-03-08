from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from gateflow.io import read_json


class PolicyViolation(RuntimeError):
    pass


def enforce_protected_branch_write_guard(root: Path) -> None:
    branch = _current_branch(root)
    if not branch:
        return

    config = read_json(root / ".gateflow" / "config.json")
    policy = config.get("policy", {})
    if not isinstance(policy, dict):
        raise ValueError("config policy must be an object")

    protected_branches = policy.get("protected_branches", [])
    if not isinstance(protected_branches, list):
        raise ValueError("config policy.protected_branches must be a list")
    protected_patterns = policy.get("protected_branch_patterns", [])
    if not isinstance(protected_patterns, list):
        raise ValueError("config policy.protected_branch_patterns must be a list")

    if branch in {str(name) for name in protected_branches}:
        raise PolicyViolation(
            f"POLICY_PROTECTED_BRANCH: writes are blocked on protected branch '{branch}'"
        )
    for pattern in protected_patterns:
        regex = str(pattern)
        if re.fullmatch(regex, branch):
            raise PolicyViolation(
                "POLICY_PROTECTED_BRANCH: writes are blocked on protected branch "
                f"'{branch}' (pattern='{regex}')"
            )


def _current_branch(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), "symbolic-ref", "--quiet", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch if branch else None
