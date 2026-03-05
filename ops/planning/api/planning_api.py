#!/usr/bin/env python3
"""Endpoint-style planning data mutator for milestones and tasks.

Examples:
  python ops/planning/api/planning_api.py POST /milestones --body '{"id":"A-021",...}'
  python ops/planning/api/planning_api.py PATCH /tasks/T-1201 --body '{"status":"Prototype Stage 1"}' --apply
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path("ops/planning")
SCHEDULE_PATH = ROOT / "gantt/milestone_schedule.json"
TASKS_MASTER_PATH = ROOT / "agile/tasks_master.json"
TASKS_ARCHIVED_PATH = ROOT / "agile/tasks_archived.json"
BOARDS_PATH = ROOT / "agile/boards_registry.json"
BACKLOG_PATH = ROOT / "agile/backlog_misc.json"
GANTT_MD_PATH = ROOT / "gantt/milestones_gantt.md"
GANTT_PNG_PATH = ROOT / "gantt/milestones_gantt.png"
CLOSEOUT_DIR = ROOT / "closeout"

METHODS = {"GET", "POST", "PATCH", "DELETE"}
ALLOWED_MILESTONE_STATUS = {"Planned", "In Progress", "Complete", "Blocked"}
LEGACY_TASK_STATUS = {"Backlog", "Ready", "In Progress", "Review", "Done", "Blocked"}
MILESTONE_ID_RE = re.compile(r"^[ARFUPX]{1,3}-\d{3}$")
TASK_ID_RE = re.compile(r"^(T|A-H)\-\d{3,4}(?:-\d{2})?$")
BACKLOG_ID_RE = re.compile(r"^B-\d{3,4}$")
BACKLOG_STATUS = {"Open", "Triaged", "Assigned", "Closed"}
BACKLOG_BUCKETS = {"Carryover", "Unscoped", "ParkingLot", "Backfill"}
COST_BASIS_VERSION = "gateflow_cost_v1"
COST_COMPONENT_KEYS = {
    "context_load",
    "reasoning_depth",
    "code_edit_surface",
    "validation_scope",
    "iteration_risk",
}
COST_COMPONENT_WEIGHTS = {
    "context_load": 0.20,
    "reasoning_depth": 0.25,
    "code_edit_surface": 0.20,
    "validation_scope": 0.20,
    "iteration_risk": 0.15,
}
GATEFLOW_STAGE_MULTIPLIERS = {
    "Intake": 0.60,
    "Success Criteria Spec": 0.80,
    "Safety Tests Spec": 0.90,
    "Implementation Tests Spec": 0.90,
    "Edge Case Tests Spec": 0.95,
    "Prototype Stage 1": 1.00,
    "Prototype Stage 2+": 1.10,
    "Verification Review": 0.85,
    "Integration Ready": 0.70,
    "Done": 0.00,
}
DONE_REQUIRED_ACTUALS_KEYS = {
    "input_tokens",
    "output_tokens",
    "wall_time_sec",
    "tool_calls",
    "reopen_count",
}
DONE_REQUIRED_GATE_KEYS = {
    "success_criteria_met",
    "safety_tests_passed",
    "implementation_tests_passed",
    "edge_case_tests_passed",
    "merged_to_main",
    "required_checks_passed_on_main",
}
GATEFLOW_SEQUENCE = [
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
]
DEFAULT_PROTOTYPE_WIP_LIMIT = 2
DEFAULT_VERIFICATION_WIP_LIMIT = 1
MAX_PROTOTYPE_WIP_LIMIT = 10
MAX_VERIFICATION_WIP_LIMIT = 10
REQUIRED_CLOSEOUT_SECTIONS = [
    "Objective Summary",
    "Task Final States",
    "Evidence",
    "Determinism",
    "Protocol Compatibility",
    "Modularity",
    "Residual Risks",
]
ALLOWED_TASK_TYPES = {"standard", "closeout_harness"}
CLOSEOUT_HARNESS_TITLE_PREFIX = "[CLOSEOUT HARNESS]"


class ApiError(RuntimeError):
    pass


def current_git_branch() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def normalize_heading(line: str) -> str:
    return line.strip().lstrip("#").strip().lower()


def validate_closeout_packet(milestone_id: str) -> None:
    path = CLOSEOUT_DIR / f"{milestone_id.lower()}_closeout.md"
    if not path.exists():
        raise ApiError(
            f"milestone {milestone_id} cannot be marked Complete without closeout packet: {path}"
        )
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ApiError(f"closeout packet is empty: {path}")
    headings = {
        normalize_heading(line)
        for line in text.splitlines()
        if line.strip().startswith("#")
    }
    missing = [s for s in REQUIRED_CLOSEOUT_SECTIONS if s.lower() not in headings]
    if missing:
        raise ApiError(
            f"closeout packet {path} missing required sections: {', '.join(missing)}"
        )


def regenerate_gantt_artifacts() -> None:
    commands = [
        [
            sys.executable,
            "ops/discord/scripts/generate_gantt_markdown.py",
            "--schedule",
            str(SCHEDULE_PATH),
            "--out",
            str(GANTT_MD_PATH),
        ],
        [
            sys.executable,
            "ops/discord/scripts/generate_gantt_png.py",
            "--schedule",
            str(SCHEDULE_PATH),
            "--out",
            str(GANTT_PNG_PATH),
        ],
    ]
    for cmd in commands:
        subprocess.run(cmd, check=True, cwd=Path.cwd())


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def parse_body(args: argparse.Namespace) -> dict[str, Any]:
    if args.body and args.body_file:
        raise ApiError("pass either --body or --body-file, not both")
    if args.body:
        return json.loads(args.body)
    if args.body_file:
        return json.loads(Path(args.body_file).read_text(encoding="utf-8"))
    return {}


def index_by_id(rows: list[dict[str, Any]], key: str = "id") -> dict[str, dict[str, Any]]:
    return {row[key]: row for row in rows}


def split_path(path: str) -> tuple[str, str | None]:
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        raise ApiError("path must not be empty")
    if parts[0] not in {"milestones", "tasks", "boards", "frameworks", "backlog"}:
        raise ApiError("path must start with /milestones, /tasks, /boards, /frameworks, or /backlog")
    ident = parts[1] if len(parts) > 1 else None
    if len(parts) > 2:
        raise ApiError("path supports at most one identifier segment")
    return parts[0], ident


def validate_board_refs(task: dict[str, Any], board_ids: set[str]) -> None:
    refs = task.get("board_refs", [])
    if not isinstance(refs, list):
        raise ApiError(f"task {task.get('id')} board_refs must be a list")
    for ref in refs:
        if ref not in board_ids:
            raise ApiError(f"task {task.get('id')} references unknown board_ref '{ref}'")


def validate_milestone_descriptions(milestone: dict[str, Any]) -> None:
    mid = milestone.get("id", "<unknown>")
    descriptions = milestone.get("descriptions")
    if descriptions is None:
        return
    if not isinstance(descriptions, list):
        raise ApiError(f"milestone {mid} descriptions must be a list of strings")
    for idx, item in enumerate(descriptions):
        if not isinstance(item, str) or not item.strip():
            raise ApiError(f"milestone {mid} descriptions[{idx}] must be a non-empty string")


def validate_task_notes(task: dict[str, Any]) -> None:
    tid = task.get("id", "<unknown>")
    notes = task.get("notes")
    if notes is None:
        return
    if isinstance(notes, str):
        if not notes.strip():
            raise ApiError(f"task {tid} notes string must be non-empty")
        return
    if not isinstance(notes, list):
        raise ApiError(f"task {tid} notes must be a string or list of strings")
    for idx, item in enumerate(notes):
        if not isinstance(item, str) or not item.strip():
            raise ApiError(f"task {tid} notes[{idx}] must be a non-empty string")


def validate_closeout_criteria(milestone: dict[str, Any], *, required: bool) -> None:
    mid = milestone.get("id", "<unknown>")
    criteria = milestone.get("closeout_criteria")
    if criteria is None:
        if required:
            raise ApiError(f"milestone {mid} missing required closeout_criteria")
        return
    if not isinstance(criteria, dict):
        raise ApiError(f"milestone {mid} closeout_criteria must be an object")

    required_keys = {
        "metric_id",
        "metric_description",
        "score_formula",
        "score_components",
        "go_threshold",
        "hard_no_go_conditions",
        "required_evidence",
        "required_commands",
        "rubric_version",
    }
    missing = sorted(k for k in required_keys if k not in criteria)
    if missing:
        raise ApiError(
            f"milestone {mid} closeout_criteria missing fields: {', '.join(missing)}"
        )

    for key in {"metric_id", "metric_description", "score_formula", "rubric_version"}:
        val = criteria.get(key)
        if not isinstance(val, str) or not val.strip():
            raise ApiError(f"milestone {mid} closeout_criteria.{key} must be a non-empty string")

    gt = criteria.get("go_threshold")
    if not isinstance(gt, (int, float)):
        raise ApiError(f"milestone {mid} closeout_criteria.go_threshold must be numeric")
    if gt < 0 or gt > 100:
        raise ApiError(f"milestone {mid} closeout_criteria.go_threshold must be in [0,100]")

    for key in {"score_components", "hard_no_go_conditions", "required_evidence", "required_commands"}:
        val = criteria.get(key)
        if not isinstance(val, list) or not val:
            raise ApiError(f"milestone {mid} closeout_criteria.{key} must be a non-empty list")
        for idx, item in enumerate(val):
            if not isinstance(item, str) or not item.strip():
                raise ApiError(
                    f"milestone {mid} closeout_criteria.{key}[{idx}] must be a non-empty string"
                )


def validate_ci_required_checks(milestone: dict[str, Any], *, required: bool) -> None:
    mid = milestone.get("id", "<unknown>")
    checks = milestone.get("ci_required_checks")
    if checks is None:
        if required:
            raise ApiError(f"milestone {mid} missing required ci_required_checks")
        return
    if not isinstance(checks, list) or not checks:
        raise ApiError(f"milestone {mid} ci_required_checks must be a non-empty list")
    for idx, item in enumerate(checks):
        if not isinstance(item, str) or not item.strip():
            raise ApiError(f"milestone {mid} ci_required_checks[{idx}] must be a non-empty string")


def normalize_task_type_and_title(task: dict[str, Any]) -> None:
    ttype = task.get("task_type", "standard")
    if ttype not in ALLOWED_TASK_TYPES:
        raise ApiError(
            f"task {task.get('id')} task_type must be one of: {', '.join(sorted(ALLOWED_TASK_TYPES))}"
        )
    task["task_type"] = ttype

    title = task.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ApiError(f"task {task.get('id')} title must be a non-empty string")
    if ttype == "closeout_harness" and not title.startswith(CLOSEOUT_HARNESS_TITLE_PREFIX):
        task["title"] = f"{CLOSEOUT_HARNESS_TITLE_PREFIX} {title}"


def enforce_closeout_harness_first(
    schedule: dict[str, Any],
    tasks_master: dict[str, Any],
    tasks_archived: dict[str, Any],
    *,
    milestone_id: str,
    candidate_task_type: str,
) -> None:
    milestone = next((m for m in schedule.get("milestones", []) if m.get("id") == milestone_id), None)
    if milestone is None:
        raise ApiError(f"unknown milestone_id: {milestone_id}")

    # Legacy milestones without closeout_criteria are exempt.
    if "closeout_criteria" not in milestone:
        return

    linked_active = [t for t in tasks_master.get("tasks", []) if t.get("milestone_id") == milestone_id]
    linked_archived = [t for t in tasks_archived.get("tasks", []) if t.get("milestone_id") == milestone_id]
    linked_all = linked_active + linked_archived
    has_harness = any(t.get("task_type", "standard") == "closeout_harness" for t in linked_all)

    # Enforce only for new milestone task streams: no tasks exist yet.
    if not linked_all and candidate_task_type != "closeout_harness":
        raise ApiError(
            f"milestone {milestone_id} requires a closeout harness task before other task types"
        )


def validate_dep_id_format(task_id: str, dep: str) -> None:
    if not TASK_ID_RE.match(dep):
        raise ApiError(f"task {task_id} has invalid dependency id format: {dep}")


def clamp_score(value: float) -> float:
    return max(0.0, min(100.0, value))


def derive_cost_bucket(score: float) -> str:
    if score <= 20:
        return "S"
    if score <= 40:
        return "M"
    if score <= 60:
        return "L"
    if score <= 80:
        return "XL"
    return "XXL"


def validate_cost_fields(task: dict[str, Any]) -> None:
    if "cost_score" in task:
        score = task["cost_score"]
        if not isinstance(score, (int, float)):
            raise ApiError(f"task {task.get('id')} cost_score must be numeric")
        if score < 0 or score > 100:
            raise ApiError(f"task {task.get('id')} cost_score must be in [0,100]")

    if "cost_confidence" in task:
        conf = task["cost_confidence"]
        if not isinstance(conf, (int, float)):
            raise ApiError(f"task {task.get('id')} cost_confidence must be numeric")
        if conf < 0 or conf > 1:
            raise ApiError(f"task {task.get('id')} cost_confidence must be in [0,1]")

    if "cost_bucket" in task and task["cost_bucket"] not in {"S", "M", "L", "XL", "XXL"}:
        raise ApiError(f"task {task.get('id')} cost_bucket must be one of S/M/L/XL/XXL")

    if "cost_score" in task and "cost_bucket" in task:
        expected_bucket = derive_cost_bucket(float(task["cost_score"]))
        if task["cost_bucket"] != expected_bucket:
            raise ApiError(
                f"task {task.get('id')} cost_bucket {task['cost_bucket']} does not match cost_score-derived bucket {expected_bucket}"
            )

    components = task.get("cost_components")
    if components is not None:
        if not isinstance(components, dict):
            raise ApiError(f"task {task.get('id')} cost_components must be an object")
        missing = sorted(COST_COMPONENT_KEYS - set(components))
        if missing:
            raise ApiError(f"task {task.get('id')} cost_components missing keys: {', '.join(missing)}")
        for key in COST_COMPONENT_KEYS:
            value = components.get(key)
            if not isinstance(value, (int, float)):
                raise ApiError(f"task {task.get('id')} cost_components.{key} must be numeric")
            if value < 0 or value > 100:
                raise ApiError(f"task {task.get('id')} cost_components.{key} must be in [0,100]")

    if (
        "cost_score" in task
        or "cost_components" in task
        or "cost_bucket" in task
        or "cost_confidence" in task
    ):
        basis = task.get("cost_basis_version")
        if basis is not None and basis != COST_BASIS_VERSION:
            raise ApiError(f"task {task.get('id')} unsupported cost_basis_version: {basis}")

    if "stage_multiplier_applied" in task:
        mult = task["stage_multiplier_applied"]
        if not isinstance(mult, (int, float)):
            raise ApiError(f"task {task.get('id')} stage_multiplier_applied must be numeric")
        if mult < 0:
            raise ApiError(f"task {task.get('id')} stage_multiplier_applied must be >= 0")

    if "actuals" in task:
        actuals = task["actuals"]
        if not isinstance(actuals, dict):
            raise ApiError(f"task {task.get('id')} actuals must be an object")
        numeric_keys = DONE_REQUIRED_ACTUALS_KEYS
        for key in numeric_keys:
            if key in actuals:
                value = actuals[key]
                if not isinstance(value, (int, float)):
                    raise ApiError(f"task {task.get('id')} actuals.{key} must be numeric")
                if value < 0:
                    raise ApiError(f"task {task.get('id')} actuals.{key} must be >= 0")

    if "done_gate" in task:
        done_gate = task["done_gate"]
        if not isinstance(done_gate, dict):
            raise ApiError(f"task {task.get('id')} done_gate must be an object")
        for key in DONE_REQUIRED_GATE_KEYS:
            if key in done_gate and not isinstance(done_gate[key], bool):
                raise ApiError(f"task {task.get('id')} done_gate.{key} must be boolean")


def validate_done_gate_requirements(task: dict[str, Any], *, require: bool) -> None:
    if not require:
        return

    task_id = task.get("id")
    actuals = task.get("actuals")
    if not isinstance(actuals, dict):
        raise ApiError(
            f"task {task_id} moving to Done must include actuals with keys: "
            f"{', '.join(sorted(DONE_REQUIRED_ACTUALS_KEYS))}"
        )
    missing_actuals = sorted(k for k in DONE_REQUIRED_ACTUALS_KEYS if k not in actuals)
    if missing_actuals:
        raise ApiError(
            f"task {task_id} moving to Done missing actuals keys: {', '.join(missing_actuals)}"
        )

    done_gate = task.get("done_gate")
    if not isinstance(done_gate, dict):
        raise ApiError(
            f"task {task_id} moving to Done must include done_gate with keys: "
            f"{', '.join(sorted(DONE_REQUIRED_GATE_KEYS))}"
        )
    missing_done_gate = sorted(k for k in DONE_REQUIRED_GATE_KEYS if k not in done_gate)
    if missing_done_gate:
        raise ApiError(
            f"task {task_id} moving to Done missing done_gate keys: {', '.join(missing_done_gate)}"
        )
    failed_keys = sorted(k for k in DONE_REQUIRED_GATE_KEYS if done_gate.get(k) is not True)
    if failed_keys:
        raise ApiError(
            f"task {task_id} cannot move to Done; failed done_gate checks: {', '.join(failed_keys)}"
        )


def enforce_gateflow_status_transition(
    task_id: str,
    old_status: str,
    new_status: str,
    *,
    force_with_reason: str | None,
) -> None:
    if old_status == new_status:
        return

    # Keep legacy statuses backward compatible.
    if old_status not in GATEFLOW_SEQUENCE + ["Blocked"] or new_status not in GATEFLOW_SEQUENCE + ["Blocked"]:
        return

    if new_status == "Blocked":
        return
    if old_status == "Blocked":
        if new_status == "Done":
            raise ApiError(
                f"task {task_id} cannot move Blocked -> Done directly; move to Integration Ready first"
            )
        return

    old_idx = GATEFLOW_SEQUENCE.index(old_status)
    new_idx = GATEFLOW_SEQUENCE.index(new_status)
    delta = new_idx - old_idx
    if delta == 1:
        return
    if delta < 0 and force_with_reason:
        return
    if delta > 1:
        raise ApiError(
            f"task {task_id} cannot skip GateFlow stages ({old_status} -> {new_status}); "
            "use sequential moves"
        )
    if delta < 0:
        raise ApiError(
            f"task {task_id} backward stage move requires --force-with-reason ({old_status} -> {new_status})"
        )


def enforce_wip_limits(
    tasks_master: dict[str, Any],
    boards: dict[str, Any],
    milestone_id: str,
    *,
    task_id: str,
    new_status: str,
) -> None:
    if new_status not in {"Prototype Stage 1", "Prototype Stage 2+", "Verification Review"}:
        return

    scoped = [t for t in tasks_master.get("tasks", []) if t.get("milestone_id") == milestone_id]

    prototype_count = sum(
        1
        for t in scoped
        if t.get("status") in {"Prototype Stage 1", "Prototype Stage 2+"}
    )
    verification_count = sum(1 for t in scoped if t.get("status") == "Verification Review")

    prototype_wip_limit, verification_wip_limit = resolve_wip_limits(boards, milestone_id)

    if new_status in {"Prototype Stage 1", "Prototype Stage 2+"} and prototype_count > prototype_wip_limit:
        raise ApiError(
            f"milestone {milestone_id} exceeds prototype WIP limit "
            f"({prototype_count}/{prototype_wip_limit}) when moving {task_id} -> {new_status}"
        )
    if new_status == "Verification Review" and verification_count > verification_wip_limit:
        raise ApiError(
            f"milestone {milestone_id} exceeds verification WIP limit "
            f"({verification_count}/{verification_wip_limit}) when moving {task_id} -> {new_status}"
        )


def _safe_wip_int(value: Any, *, default: int, max_allowed: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        parsed = int(value)
        if parsed < 1:
            return default
        return min(parsed, max_allowed)
    return default


def _prototype_limit_from_wip_map(wip_map: dict[str, Any], default: int) -> int:
    # Allow either an explicit combined key or stage-specific keys.
    combined = wip_map.get("Prototype Combined")
    if combined is not None:
        return _safe_wip_int(
            combined,
            default=default,
            max_allowed=MAX_PROTOTYPE_WIP_LIMIT,
        )

    stage_1 = _safe_wip_int(
        wip_map.get("Prototype Stage 1"),
        default=default,
        max_allowed=MAX_PROTOTYPE_WIP_LIMIT,
    )
    stage_2 = _safe_wip_int(
        wip_map.get("Prototype Stage 2+"),
        default=default,
        max_allowed=MAX_PROTOTYPE_WIP_LIMIT,
    )
    return max(stage_1, stage_2)


def resolve_wip_limits(boards: dict[str, Any], milestone_id: str) -> tuple[int, int]:
    prototype_limit = DEFAULT_PROTOTYPE_WIP_LIMIT
    verification_limit = DEFAULT_VERIFICATION_WIP_LIMIT

    render_defaults = boards.get("render_defaults", {})
    rd_wip = render_defaults.get("wip_limits", {})
    if isinstance(rd_wip, dict):
        prototype_limit = _prototype_limit_from_wip_map(rd_wip, prototype_limit)
        verification_limit = _safe_wip_int(
            rd_wip.get("Verification Review"),
            default=verification_limit,
            max_allowed=MAX_VERIFICATION_WIP_LIMIT,
        )

    default_template = boards.get("default_framework_template")
    template_name = default_template

    for board in boards.get("boards", []):
        if board.get("id") == f"milestone:{milestone_id}":
            template_name = board.get("framework_template", default_template)
            board_wip = board.get("wip_limits")
            if isinstance(board_wip, dict):
                prototype_limit = _prototype_limit_from_wip_map(board_wip, prototype_limit)
                verification_limit = _safe_wip_int(
                    board_wip.get("Verification Review"),
                    default=verification_limit,
                    max_allowed=MAX_VERIFICATION_WIP_LIMIT,
                )
            break

    templates = boards.get("framework_templates", {})
    template = templates.get(template_name, {})
    template_wip = template.get("wip_limits", {})
    if isinstance(template_wip, dict):
        prototype_limit = _prototype_limit_from_wip_map(template_wip, prototype_limit)
        verification_limit = _safe_wip_int(
            template_wip.get("Verification Review"),
            default=verification_limit,
            max_allowed=MAX_VERIFICATION_WIP_LIMIT,
        )

    return prototype_limit, verification_limit


def compute_weighted_cost_score(components: dict[str, Any]) -> float:
    score = 0.0
    for key, weight in COST_COMPONENT_WEIGHTS.items():
        score += float(components[key]) * weight
    return clamp_score(score)


def apply_stage_multiplier(status: str, score: float) -> tuple[float, float]:
    if status in GATEFLOW_STAGE_MULTIPLIERS:
        mult = GATEFLOW_STAGE_MULTIPLIERS[status]
        return clamp_score(score * mult), mult
    # legacy/non-GateFlow statuses: neutral multiplier
    return clamp_score(score), 1.0


def normalize_task_cost(
    task: dict[str, Any],
    *,
    reestimate: bool = False,
    blocked_confidence_drop: bool = False,
) -> None:
    validate_cost_fields(task)

    score = task.get("cost_score")
    components = task.get("cost_components")

    if components is not None and (reestimate or score is None):
        score = compute_weighted_cost_score(components)

    if score is not None:
        score = float(score)
        score, mult = apply_stage_multiplier(task.get("status", ""), score)
        task["cost_score"] = round(score, 2)
        task["stage_multiplier_applied"] = mult
        task["cost_bucket"] = derive_cost_bucket(score)
        task["cost_basis_version"] = COST_BASIS_VERSION

    if blocked_confidence_drop and "cost_confidence" in task and isinstance(task["cost_confidence"], (int, float)):
        task["cost_confidence"] = round(max(0.0, float(task["cost_confidence"]) - 0.15), 2)


def allowed_task_statuses(boards: dict[str, Any]) -> set[str]:
    statuses = set(LEGACY_TASK_STATUS)
    for template in boards.get("framework_templates", {}).values():
        for status in template.get("status_columns", []):
            statuses.add(str(status))
    for status in boards.get("render_defaults", {}).get("status_columns", []):
        statuses.add(str(status))
    return statuses


def validate_board_definitions(boards: dict[str, Any]) -> None:
    board_types = boards.get("board_types", {})
    templates = boards.get("framework_templates", {})
    default_template = boards.get("default_framework_template")
    if default_template not in templates:
        raise ApiError("default_framework_template must reference an existing framework template")

    seen: set[str] = set()
    for board in boards.get("boards", []):
        bid = board.get("id")
        if not bid:
            raise ApiError("board id is required")
        if bid in seen:
            raise ApiError(f"duplicate board id: {bid}")
        seen.add(bid)
        btype = board.get("type")
        if btype not in board_types:
            raise ApiError(f"board {bid} has unknown type: {btype}")
        template = board.get("framework_template", default_template)
        if template not in templates:
            raise ApiError(f"board {bid} has unknown framework_template: {template}")


def validate_milestone_task_links(
    schedule: dict[str, Any], tasks_master: dict[str, Any], tasks_archived: dict[str, Any]
) -> None:
    active = index_by_id(tasks_master.get("tasks", []))
    archived = index_by_id(tasks_archived.get("tasks", []))

    for milestone in schedule.get("milestones", []):
        mid = milestone.get("id", "<unknown>")
        task_ids = milestone.get("task_ids")
        if task_ids is None:
            task_ids = []
            milestone["task_ids"] = task_ids
        if not isinstance(task_ids, list):
            raise ApiError(f"{mid}: task_ids must be a list")
        for tid in task_ids:
            if tid in active:
                if active[tid].get("milestone_id") != mid:
                    raise ApiError(
                        f"{mid}: task {tid} belongs to {active[tid].get('milestone_id')} in tasks_master"
                    )
                continue
            if tid in archived:
                if archived[tid].get("milestone_id") != mid:
                    raise ApiError(
                        f"{mid}: task {tid} belongs to {archived[tid].get('milestone_id')} in tasks_archived"
                    )
                continue
            raise ApiError(f"{mid}: task {tid} missing in tasks_master and tasks_archived")


def validate_cross_refs(
    schedule: dict[str, Any], tasks_master: dict[str, Any], tasks_archived: dict[str, Any], boards: dict[str, Any], backlog: dict[str, Any]
) -> None:
    milestones = index_by_id(schedule.get("milestones", []))
    board_ids = {b["id"] for b in boards.get("boards", [])}
    active = index_by_id(tasks_master.get("tasks", []))
    archived = index_by_id(tasks_archived.get("tasks", []))
    all_task_ids = set(active) | set(archived)

    for mid in milestones:
        if not MILESTONE_ID_RE.match(mid):
            raise ApiError(f"invalid milestone id format: {mid}")
        validate_milestone_descriptions(milestones[mid])
        if "closeout_criteria" in milestones[mid]:
            validate_closeout_criteria(milestones[mid], required=False)
        if "ci_required_checks" in milestones[mid]:
            validate_ci_required_checks(milestones[mid], required=False)

    validate_board_definitions(boards)
    statuses = allowed_task_statuses(boards)

    for task in tasks_master.get("tasks", []):
        tid = task.get("id", "")
        if not TASK_ID_RE.match(tid):
            raise ApiError(f"invalid task id format: {tid}")
        if task.get("milestone_id") not in milestones:
            raise ApiError(f"task {tid} references unknown milestone_id {task.get('milestone_id')}")
        if task.get("status") not in statuses:
            raise ApiError(f"task {tid} has invalid status {task.get('status')}")
        normalize_task_type_and_title(task)
        validate_board_refs(task, board_ids)
        deps = task.get("depends_on", [])
        if not isinstance(deps, list):
            raise ApiError(f"task {tid} depends_on must be a list")
        for dep in deps:
            validate_dep_id_format(tid, dep)
        validate_task_notes(task)
        validate_cost_fields(task)

    validate_milestone_task_links(schedule, tasks_master, tasks_archived)
    validate_backlog_registry(backlog, set(milestones), all_task_ids)


def create_milestone(schedule: dict[str, Any], body: dict[str, Any], task_ids_all: set[str]) -> str:
    required = {
        "id",
        "name",
        "emoji",
        "start_week",
        "end_week",
        "status",
        "success_criteria",
        "closeout_criteria",
        "ci_required_checks",
    }
    missing = sorted(required - set(body))
    if missing:
        raise ApiError(f"POST /milestones missing fields: {', '.join(missing)}")
    mid = body["id"]
    if not MILESTONE_ID_RE.match(mid):
        raise ApiError("milestone id must match <1-3 uppercase letters>-### (example: A-001, FR-004, APU-020)")
    milestones = schedule.get("milestones", [])
    if any(m["id"] == mid for m in milestones):
        raise ApiError(f"milestone already exists: {mid}")
    if body["status"] not in ALLOWED_MILESTONE_STATUS:
        raise ApiError(f"invalid milestone status: {body['status']}")
    if not isinstance(body.get("success_criteria"), list) or not body["success_criteria"]:
        raise ApiError("milestone success_criteria must be a non-empty list")
    for idx, item in enumerate(body["success_criteria"]):
        if not isinstance(item, str) or not item.strip():
            raise ApiError(f"milestone success_criteria[{idx}] must be a non-empty string")
    body.setdefault("descriptions", [])
    validate_milestone_descriptions(body)
    validate_closeout_criteria(body, required=True)
    validate_ci_required_checks(body, required=True)
    body.setdefault("task_ids", [])
    if not isinstance(body["task_ids"], list):
        raise ApiError("milestone task_ids must be a list")
    for tid in body.get("task_ids", []):
        if tid not in task_ids_all:
            raise ApiError(f"milestone task_id not found in task ledgers: {tid}")
    if body.get("status") == "Complete":
        validate_closeout_packet(mid)
    milestones.append(body)
    return f"created milestone {mid}"


def patch_milestone(schedule: dict[str, Any], milestone_id: str, body: dict[str, Any], task_ids_all: set[str]) -> str:
    milestones = index_by_id(schedule.get("milestones", []))
    if milestone_id not in milestones:
        raise ApiError(f"milestone not found: {milestone_id}")
    if "id" in body and body["id"] != milestone_id:
        raise ApiError("milestone id is immutable")
    row = milestones[milestone_id]
    old_status = row.get("status")
    for k, v in body.items():
        row[k] = v
    if row.get("status") not in ALLOWED_MILESTONE_STATUS:
        raise ApiError(f"invalid milestone status: {row.get('status')}")
    validate_milestone_descriptions(row)
    if "success_criteria" in row:
        if not isinstance(row["success_criteria"], list) or not row["success_criteria"]:
            raise ApiError("milestone success_criteria must be a non-empty list")
        for idx, item in enumerate(row["success_criteria"]):
            if not isinstance(item, str) or not item.strip():
                raise ApiError(f"milestone success_criteria[{idx}] must be a non-empty string")
    require_closeout = row.get("status") in {"In Progress", "Complete"}
    validate_closeout_criteria(row, required=require_closeout)
    validate_ci_required_checks(row, required=require_closeout)
    row.setdefault("task_ids", [])
    if not isinstance(row.get("task_ids"), list):
        raise ApiError("milestone task_ids must be a list")
    for tid in row.get("task_ids", []):
        if tid not in task_ids_all:
            raise ApiError(f"milestone task_id not found in task ledgers: {tid}")
    if old_status != "Complete" and row.get("status") == "Complete":
        validate_closeout_packet(milestone_id)
    return f"updated milestone {milestone_id}"


def delete_milestone(
    schedule: dict[str, Any], tasks_master: dict[str, Any], milestone_id: str, force: bool
) -> str:
    milestones = schedule.get("milestones", [])
    found = next((m for m in milestones if m["id"] == milestone_id), None)
    if not found:
        raise ApiError(f"milestone not found: {milestone_id}")
    active_linked = [t["id"] for t in tasks_master.get("tasks", []) if t.get("milestone_id") == milestone_id]
    if active_linked and not force:
        raise ApiError(
            f"milestone {milestone_id} has active tasks: {', '.join(active_linked)}; "
            "delete tasks first or use --force"
        )
    schedule["milestones"] = [m for m in milestones if m["id"] != milestone_id]
    return f"deleted milestone {milestone_id}"


def create_task(
    tasks_master: dict[str, Any],
    tasks_archived: dict[str, Any],
    schedule: dict[str, Any],
    boards: dict[str, Any],
    body: dict[str, Any],
    all_task_ids: set[str],
    *,
    reestimate_cost: bool = False,
) -> str:
    required = {"id", "title", "milestone_id", "status", "depends_on", "board_refs"}
    missing = sorted(required - set(body))
    if missing:
        raise ApiError(f"POST /tasks missing fields: {', '.join(missing)}")
    tid = body["id"]
    if tid in all_task_ids:
        raise ApiError(f"task id already exists: {tid}")
    if not TASK_ID_RE.match(tid):
        raise ApiError("invalid task id format")
    milestone_ids = {m["id"] for m in schedule.get("milestones", [])}
    if body["milestone_id"] not in milestone_ids:
        raise ApiError(f"unknown milestone_id: {body['milestone_id']}")
    normalize_task_type_and_title(body)
    enforce_closeout_harness_first(
        schedule,
        tasks_master,
        tasks_archived,
        milestone_id=body["milestone_id"],
        candidate_task_type=body.get("task_type", "standard"),
    )
    if body["status"] not in allowed_task_statuses(boards):
        raise ApiError(f"invalid task status: {body['status']}")
    board_ids = {b["id"] for b in boards.get("boards", [])}
    validate_board_refs(body, board_ids)
    deps = body.get("depends_on", [])
    if not isinstance(deps, list):
        raise ApiError("depends_on must be a list")
    for dep in deps:
        validate_dep_id_format(tid, dep)
    validate_task_notes(body)
    normalize_task_cost(body, reestimate=reestimate_cost)
    validate_done_gate_requirements(body, require=body.get("status") == "Done")

    if body.get("status") in {"Prototype Stage 1", "Prototype Stage 2+", "Verification Review"}:
        preview_master = {"tasks": list(tasks_master.get("tasks", [])) + [body]}
        enforce_wip_limits(
            preview_master,
            boards,
            body["milestone_id"],
            task_id=tid,
            new_status=body.get("status", ""),
        )

    tasks_master.setdefault("tasks", []).append(body)
    # Maintain milestone task index contract.
    milestone = next(m for m in schedule["milestones"] if m["id"] == body["milestone_id"])
    if tid not in milestone["task_ids"]:
        milestone["task_ids"].append(tid)
    return f"created task {tid}"


def patch_task(
    tasks_master: dict[str, Any],
    tasks_archived: dict[str, Any],
    schedule: dict[str, Any],
    boards: dict[str, Any],
    task_id: str,
    body: dict[str, Any],
    all_task_ids: set[str],
    *,
    reestimate_cost: bool = False,
    force_with_reason: str | None = None,
) -> str:
    rows = index_by_id(tasks_master.get("tasks", []))
    if task_id not in rows:
        raise ApiError(f"task not found in tasks_master: {task_id}")
    if "id" in body and body["id"] != task_id:
        raise ApiError("task id is immutable")

    row = rows[task_id]
    old_mid = row.get("milestone_id")
    old_status = row.get("status")
    for k, v in body.items():
        row[k] = v
    normalize_task_type_and_title(row)

    milestone_ids = {m["id"] for m in schedule.get("milestones", [])}
    if row.get("milestone_id") not in milestone_ids:
        raise ApiError(f"unknown milestone_id: {row.get('milestone_id')}")
    enforce_closeout_harness_first(
        schedule,
        tasks_master,
        tasks_archived,
        milestone_id=row.get("milestone_id", ""),
        candidate_task_type=row.get("task_type", "standard"),
    )
    if row.get("status") not in allowed_task_statuses(boards):
        raise ApiError(f"invalid task status: {row.get('status')}")
    board_ids = {b["id"] for b in boards.get("boards", [])}
    validate_board_refs(row, board_ids)
    if not isinstance(row.get("depends_on", []), list):
        raise ApiError("depends_on must be a list")
    for dep in row.get("depends_on", []):
        validate_dep_id_format(task_id, dep)
    validate_task_notes(row)
    if row.get("status") != old_status:
        enforce_gateflow_status_transition(
            task_id,
            old_status or "",
            row.get("status", ""),
            force_with_reason=force_with_reason,
        )
        enforce_wip_limits(
            tasks_master,
            boards,
            row.get("milestone_id", ""),
            task_id=task_id,
            new_status=row.get("status", ""),
        )
    became_blocked = old_status != "Blocked" and row.get("status") == "Blocked"
    normalize_task_cost(row, reestimate=reestimate_cost, blocked_confidence_drop=became_blocked)
    became_done = old_status != "Done" and row.get("status") == "Done"
    validate_done_gate_requirements(row, require=became_done)

    # If milestone changed, move index link.
    new_mid = row["milestone_id"]
    if new_mid != old_mid:
        old_m = next(m for m in schedule["milestones"] if m["id"] == old_mid)
        old_m["task_ids"] = [tid for tid in old_m["task_ids"] if tid != task_id]
        new_m = next(m for m in schedule["milestones"] if m["id"] == new_mid)
        if task_id not in new_m["task_ids"]:
            new_m["task_ids"].append(task_id)
    return f"updated task {task_id}"


def delete_task(
    tasks_master: dict[str, Any],
    tasks_archived: dict[str, Any],
    task_id: str,
    force_remove_deps: bool,
) -> str:
    active = tasks_master.get("tasks", [])
    row = next((t for t in active if t["id"] == task_id), None)
    if row is None:
        raise ApiError(f"task not found in tasks_master: {task_id}")

    dependents = [t["id"] for t in active if task_id in t.get("depends_on", [])]
    if dependents and not force_remove_deps:
        raise ApiError(
            f"task {task_id} is depended on by: {', '.join(dependents)}; "
            "use --force-remove-deps to remove those references"
        )
    if force_remove_deps:
        for t in active:
            if task_id in t.get("depends_on", []):
                t["depends_on"] = [d for d in t["depends_on"] if d != task_id]

    active.remove(row)
    archived_row = copy.deepcopy(row)
    archived_row["status"] = "Archived"
    archived_row["archived_on"] = dt.date.today().isoformat()
    tasks_archived.setdefault("tasks", []).append(archived_row)
    return f"archived task {task_id}"


def create_board(boards: dict[str, Any], body: dict[str, Any]) -> str:
    required = {"id", "title", "type", "source_filter"}
    missing = sorted(required - set(body))
    if missing:
        raise ApiError(f"POST /boards missing fields: {', '.join(missing)}")
    existing = {b["id"] for b in boards.get("boards", [])}
    if body["id"] in existing:
        raise ApiError(f"board already exists: {body['id']}")
    boards.setdefault("boards", []).append(body)
    validate_board_definitions(boards)
    return f"created board {body['id']}"


def patch_board(boards: dict[str, Any], board_id: str, body: dict[str, Any]) -> str:
    rows = index_by_id(boards.get("boards", []))
    if board_id not in rows:
        raise ApiError(f"board not found: {board_id}")
    if "id" in body and body["id"] != board_id:
        raise ApiError("board id is immutable")
    row = rows[board_id]
    for k, v in body.items():
        row[k] = v
    validate_board_definitions(boards)
    return f"updated board {board_id}"


def delete_board(boards: dict[str, Any], board_id: str) -> str:
    before = len(boards.get("boards", []))
    boards["boards"] = [b for b in boards.get("boards", []) if b.get("id") != board_id]
    if len(boards["boards"]) == before:
        raise ApiError(f"board not found: {board_id}")
    validate_board_definitions(boards)
    return f"deleted board {board_id}"


def create_framework(boards: dict[str, Any], name: str, body: dict[str, Any]) -> str:
    templates = boards.setdefault("framework_templates", {})
    if name in templates:
        raise ApiError(f"framework already exists: {name}")
    required = {"description", "status_columns"}
    missing = sorted(required - set(body))
    if missing:
        raise ApiError(f"POST /frameworks/{{name}} missing fields: {', '.join(missing)}")
    templates[name] = body
    validate_board_definitions(boards)
    return f"created framework {name}"


def patch_framework(boards: dict[str, Any], name: str, body: dict[str, Any]) -> str:
    templates = boards.setdefault("framework_templates", {})
    if name not in templates:
        raise ApiError(f"framework not found: {name}")
    row = templates[name]
    for k, v in body.items():
        row[k] = v
    validate_board_definitions(boards)
    return f"updated framework {name}"


def delete_framework(boards: dict[str, Any], name: str) -> str:
    if boards.get("default_framework_template") == name:
        raise ApiError("cannot delete default framework template")
    templates = boards.setdefault("framework_templates", {})
    if name not in templates:
        raise ApiError(f"framework not found: {name}")
    del templates[name]
    validate_board_definitions(boards)
    return f"deleted framework {name}"


def validate_backlog_item(
    item: dict[str, Any],
    milestone_ids: set[str],
    task_ids: set[str],
) -> None:
    bid = item.get("id", "")
    if not BACKLOG_ID_RE.match(str(bid)):
        raise ApiError(f"invalid backlog id format: {bid}")
    if not item.get("title"):
        raise ApiError(f"backlog {bid} missing title")
    status = item.get("status")
    if status not in BACKLOG_STATUS:
        raise ApiError(f"backlog {bid} invalid status: {status}")
    bucket = item.get("bucket")
    if bucket not in BACKLOG_BUCKETS:
        raise ApiError(f"backlog {bid} invalid bucket: {bucket}")
    mid = item.get("source_milestone_id")
    if mid is not None and mid not in milestone_ids:
        raise ApiError(f"backlog {bid} unknown source_milestone_id: {mid}")
    tid = item.get("task_ref")
    if tid is not None and tid not in task_ids:
        raise ApiError(f"backlog {bid} unknown task_ref: {tid}")


def validate_backlog_registry(
    backlog: dict[str, Any],
    milestone_ids: set[str],
    task_ids: set[str],
) -> None:
    seen: set[str] = set()
    for item in backlog.get("items", []):
        bid = item.get("id")
        if bid in seen:
            raise ApiError(f"duplicate backlog id: {bid}")
        seen.add(bid)
        validate_backlog_item(item, milestone_ids, task_ids)


def create_backlog_item(backlog: dict[str, Any], body: dict[str, Any], milestone_ids: set[str], task_ids: set[str]) -> str:
    required = {"id", "title", "status", "bucket"}
    missing = sorted(required - set(body))
    if missing:
        raise ApiError(f"POST /backlog missing fields: {', '.join(missing)}")
    validate_backlog_item(body, milestone_ids, task_ids)
    if any(i.get("id") == body["id"] for i in backlog.get("items", [])):
        raise ApiError(f"backlog item already exists: {body['id']}")
    backlog.setdefault("items", []).append(body)
    return f"created backlog item {body['id']}"


def patch_backlog_item(backlog: dict[str, Any], item_id: str, body: dict[str, Any], milestone_ids: set[str], task_ids: set[str]) -> str:
    rows = index_by_id(backlog.get("items", []))
    if item_id not in rows:
        raise ApiError(f"backlog item not found: {item_id}")
    if "id" in body and body["id"] != item_id:
        raise ApiError("backlog id is immutable")
    row = rows[item_id]
    for k, v in body.items():
        row[k] = v
    validate_backlog_item(row, milestone_ids, task_ids)
    return f"updated backlog item {item_id}"


def delete_backlog_item(backlog: dict[str, Any], item_id: str) -> str:
    before = len(backlog.get("items", []))
    backlog["items"] = [i for i in backlog.get("items", []) if i.get("id") != item_id]
    if len(backlog["items"]) == before:
        raise ApiError(f"backlog item not found: {item_id}")
    return f"deleted backlog item {item_id}"


def handle_get(
    resource: str,
    ident: str | None,
    schedule: dict[str, Any],
    tasks_master: dict[str, Any],
    boards: dict[str, Any],
    backlog: dict[str, Any],
) -> int:
    if resource == "milestones":
        if ident is None:
            print(json.dumps(schedule.get("milestones", []), indent=2))
            return 0
        row = next((m for m in schedule.get("milestones", []) if m["id"] == ident), None)
        if row is None:
            raise ApiError(f"milestone not found: {ident}")
        print(json.dumps(row, indent=2))
        return 0

    if resource == "tasks":
        if ident is None:
            print(json.dumps(tasks_master.get("tasks", []), indent=2))
            return 0
        row = next((t for t in tasks_master.get("tasks", []) if t["id"] == ident), None)
        if row is None:
            raise ApiError(f"task not found in tasks_master: {ident}")
        print(json.dumps(row, indent=2))
        return 0

    if resource == "boards":
        if ident is None:
            print(json.dumps(boards.get("boards", []), indent=2))
            return 0
        row = next((b for b in boards.get("boards", []) if b.get("id") == ident), None)
        if row is None:
            raise ApiError(f"board not found: {ident}")
        print(json.dumps(row, indent=2))
        return 0

    if resource == "backlog":
        if ident is None:
            print(json.dumps(backlog.get("items", []), indent=2))
            return 0
        row = next((i for i in backlog.get("items", []) if i.get("id") == ident), None)
        if row is None:
            raise ApiError(f"backlog item not found: {ident}")
        print(json.dumps(row, indent=2))
        return 0

    if ident is None:
        payload = {
            "default_framework_template": boards.get("default_framework_template"),
            "framework_templates": boards.get("framework_templates", {}),
        }
        print(json.dumps(payload, indent=2))
        return 0
    templates = boards.get("framework_templates", {})
    row = templates.get(ident)
    if row is None:
        raise ApiError(f"framework not found: {ident}")
    print(json.dumps(row, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Planning endpoint-style mutator.")
    parser.add_argument("method", help="GET|POST|PATCH|DELETE")
    parser.add_argument("path", help="Endpoint path like /milestones, /tasks/T-1101, /boards/{id}, /frameworks/{name}, /backlog/{id}")
    parser.add_argument("--body", help="Inline JSON body")
    parser.add_argument("--body-file", help="Path to JSON body file")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry-run)")
    parser.add_argument("--force", action="store_true", help="Allow risky operation on milestone delete")
    parser.add_argument(
        "--force-remove-deps",
        action="store_true",
        help="When deleting task, remove dependency links from active tasks",
    )
    parser.add_argument(
        "--reestimate-cost",
        action="store_true",
        help="Recompute task cost_score from cost_components and apply stage multiplier for task POST/PATCH.",
    )
    parser.add_argument(
        "--force-with-reason",
        help="Explicit override reason for guarded operations (for example backward GateFlow moves).",
    )
    args = parser.parse_args()

    method = args.method.upper()
    if method not in METHODS:
        raise ApiError(f"unsupported method: {method}")
    resource, ident = split_path(args.path)

    schedule = load_json(SCHEDULE_PATH)
    tasks_master = load_json(TASKS_MASTER_PATH)
    tasks_archived = load_json(TASKS_ARCHIVED_PATH)
    boards = load_json(BOARDS_PATH)
    backlog = load_json(BACKLOG_PATH)
    body = parse_body(args)

    if method == "GET":
        return handle_get(resource, ident, schedule, tasks_master, boards, backlog)

    all_task_ids = {
        t["id"] for t in tasks_master.get("tasks", [])
    } | {t["id"] for t in tasks_archived.get("tasks", [])}
    milestone_ids = {m["id"] for m in schedule.get("milestones", [])}

    summary = ""
    if resource == "milestones":
        if method == "POST":
            if ident is not None:
                raise ApiError("POST /milestones must not include id in path")
            summary = create_milestone(schedule, body, all_task_ids)
        elif method == "PATCH":
            if ident is None:
                raise ApiError("PATCH /milestones/{id} requires id in path")
            summary = patch_milestone(schedule, ident, body, all_task_ids)
        elif method == "DELETE":
            if ident is None:
                raise ApiError("DELETE /milestones/{id} requires id in path")
            summary = delete_milestone(schedule, tasks_master, ident, force=args.force)
        else:
            raise ApiError(f"unsupported method for milestones: {method}")
    elif resource == "tasks":
        if method == "POST":
            if ident is not None:
                raise ApiError("POST /tasks must not include id in path")
            summary = create_task(
                tasks_master,
                tasks_archived,
                schedule,
                boards,
                body,
                all_task_ids,
                reestimate_cost=args.reestimate_cost,
            )
        elif method == "PATCH":
            if ident is None:
                raise ApiError("PATCH /tasks/{id} requires id in path")
            summary = patch_task(
                tasks_master,
                tasks_archived,
                schedule,
                boards,
                ident,
                body,
                all_task_ids,
                reestimate_cost=args.reestimate_cost,
                force_with_reason=args.force_with_reason,
            )
        elif method == "DELETE":
            if ident is None:
                raise ApiError("DELETE /tasks/{id} requires id in path")
            summary = delete_task(tasks_master, tasks_archived, ident, args.force_remove_deps)
        else:
            raise ApiError(f"unsupported method for tasks: {method}")
    elif resource == "boards":
        if method == "POST":
            if ident is not None:
                raise ApiError("POST /boards must not include id in path")
            summary = create_board(boards, body)
        elif method == "PATCH":
            if ident is None:
                raise ApiError("PATCH /boards/{id} requires id in path")
            summary = patch_board(boards, ident, body)
        elif method == "DELETE":
            if ident is None:
                raise ApiError("DELETE /boards/{id} requires id in path")
            summary = delete_board(boards, ident)
        else:
            raise ApiError(f"unsupported method for boards: {method}")
    elif resource == "backlog":
        if method == "POST":
            if ident is not None:
                raise ApiError("POST /backlog must not include id in path")
            summary = create_backlog_item(backlog, body, milestone_ids, all_task_ids)
        elif method == "PATCH":
            if ident is None:
                raise ApiError("PATCH /backlog/{id} requires id in path")
            summary = patch_backlog_item(backlog, ident, body, milestone_ids, all_task_ids)
        elif method == "DELETE":
            if ident is None:
                raise ApiError("DELETE /backlog/{id} requires id in path")
            summary = delete_backlog_item(backlog, ident)
        else:
            raise ApiError(f"unsupported method for backlog: {method}")
    else:
        if method == "POST":
            if ident is None:
                raise ApiError("POST /frameworks/{name} requires name in path")
            summary = create_framework(boards, ident, body)
        elif method == "PATCH":
            if ident is None:
                if "default_framework_template" not in body:
                    raise ApiError("PATCH /frameworks requires default_framework_template in body")
                boards["default_framework_template"] = body["default_framework_template"]
                validate_board_definitions(boards)
                summary = f"updated default framework {boards['default_framework_template']}"
            else:
                summary = patch_framework(boards, ident, body)
        elif method == "DELETE":
            if ident is None:
                raise ApiError("DELETE /frameworks/{name} requires name in path")
            summary = delete_framework(boards, ident)
        else:
            raise ApiError(f"unsupported method for frameworks: {method}")

    validate_cross_refs(schedule, tasks_master, tasks_archived, boards, backlog)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"mode: {mode}")
    print(summary)
    if args.apply:
        branch = current_git_branch()
        if branch != "main":
            raise ApiError(
                "planning_api --apply is restricted to main branch only; "
                f"current branch is '{branch}'. Run this write on main, then sync milestone branches."
            )
        write_json(SCHEDULE_PATH, schedule)
        write_json(TASKS_MASTER_PATH, tasks_master)
        write_json(TASKS_ARCHIVED_PATH, tasks_archived)
        write_json(BOARDS_PATH, boards)
        write_json(BACKLOG_PATH, backlog)
        regenerate_gantt_artifacts()
        print("write: ok")
        print(f"regenerated: {GANTT_MD_PATH}, {GANTT_PNG_PATH}")
    else:
        print("write: skipped (use --apply)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
