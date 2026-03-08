from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gateflow.io import read_json, write_json

_ALLOWED_PREFIXES = ("policy.protected_branches", "defaults", "render")


def config_path(root: Path) -> Path:
    return root / ".gateflow" / "config.json"


def show_config(root: Path) -> dict[str, Any]:
    return read_json(config_path(root))


def get_config_value(root: Path, key: str) -> Any:
    node: Any = show_config(root)
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise ValueError(f"unknown config key: {key}")
        node = node[part]
    return node


def set_config_value(root: Path, key: str, value_raw: str) -> str:
    if not any(key == allowed or key.startswith(f"{allowed}.") for allowed in _ALLOWED_PREFIXES):
        raise ValueError("config key must target policy.protected_branches, defaults, or render")

    data = show_config(root)
    value = _coerce_value(value_raw)

    parts = key.split(".")
    node = data
    for part in parts[:-1]:
        child = node.get(part)
        if child is None:
            child = {}
            node[part] = child
        if not isinstance(child, dict):
            raise ValueError(f"config path is not an object: {part}")
        node = child
    node[parts[-1]] = value
    write_json(config_path(root), data)
    return f"updated config {key}"


def _coerce_value(value_raw: str) -> Any:
    try:
        return json.loads(value_raw)
    except json.JSONDecodeError:
        return value_raw
