from __future__ import annotations

from typing import Any

from gateflow_cli.workspace import GateflowWorkspace


class ResourceError(RuntimeError):
    pass


def list_resource(workspace: GateflowWorkspace, resource: str) -> list[dict[str, Any]]:
    return workspace.list_items(resource)


def get_resource(workspace: GateflowWorkspace, resource: str, item_id: str) -> dict[str, Any]:
    for item in workspace.list_items(resource):
        key = item.get("id", item.get("name"))
        if key == item_id:
            return item
    raise ResourceError(f"{resource} item not found: {item_id}")


def create_resource(workspace: GateflowWorkspace, resource: str, body: dict[str, Any]) -> str:
    items = workspace.list_items(resource)
    item_id = _item_key(resource, body)
    if any(_item_key(resource, row) == item_id for row in items):
        raise ResourceError(f"{resource} item already exists: {item_id}")
    items.append(body)
    workspace.write_items(resource, items)
    return f"created {resource} {item_id}"


def update_resource(workspace: GateflowWorkspace, resource: str, item_id: str, body: dict[str, Any]) -> str:
    items = workspace.list_items(resource)
    found = False
    for item in items:
        if _item_key(resource, item) == item_id:
            item.update(body)
            found = True
            break
    if not found:
        raise ResourceError(f"{resource} item not found: {item_id}")
    workspace.write_items(resource, items)
    return f"updated {resource} {item_id}"


def delete_resource(workspace: GateflowWorkspace, resource: str, item_id: str) -> str:
    items = workspace.list_items(resource)
    remaining = [item for item in items if _item_key(resource, item) != item_id]
    if len(remaining) == len(items):
        raise ResourceError(f"{resource} item not found: {item_id}")
    workspace.write_items(resource, remaining)
    return f"deleted {resource} {item_id}"


def _item_key(resource: str, item: dict[str, Any]) -> Any:
    key = item.get("name") if resource == "frameworks" else item.get("id")
    if key in (None, ""):
        raise ResourceError(f"{resource} item missing required key")
    return key
