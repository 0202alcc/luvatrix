from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"missing ledger: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    payload = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True)
    path.write_text(f"{payload}\n", encoding="utf-8")
