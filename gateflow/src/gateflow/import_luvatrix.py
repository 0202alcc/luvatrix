from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from gateflow.io import read_json, write_json
from gateflow.scaffold import scaffold_workspace


@dataclass(frozen=True)
class DriftFinding:
    code: str
    path: str
    message: str
    remediation: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "path": self.path,
            "message": self.message,
            "remediation": self.remediation,
        }


@dataclass(frozen=True)
class DriftReport:
    root: Path
    findings: list[DriftFinding]

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "status": "clean" if not self.findings else "drifted",
            "mismatch_count": len(self.findings),
            "mismatches": [finding.as_dict() for finding in self.findings],
        }


@dataclass(frozen=True)
class ImportResult:
    root: Path
    milestone_count: int
    task_count: int
    board_count: int
    backlog_count: int
    closeout_count: int
    drift_report: DriftReport

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "milestones": self.milestone_count,
            "tasks": self.task_count,
            "boards": self.board_count,
            "backlog_items": self.backlog_count,
            "closeout_packets": self.closeout_count,
            "drift": self.drift_report.as_dict(),
        }


def import_luvatrix(path: Path) -> ImportResult:
    root = path.resolve()
    scaffold_workspace(root=root, profile="minimal")
    stamped = date.today().isoformat()

    payload = _build_expected_payload(root, stamped)
    _write_expected_payload(root, payload)
    report = check_luvatrix_import_drift(root)

    milestones = list(payload["milestones.json"].get("items", []))
    tasks = list(payload["tasks.json"].get("items", []))
    boards = list(payload["boards.json"].get("items", []))
    backlog_items = list(payload["backlog.json"].get("items", []))
    closeout_map = payload["closeout"]
    return ImportResult(
        root=root,
        milestone_count=len(milestones),
        task_count=len(tasks),
        board_count=len(boards),
        backlog_count=len(backlog_items),
        closeout_count=len(closeout_map),
        drift_report=report,
    )


def check_luvatrix_import_drift(path: Path) -> DriftReport:
    root = path.resolve()
    stamped = date.today().isoformat()
    expected = _build_expected_payload(root, stamped)
    findings: list[DriftFinding] = []

    gateflow_dir = root / ".gateflow"
    json_files = ["config.json", "milestones.json", "tasks.json", "boards.json", "backlog.json"]
    for name in json_files:
        target = gateflow_dir / name
        rel_path = str(target.relative_to(root))
        if not target.exists():
            findings.append(
                DriftFinding(
                    code="MISSING_FILE",
                    path=rel_path,
                    message="Required GateFlow ledger file is missing.",
                    remediation="Run `gateflow import-luvatrix --path <repo>` to regenerate this file.",
                )
            )
            continue
        actual = read_json(target)
        expected_payload = expected[name]
        if _normalize_json_for_drift(actual) != _normalize_json_for_drift(expected_payload):
            findings.append(
                DriftFinding(
                    code="CONTENT_MISMATCH",
                    path=rel_path,
                    message="Ledger content differs from deterministic import mapping.",
                    remediation="Re-run `gateflow import-luvatrix --path <repo>` and commit regenerated ledgers.",
                )
            )

    expected_closeout: dict[str, str] = expected["closeout"]
    closeout_dir = gateflow_dir / "closeout"
    existing_closeout = set(path.name for path in closeout_dir.glob("*_closeout.md")) if closeout_dir.exists() else set()

    for filename in sorted(expected_closeout.keys()):
        target = closeout_dir / filename
        rel_path = str(target.relative_to(root))
        if not target.exists():
            findings.append(
                DriftFinding(
                    code="MISSING_FILE",
                    path=rel_path,
                    message="Expected closeout packet is missing.",
                    remediation="Run `gateflow import-luvatrix --path <repo>` to sync closeout packets.",
                )
            )
            continue
        actual_text = target.read_text(encoding="utf-8")
        if actual_text != expected_closeout[filename]:
            findings.append(
                DriftFinding(
                    code="CONTENT_MISMATCH",
                    path=rel_path,
                    message="Closeout packet content differs from deterministic import output.",
                    remediation="Replace the file using `gateflow import-luvatrix --path <repo>` output.",
                )
            )

    for filename in sorted(existing_closeout - set(expected_closeout.keys())):
        rel_path = str((closeout_dir / filename).relative_to(root))
        findings.append(
            DriftFinding(
                code="EXTRA_FILE",
                path=rel_path,
                message="Unexpected closeout packet exists in destination.",
                remediation="Remove the extra packet or align source planning closeout files before re-import.",
            )
        )

    ordered = sorted(findings, key=lambda item: (item.path, item.code, item.message))
    return DriftReport(root=root, findings=ordered)


