from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from gateflow_cli.resources import ResourceError, create_resource, delete_resource, get_resource, list_resource, update_resource
from gateflow_cli.workspace import GateflowWorkspace

RESOURCES = ("milestones", "tasks", "boards", "frameworks", "backlog")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gateflow")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="resource", required=True)

    for resource in RESOURCES:
        rs = sub.add_parser(resource)
        rsub = rs.add_subparsers(dest="action", required=True)

        rsub.add_parser("list")

        get_p = rsub.add_parser("get")
        get_p.add_argument("item_id")

        create_p = rsub.add_parser("create")
        create_p.add_argument("--body", required=True)

        update_p = rsub.add_parser("update")
        update_p.add_argument("item_id")
        update_p.add_argument("--body", required=True)

        delete_p = rsub.add_parser("delete")
        delete_p.add_argument("item_id")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    workspace = GateflowWorkspace(args.root)

    try:
        return _dispatch(workspace, args.resource, args.action, vars(args))
    except (ResourceError, FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}")
        return 2
    except Exception as exc:  # pragma: no cover - defensive contract
        print(f"internal error: {exc}")
        return 4


def _dispatch(workspace: GateflowWorkspace, resource: str, action: str, args: dict[str, Any]) -> int:
    if action == "list":
        print(json.dumps(list_resource(workspace, resource), indent=2, sort_keys=True))
        return 0
    if action == "get":
        print(json.dumps(get_resource(workspace, resource, args["item_id"]), indent=2, sort_keys=True))
        return 0
    if action == "create":
        print(create_resource(workspace, resource, json.loads(args["body"])))
        return 0
    if action == "update":
        print(update_resource(workspace, resource, args["item_id"], json.loads(args["body"])))
        return 0
    if action == "delete":
        print(delete_resource(workspace, resource, args["item_id"]))
        return 0
    raise ValueError(f"unsupported action: {action}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
