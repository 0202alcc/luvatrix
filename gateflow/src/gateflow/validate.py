from __future__ import annotations

from pathlib import Path
from typing import Any

from gateflow.io import read_json

REQUIRED_CLOSEOUT_SECTIONS = [
    "Objective Summary",
    "Task Final States",
    "Evidence",
    "Determinism",
    "Protocol Compatibility",
    "Modularity",
    "Residual Risks",
]


class ValidationCommandError(ValueError):
    def __init__(self, mode: str, errors: list[str]) -> None:
        self.mode = mode
        self.errors = list(errors)
        super().__init__(f"validation failed ({mode})")


def validate_links(root: Path) -> list[str]:
    gateflow = root / ".gateflow"
    milestones = read_json(gateflow / "milestones.json").get("items", [])
    tasks = read_json(gateflow / "tasks.json").get("items", [])
    task_index = {str(task.get("id")): task for task in tasks}
    errors: list[str] = []

    for milestone in milestones:
        mid = str(milestone.get("id", "<unknown>"))
        task_ids = milestone.get("task_ids", [])
        if task_ids is None:
            continue
        if not isinstance(task_ids, list):
            errors.append(f"{mid}: task_ids must be a list")
            continue
        for tid in task_ids:
            tid_s = str(tid)
            task = task_index.get(tid_s)
            if task is None:
                errors.append(f"{mid}: missing task {tid_s}")
                continue
            task_mid = str(task.get("milestone_id", ""))
            if task_mid and task_mid != mid:
                errors.append(f"{mid}: task {tid_s} belongs to {task_mid}")

    for task in tasks:
        tid = str(task.get("id", "<unknown>"))
        deps = task.get("depends_on", [])
        if deps is None:
            continue
        if not isinstance(deps, list):
            errors.append(f"{tid}: depends_on must be a list")
            continue
        for dep in deps:
            dep_s = str(dep)
            if dep_s not in task_index:
                errors.append(f"{tid}: dependency missing task {dep_s}")
    return errors


def validate_closeout(root: Path) -> list[str]:
    gateflow = root / ".gateflow"
    closeout_dir = gateflow / "closeout"
    milestones = read_json(gateflow / "milestones.json").get("items", [])
    errors: list[str] = []

    for milestone in milestones:
        mid = str(milestone.get("id", "")).strip()
        if not mid:
            continue
        requires_packet = milestone.get("status") == "Complete" or "closeout_criteria" in milestone
        if not requires_packet:
            continue
        path = closeout_dir / f"{mid.lower()}_closeout.md"
        if not path.exists():
            errors.append(f"{mid}: missing closeout packet {path}")
            continue
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            errors.append(f"{mid}: closeout packet is empty")
            continue
        headings = {_normalize_heading(line) for line in text.splitlines() if line.strip().startswith("#")}
        missing = [section for section in REQUIRED_CLOSEOUT_SECTIONS if section.lower() not in headings]
        if missing:
            errors.append(f"{mid}: closeout packet missing sections: {', '.join(missing)}")
    return errors


def run_validation(root: Path, mode: str) -> tuple[bool, list[str]]:
    if mode == "links":
        errors = validate_links(root)
        return len(errors) == 0, errors
    if mode == "closeout":
        errors = validate_closeout(root)
        return len(errors) == 0, errors
    if mode == "all":
        errors = validate_links(root) + validate_closeout(root)
        return len(errors) == 0, errors
    raise ValueError(f"unsupported validate mode: {mode}")


def _normalize_heading(line: str) -> str:
    return line.strip().lstrip("#").strip().lower()
