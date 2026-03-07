from __future__ import annotations

from datetime import date
from pathlib import Path

from gateflow_cli.io import read_json, write_json


def scaffold_workspace(root: Path, profile: str) -> list[str]:
    gateflow_dir = root / ".gateflow"
    closeout_dir = gateflow_dir / "closeout"
    gateflow_dir.mkdir(parents=True, exist_ok=True)
    closeout_dir.mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    stamped = date.today().isoformat()

    config_payload = {
        "defaults": {"framework": "gateflow_v1", "warning_mode": "warn"},
        "overlays": [],
        "policy": {"protected_branches": ["main"], "protected_branch_patterns": []},
        "profile": profile,
        "render": {"format": "md", "lane_mode": "milestone"},
        "updated_at": stamped,
        "version": "gateflow_v1",
    }

    created.extend(_ensure_json(gateflow_dir / "config.json", config_payload))
    created.extend(_ensure_json(gateflow_dir / "milestones.json", _empty_ledger(stamped)))
    created.extend(_ensure_json(gateflow_dir / "tasks.json", _empty_ledger(stamped)))
    created.extend(_ensure_json(gateflow_dir / "boards.json", _empty_ledger(stamped)))
    created.extend(_ensure_json(gateflow_dir / "backlog.json", _empty_ledger(stamped)))
    return created


def doctor_workspace(root: Path) -> dict[str, object]:
    gateflow_dir = root / ".gateflow"
    expected = [
        "config.json",
        "milestones.json",
        "tasks.json",
        "boards.json",
        "backlog.json",
        "closeout",
    ]
    missing = [name for name in expected if not (gateflow_dir / name).exists()]
    return {
        "ok": len(missing) == 0,
        "missing": missing,
        "root": str(root),
    }


def _empty_ledger(stamped: str) -> dict[str, object]:
    return {
        "items": [],
        "updated_at": stamped,
        "version": "gateflow_v1",
    }


def _ensure_json(path: Path, payload: dict[str, object]) -> list[str]:
    if path.exists():
        existing = read_json(path)
        merged = dict(existing)
        changed = False
        for key, value in payload.items():
            if key not in merged:
                merged[key] = value
                changed = True
        if changed:
            write_json(path, merged)
            return [str(path)]
        return []
    write_json(path, payload)
    return [str(path)]
