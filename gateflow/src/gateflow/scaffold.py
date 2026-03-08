from __future__ import annotations

from datetime import date
from pathlib import Path

from gateflow.io import read_json, write_json


def scaffold_workspace(root: Path, profile: str) -> list[str]:
    gateflow_dir = root / ".gateflow"
    closeout_dir = gateflow_dir / "closeout"
    gateflow_dir.mkdir(parents=True, exist_ok=True)
    closeout_dir.mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    stamped = date.today().isoformat()

    overlay_names = _profile_to_overlays(profile)
    config_payload = {
        "defaults": {"framework": "gateflow_v1", "warning_mode": "warn"},
        "overlays": overlay_names,
        "profiles": _overlay_payload(overlay_names),
        "policy": {"protected_branches": ["main"], "protected_branch_patterns": []},
        "profile": "minimal",
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
        if path.name == "config.json":
            merged, changed = _merge_config(merged, payload)
        else:
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


def _profile_to_overlays(profile: str) -> list[str]:
    if profile == "minimal":
        return []
    if profile == "discord":
        return ["discord"]
    if profile == "enterprise":
        return ["enterprise"]
    raise ValueError(f"unsupported profile: {profile}")


def _overlay_payload(overlays: list[str]) -> dict[str, dict[str, object]]:
    payload: dict[str, dict[str, object]] = {}
    if "discord" in overlays:
        payload["discord"] = {
            "channel_map": {},
            "message_template": "default",
        }
    if "enterprise" in overlays:
        payload["enterprise"] = {
            "audit_required": True,
            "done_gate_strict": True,
        }
    return payload


def _merge_config(existing: dict[str, object], target: dict[str, object]) -> tuple[dict[str, object], bool]:
    merged = dict(existing)
    changed = False
    for key in ("version", "updated_at", "profile", "defaults", "policy", "render"):
        if key not in merged:
            merged[key] = target[key]
            changed = True

    existing_overlays = set(merged.get("overlays", []))
    target_overlays = set(target.get("overlays", []))
    union_overlays = sorted(existing_overlays | target_overlays)
    if union_overlays != list(merged.get("overlays", [])):
        merged["overlays"] = union_overlays
        changed = True

    profile_payload = dict(merged.get("profiles", {}))
    for name, details in _overlay_payload(union_overlays).items():
        if name not in profile_payload:
            profile_payload[name] = details
            changed = True
    if profile_payload != merged.get("profiles"):
        merged["profiles"] = profile_payload
        changed = True

    if "enterprise" in union_overlays:
        defaults = dict(merged.get("defaults", {}))
        if defaults.get("warning_mode") != "strict":
            defaults["warning_mode"] = "strict"
            merged["defaults"] = defaults
            changed = True
        policy = dict(merged.get("policy", {}))
        branches = list(policy.get("protected_branches", []))
        if "release" not in branches:
            branches.append("release")
            policy["protected_branches"] = branches
            merged["policy"] = policy
            changed = True

    return merged, changed
