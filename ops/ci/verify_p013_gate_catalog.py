from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_GATE_KEYS = {"id", "owner", "required_command", "pass_criteria"}


def validate_catalog(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    milestone_id = payload.get("milestone_id")
    if milestone_id != "P-013":
        errors.append("milestone_id must be P-013")

    gates = payload.get("gates")
    if not isinstance(gates, list) or not gates:
        errors.append("gates must be a non-empty list")
        return errors

    gate_ids: set[str] = set()
    for idx, gate in enumerate(gates):
        if not isinstance(gate, dict):
            errors.append(f"gates[{idx}] must be an object")
            continue
        missing = sorted(REQUIRED_GATE_KEYS.difference(gate.keys()))
        if missing:
            errors.append(f"gates[{idx}] missing keys: {', '.join(missing)}")
        gate_id = gate.get("id")
        if not isinstance(gate_id, str) or not gate_id.strip():
            errors.append(f"gates[{idx}].id must be a non-empty string")
            continue
        if gate_id in gate_ids:
            errors.append(f"duplicate gate id: {gate_id}")
        gate_ids.add(gate_id)

        owner = gate.get("owner")
        if not isinstance(owner, str) or not owner.startswith("team:"):
            errors.append(f"gates[{idx}].owner must start with team:")

        command = gate.get("required_command")
        if not isinstance(command, str) or "gateflow" not in command or "validate" not in command:
            errors.append(f"gates[{idx}].required_command must be a gateflow validate command")

        criteria = gate.get("pass_criteria")
        if not isinstance(criteria, str) or not criteria.strip():
            errors.append(f"gates[{idx}].pass_criteria must be non-empty")

    escalation_path = payload.get("escalation_path")
    if not isinstance(escalation_path, list) or len(escalation_path) < 2:
        errors.append("escalation_path must contain at least two steps")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate P-013 gate ownership catalog")
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("ops/ci/p013_gate_catalog.json"),
        help="path to p013 gate catalog json",
    )
    args = parser.parse_args()

    payload = json.loads(args.catalog.read_text(encoding="utf-8"))
    errors = validate_catalog(payload)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(f"PASS: {args.catalog} ({len(payload['gates'])} gates)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
