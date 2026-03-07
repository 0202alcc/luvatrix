from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path


REQUIRED_ENTRY_KEYS = {
    "test_id",
    "reason",
    "owner",
    "ticket_id",
    "quarantined_on",
    "expires_on",
    "remediation_status",
}
ALLOWED_REMEDIATION_STATUS = {"open", "in_progress", "fixed", "verified"}


def _parse_date(value: str, *, field: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid {field} date '{value}', expected YYYY-MM-DD") from exc


def validate_manifest(
    payload: dict[str, object],
    *,
    max_quarantine_days: int,
    today: dt.date,
) -> list[str]:
    errors: list[str] = []
    if payload.get("milestone_id") != "P-013":
        errors.append("milestone_id must be P-013")

    entries = payload.get("entries")
    if not isinstance(entries, list):
        return ["entries must be a list"]

    seen_tests: set[str] = set()
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"entries[{idx}] must be an object")
            continue

        missing = sorted(REQUIRED_ENTRY_KEYS.difference(entry.keys()))
        if missing:
            errors.append(f"entries[{idx}] missing keys: {', '.join(missing)}")
            continue

        test_id = entry["test_id"]
        if not isinstance(test_id, str) or not test_id.strip():
            errors.append(f"entries[{idx}].test_id must be non-empty")
            continue
        if test_id in seen_tests:
            errors.append(f"duplicate test_id in manifest: {test_id}")
        seen_tests.add(test_id)

        owner = entry["owner"]
        if not isinstance(owner, str) or not owner.startswith("team:"):
            errors.append(f"entries[{idx}].owner must start with team:")

        ticket_id = entry["ticket_id"]
        if not isinstance(ticket_id, str) or not ticket_id.startswith("T-"):
            errors.append(f"entries[{idx}].ticket_id must start with T-")

        status = entry["remediation_status"]
        if status not in ALLOWED_REMEDIATION_STATUS:
            errors.append(
                f"entries[{idx}].remediation_status must be one of {sorted(ALLOWED_REMEDIATION_STATUS)}"
            )

        quarantined_on = _parse_date(str(entry["quarantined_on"]), field="quarantined_on")
        expires_on = _parse_date(str(entry["expires_on"]), field="expires_on")

        if expires_on < quarantined_on:
            errors.append(f"entries[{idx}] expires_on cannot be earlier than quarantined_on")

        age_days = (today - quarantined_on).days
        if age_days > max_quarantine_days:
            errors.append(
                f"entries[{idx}] exceeds max quarantine age ({age_days} > {max_quarantine_days})"
            )

        if expires_on < today and status != "verified":
            errors.append(f"entries[{idx}] quarantine expired without verified remediation")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate flaky quarantine manifest for P-013")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("ops/ci/flaky_quarantine_manifest.json"),
        help="path to flaky quarantine manifest",
    )
    parser.add_argument(
        "--max-quarantine-days",
        type=int,
        default=14,
        help="maximum allowed quarantine age in days",
    )
    args = parser.parse_args()

    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    errors = validate_manifest(
        payload,
        max_quarantine_days=max(1, int(args.max_quarantine_days)),
        today=dt.date.today(),
    )

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    entries = payload.get("entries", [])
    print(f"PASS: {args.manifest} ({len(entries)} quarantined tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
