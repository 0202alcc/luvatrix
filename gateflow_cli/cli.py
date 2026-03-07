from __future__ import annotations

import argparse
import json
from pathlib import Path

from gateflow_cli.config import get_config_value, set_config_value, show_config
from gateflow_cli.scaffold import doctor_workspace, scaffold_workspace
from gateflow_cli.resources import ResourceError, create_resource, delete_resource, get_resource, list_resource, update_resource
from gateflow_cli.workspace import GateflowWorkspace

RESOURCES = ("milestones", "tasks", "boards", "frameworks", "backlog")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gateflow")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init")
    init_sub = init_p.add_subparsers(dest="init_action", required=True)
    scaffold_p = init_sub.add_parser("scaffold")
    scaffold_p.add_argument("--profile", choices=["minimal", "discord", "enterprise"], default="minimal")
    init_sub.add_parser("doctor")

    config_p = sub.add_parser("config")
    config_sub = config_p.add_subparsers(dest="config_action", required=True)
    config_get = config_sub.add_parser("get")
    config_get.add_argument("key")
    config_set = config_sub.add_parser("set")
    config_set.add_argument("key")
    config_set.add_argument("value")
    config_sub.add_parser("show")

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

    try:
        return _dispatch(args)
    except (ResourceError, FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}")
        return 2
    except Exception as exc:  # pragma: no cover - defensive contract
        print(f"internal error: {exc}")
        return 4


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "init":
        if args.init_action == "scaffold":
            created = scaffold_workspace(root=args.root, profile=args.profile)
            print(json.dumps({"status": "ok", "created": created}, indent=2, sort_keys=True))
            return 0
        if args.init_action == "doctor":
            print(json.dumps(doctor_workspace(root=args.root), indent=2, sort_keys=True))
            return 0
        raise ValueError(f"unsupported init action: {args.init_action}")

    if args.command == "config":
        if args.config_action == "get":
            print(json.dumps(get_config_value(args.root, args.key), indent=2, sort_keys=True))
            return 0
        if args.config_action == "set":
            print(set_config_value(args.root, args.key, args.value))
            return 0
        if args.config_action == "show":
            print(json.dumps(show_config(args.root), indent=2, sort_keys=True))
            return 0
        raise ValueError(f"unsupported config action: {args.config_action}")

    workspace = GateflowWorkspace(args.root)
    resource = args.command
    action = args.action

    if action == "list":
        print(json.dumps(list_resource(workspace, resource), indent=2, sort_keys=True))
        return 0
    if action == "get":
        print(json.dumps(get_resource(workspace, resource, args.item_id), indent=2, sort_keys=True))
        return 0
    if action == "create":
        print(create_resource(workspace, resource, json.loads(args.body)))
        return 0
    if action == "update":
        print(update_resource(workspace, resource, args.item_id, json.loads(args.body)))
        return 0
    if action == "delete":
        print(delete_resource(workspace, resource, args.item_id))
        return 0
    raise ValueError(f"unsupported action: {action}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