def _build_expected_payload(root: Path, stamped: str) -> dict[str, Any]:
    milestones_payload = read_json(root / "ops" / "planning" / "gantt" / "milestone_schedule.json")
    tasks_payload = read_json(root / "ops" / "planning" / "agile" / "tasks_master.json")
    archived_tasks_payload = read_json(root / "ops" / "planning" / "agile" / "tasks_archived.json")
    boards_payload = read_json(root / "ops" / "planning" / "agile" / "boards_registry.json")
    backlog_payload = read_json(root / "ops" / "planning" / "agile" / "backlog_misc.json")

    milestones = list(milestones_payload.get("milestones", []))
    tasks = _merge_tasks(
        active=list(tasks_payload.get("tasks", [])),
        archived=list(archived_tasks_payload.get("tasks", [])),
    )
    boards = list(boards_payload.get("boards", []))
    backlog_items = list(backlog_payload.get("items", []))
    closeout_map = _expected_closeout_packets(root, milestones)

    scaffold_defaults = read_json(root / ".gateflow" / "config.json") if (root / ".gateflow" / "config.json").exists() else {}
    frameworks = []
    for name in sorted((boards_payload.get("framework_templates") or {}).keys()):
        template = dict((boards_payload.get("framework_templates") or {}).get(name) or {})
        template["name"] = name
        frameworks.append(template)

    config_payload = dict(scaffold_defaults)
    config_payload["updated_at"] = stamped
    config_payload["source"] = {
        "kind": "luvatrix_ops_planning",
        "path": str(root / "ops" / "planning"),
    }
    config_payload["defaults"] = {
        "framework": str(boards_payload.get("default_framework_template", "gateflow_v1")),
        "warning_mode": str(config_payload.get("defaults", {}).get("warning_mode", "warn")),
    }
    config_payload["frameworks"] = frameworks
    config_payload["render_defaults"] = boards_payload.get("render_defaults", {})
    config_payload["board_types"] = boards_payload.get("board_types", {})

    return {
        "config.json": config_payload,
        "milestones.json": {
            "items": milestones,
            "title": milestones_payload.get("title"),
            "baseline_start_date": milestones_payload.get("baseline_start_date"),
            "milestone_id_schema": milestones_payload.get("milestone_id_schema"),
            "updated_at": stamped,
            "version": "gateflow_v1",
        },
        "tasks.json": {
            "items": tasks,
            "schema_version": tasks_payload.get("schema_version"),
            "status_values": tasks_payload.get("status_values"),
            "legacy_status_values": tasks_payload.get("legacy_status_values"),
            "updated_at": stamped,
            "version": "gateflow_v1",
        },
        "boards.json": {
            "items": boards,
            "schema_version": boards_payload.get("schema_version"),
            "default_framework_template": boards_payload.get("default_framework_template"),
            "framework_templates": boards_payload.get("framework_templates"),
            "render_defaults": boards_payload.get("render_defaults"),
            "board_types": boards_payload.get("board_types"),
            "updated_at": stamped,
            "version": "gateflow_v1",
        },
        "backlog.json": {
            "items": backlog_items,
            "schema_version": backlog_payload.get("schema_version"),
            "status_values": backlog_payload.get("status_values"),
            "bucket_values": backlog_payload.get("bucket_values"),
            "updated_at": stamped,
            "version": "gateflow_v1",
        },
        "closeout": closeout_map,
    }


