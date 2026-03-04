#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CLOSEOUT_ROOT = ROOT / "artifacts" / "perf" / "closeout"
CLOSEOUT_PACKET = ROOT / "ops" / "planning" / "closeout" / "p-026_closeout.md"

REQUIRED_ARTIFACTS = [
    "artifacts/perf/closeout/raw_closeout_required.json",
    "artifacts/perf/closeout/measured_summary.json",
    "artifacts/perf/closeout/determinism_replay_matrix.json",
]


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(131072), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _replace_manifest_block(packet_text: str, manifest: dict[str, Any]) -> str:
    block = "```json\n" + json.dumps(manifest, indent=2, sort_keys=True) + "\n```"
    pattern = re.compile(r"```json\s*\n\{[\s\S]*?\}\n```", re.MULTILINE)
    if pattern.search(packet_text):
        return pattern.sub(block, packet_text, count=1)
    marker = "## Evidence\n"
    idx = packet_text.find(marker)
    if idx == -1:
        return packet_text + "\n\n## Evidence\n" + block + "\n"
    insert_at = idx + len(marker)
    return packet_text[:insert_at] + "\n" + block + "\n" + packet_text[insert_at:]


def _refresh_evidence_section(packet_text: str) -> str:
    lines = packet_text.splitlines()
    out: list[str] = []
    for line in lines:
        # Drop stale bullets from synthetic bundle era.
        if "determinism_replay_seed1337.json" in line:
            continue
        if "incremental_present_matrix_seed1337.json" in line:
            continue
        if "summary.json" in line and "closeout/" in line and "raw_closeout_required" not in line:
            continue
        out.append(line)
    return "\n".join(out) + ("\n" if packet_text.endswith("\n") else "")


def build_manifest() -> dict[str, Any]:
    artifacts: list[dict[str, str]] = []
    for rel in REQUIRED_ARTIFACTS:
        path = ROOT / rel
        if not path.exists():
            raise FileNotFoundError(f"required artifact missing: {rel}")
        artifacts.append({"path": rel, "sha256": _hash_file(path)})
    return {"artifacts": artifacts}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile P-026 closeout packet manifest from provenance-backed artifacts only."
    )
    parser.add_argument("--out", default=str(CLOSEOUT_ROOT), help="Compatibility placeholder.")
    parser.add_argument("--strict", action="store_true", help="Compatibility flag; no behavior change.")
    args = parser.parse_args()
    _ = (args.out, args.strict)

    manifest = build_manifest()
    (CLOSEOUT_ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    if CLOSEOUT_PACKET.exists():
        packet = CLOSEOUT_PACKET.read_text(encoding="utf-8")
        packet = _refresh_evidence_section(packet)
        packet = _replace_manifest_block(packet, manifest)
        CLOSEOUT_PACKET.write_text(packet, encoding="utf-8")

    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
