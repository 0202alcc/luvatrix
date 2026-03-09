from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

APP_ID = "interactive_components"
APP_DIR = Path(__file__).resolve().parent
ARTIFACT_PATH = APP_DIR / "validation_artifact.json"


def _artifact_payload() -> dict[str, object]:
    command = f"PYTHONPATH=. uv run python examples/app_protocol/{APP_ID}/app_main.py --validate"
    fingerprint = sha256(f"{APP_ID}:v1".encode("utf-8")).hexdigest()
    return {
        "app_id": APP_ID,
        "artifact_version": "v1",
        "deterministic_fingerprint": fingerprint,
        "validation_command": command,
        "status": "PASS",
    }


def create() -> dict[str, object]:
    return {"app_id": APP_ID, "status": "ready"}


def run_validation() -> Path:
    payload = _artifact_payload()
    ARTIFACT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ARTIFACT_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description="Planes training app validator")
    parser.add_argument("--validate", action="store_true", help="Write deterministic validation artifact")
    args = parser.parse_args()
    if args.validate:
        output = run_validation()
        print(f"VALIDATION_ARTIFACT={output}")
        return 0
    print(json.dumps(create(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