def _write_expected_payload(root: Path, payload: dict[str, Any]) -> None:
    gateflow_dir = root / ".gateflow"
    gateflow_dir.mkdir(parents=True, exist_ok=True)
    closeout_dir = gateflow_dir / "closeout"
    closeout_dir.mkdir(parents=True, exist_ok=True)

    for name in ("config.json", "milestones.json", "tasks.json", "boards.json", "backlog.json"):
        write_json(gateflow_dir / name, payload[name])

    closeout_map: dict[str, str] = payload["closeout"]
    for filename in sorted(closeout_map.keys()):
        (closeout_dir / filename).write_text(closeout_map[filename], encoding="utf-8")


def _expected_closeout_packets(root: Path, milestones: list[dict[str, Any]]) -> dict[str, str]:
    src_dir = root / "ops" / "planning" / "closeout"
    source_text: dict[str, str] = {}
    if src_dir.exists():
        for path in sorted(src_dir.glob("*_closeout.md")):
            source_text[path.name] = path.read_text(encoding="utf-8")

    closeout_map = dict(source_text)
    required_ids = _required_closeout_milestone_ids(milestones)
    for milestone_id in required_ids:
        filename = f"{milestone_id.lower()}_closeout.md"
        if filename not in closeout_map:
            closeout_map[filename] = _placeholder_closeout_text(milestone_id)
    return {key: closeout_map[key] for key in sorted(closeout_map.keys())}


def _merge_tasks(*, active: list[dict[str, Any]], archived: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for task in archived:
        task_id = str(task.get("id", "")).strip()
        if task_id:
            merged[task_id] = dict(task)
    for task in active:
        task_id = str(task.get("id", "")).strip()
        if task_id:
            merged[task_id] = dict(task)
    for task in list(merged.values()):
        deps = task.get("depends_on", [])
        if not isinstance(deps, list):
            continue
        for dep in deps:
            dep_id = str(dep).strip()
            if not dep_id or dep_id in merged:
                continue
            merged[dep_id] = {
                "id": dep_id,
                "title": f"[IMPORTED PLACEHOLDER] Missing dependency task {dep_id}",
                "status": "Blocked",
                "depends_on": [],
                "task_type": "placeholder",
                "imported_placeholder": True,
                "notes": [
                    "Auto-generated during import-luvatrix because source planning references a missing dependency task.",
                    "Remediation: add canonical task record in ops/planning/agile/tasks_master.json or tasks_archived.json, then re-import.",
                ],
            }
    return [merged[key] for key in sorted(merged.keys())]


def _required_closeout_milestone_ids(milestones: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for milestone in milestones:
        milestone_id = str(milestone.get("id", "")).strip()
        if not milestone_id:
            continue
        if milestone.get("status") == "Complete" or "closeout_criteria" in milestone:
            ids.append(milestone_id)
    return sorted(set(ids))


def _placeholder_closeout_text(milestone_id: str) -> str:
    return "\n".join(
        [
            "# Objective Summary",
            f"- Auto-generated placeholder for `{milestone_id}` during `import-luvatrix`.",
            "",
            "# Task Final States",
            "- Pending closeout detail migration from source planning records.",
            "",
            "# Evidence",
            "- Source closeout packet missing in `ops/planning/closeout`; generated to keep `validate all` deterministic.",
            "",
            "# Determinism",
            "- Placeholder is generated from a stable template until source packet is authored.",
            "",
            "# Protocol Compatibility",
            "- Closeout packet path and section contract are preserved for GateFlow validators.",
            "",
            "# Modularity",
            "- Auto-generation is isolated to `gateflow.import_luvatrix` import flow.",
            "",
            "# Residual Risks",
            "- Replace this placeholder with canonical milestone evidence before final release closeout.",
            "",
        ]
    )


def _normalize_json_for_drift(payload: Any) -> Any:
    if isinstance(payload, dict):
        normalized: dict[str, Any] = {}
        for key in sorted(payload.keys()):
            if key == "updated_at":
                continue
            normalized[key] = _normalize_json_for_drift(payload[key])
        return normalized
    if isinstance(payload, list):
        return [_normalize_json_for_drift(item) for item in payload]
    if isinstance(payload, str):
        return payload
    # Force deterministic scalar representation for drift comparisons.
    return json.loads(json.dumps(payload, sort_keys=True))
