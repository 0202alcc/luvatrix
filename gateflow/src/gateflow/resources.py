from __future__ import annotations

from typing import Any

from gateflow.workspace import GateflowWorkspace

GATEFLOW_SEQUENCE = [
    "Intake",
    "Success Criteria Spec",
    "Safety Tests Spec",
    "Implementation Tests Spec",
    "Edge Case Tests Spec",
    "Prototype Stage 1",
    "Prototype Stage 2+",
    "Verification Review",
    "Integration Ready",
    "Done",
]
DONE_REQUIRED_ACTUALS_KEYS = {
    "input_tokens",
    "output_tokens",
    "wall_time_sec",
    "tool_calls",
    "reopen_count",
}
DONE_REQUIRED_GATE_KEYS = {
    "success_criteria_met",
    "safety_tests_passed",
    "implementation_tests_passed",
    "edge_case_tests_passed",
    "merged_to_main",
    "required_checks_passed_on_main",
}


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
    _validate_resource_payload(resource, current=None, candidate=body)
    items.append(body)
    workspace.write_items(resource, items)
    return f"created {resource} {item_id}"


def update_resource(workspace: GateflowWorkspace, resource: str, item_id: str, body: dict[str, Any]) -> str:
    items = workspace.list_items(resource)
    found = False
    for item in items:
        if _item_key(resource, item) == item_id:
            updated = dict(item)
            updated.update(body)
            _validate_resource_payload(resource, current=item, candidate=updated)
            item.update(updated)
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


def _validate_resource_payload(resource: str, *, current: dict[str, Any] | None, candidate: dict[str, Any]) -> None:
    if resource != "tasks":
        return

    _validate_task_status_transition(current=current, candidate=candidate)
    _validate_task_done_requirements(current=current, candidate=candidate)


def _validate_task_status_transition(*, current: dict[str, Any] | None, candidate: dict[str, Any]) -> None:
    if current is None:
        return
    old_status = str(current.get("status", ""))
    new_status = str(candidate.get("status", ""))
    if old_status == new_status:
        return

    if old_status not in GATEFLOW_SEQUENCE + ["Blocked"] or new_status not in GATEFLOW_SEQUENCE + ["Blocked"]:
        return
    if new_status == "Blocked":
        return
    if old_status == "Blocked":
        if new_status == "Done":
            raise ResourceError("task cannot move Blocked -> Done directly; move to Integration Ready first")
        return

    old_idx = GATEFLOW_SEQUENCE.index(old_status)
    new_idx = GATEFLOW_SEQUENCE.index(new_status)
    delta = new_idx - old_idx
    if delta == 1:
        return
    if delta > 1:
        raise ResourceError(f"cannot skip GateFlow stages ({old_status} -> {new_status})")
    if delta < 0:
        raise ResourceError(f"backward GateFlow stage move is not allowed ({old_status} -> {new_status})")


def _validate_task_done_requirements(*, current: dict[str, Any] | None, candidate: dict[str, Any]) -> None:
    status = candidate.get("status")
    became_done = status == "Done" and (current is None or current.get("status") != "Done")
    if not became_done:
        return

    actuals = candidate.get("actuals")
    if not isinstance(actuals, dict):
        raise ResourceError("task moving to Done must include actuals object")
    missing_actuals = sorted(k for k in DONE_REQUIRED_ACTUALS_KEYS if k not in actuals)
    if missing_actuals:
        raise ResourceError(f"task moving to Done missing actuals keys: {', '.join(missing_actuals)}")
    for key in DONE_REQUIRED_ACTUALS_KEYS:
        value = actuals[key]
        if not isinstance(value, (int, float)):
            raise ResourceError(f"task actuals.{key} must be numeric")
        if value < 0:
            raise ResourceError(f"task actuals.{key} must be >= 0")

    done_gate = candidate.get("done_gate")
    if not isinstance(done_gate, dict):
        raise ResourceError("task moving to Done must include done_gate object")
    missing_done_gate = sorted(k for k in DONE_REQUIRED_GATE_KEYS if k not in done_gate)
    if missing_done_gate:
        raise ResourceError(f"task moving to Done missing done_gate keys: {', '.join(missing_done_gate)}")
    failed = sorted(k for k in DONE_REQUIRED_GATE_KEYS if done_gate.get(k) is not True)
    if failed:
        raise ResourceError(f"task moving to Done failed done_gate checks: {', '.join(failed)}")
