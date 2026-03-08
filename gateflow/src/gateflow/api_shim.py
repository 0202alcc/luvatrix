from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gateflow.resources import create_resource, delete_resource, get_resource, list_resource, update_resource
from gateflow.workspace import GateflowWorkspace

VALID_RESOURCES = {"milestones", "tasks", "boards", "frameworks", "backlog"}


def execute_api(method: str, endpoint: str, *, body: str | None, root: Path) -> dict[str, Any]:
    method = method.upper()
    resource, item_id = _parse_endpoint(endpoint)
    workspace = GateflowWorkspace(root)

    result: Any
    if method == "GET":
        result = list_resource(workspace, resource) if item_id is None else get_resource(workspace, resource, item_id)
    elif method == "POST":
        if body is None:
            raise ValueError("POST requires --body")
        result = create_resource(workspace, resource, json.loads(body))
    elif method == "PATCH":
        if body is None:
            raise ValueError("PATCH requires --body")
        if item_id is None:
            raise ValueError("PATCH requires resource id in endpoint")
        result = update_resource(workspace, resource, item_id, json.loads(body))
    elif method == "DELETE":
        if item_id is None:
            raise ValueError("DELETE requires resource id in endpoint")
        result = delete_resource(workspace, resource, item_id)
    else:
        raise ValueError(f"unsupported method: {method}")

    return {
        "compatibility_mode": "planning_api_shim_v1",
        "method": method,
        "path": endpoint,
        "result": result,
    }


def _parse_endpoint(endpoint: str) -> tuple[str, str | None]:
    if not endpoint.startswith("/"):
        raise ValueError("endpoint must start with /")
    parts = [part for part in endpoint.split("/") if part]
    if not parts:
        raise ValueError("endpoint must include resource")
    resource = parts[0]
    if resource not in VALID_RESOURCES:
        raise ValueError(f"unsupported resource: {resource}")
    if len(parts) == 1:
        return resource, None
    return resource, parts[1]
