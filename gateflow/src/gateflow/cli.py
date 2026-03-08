from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from gateflow.api_shim import execute_api
from gateflow.config import get_config_value, set_config_value, show_config
from gateflow.policy import PolicyViolation, enforce_protected_branch_write_guard
from gateflow.render import render_board, render_gantt
from gateflow.scaffold import doctor_workspace, scaffold_workspace
from gateflow.resources import ResourceError, create_resource, delete_resource, get_resource, list_resource, update_resource
from gateflow.validate import ValidationCommandError, run_validation
from gateflow.workspace import GateflowWorkspace

RESOURCES = ("milestones", "tasks", "boards", "frameworks", "backlog")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gateflow")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json-errors", action="store_true", help="Emit machine-readable error payloads.")
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

    validate_p = sub.add_parser("validate")
    validate_sub = validate_p.add_subparsers(dest="validate_action", required=True)
    validate_sub.add_parser("links")
    validate_sub.add_parser("closeout")
    validate_sub.add_parser("all")

    api_p = sub.add_parser("api")
    api_p.add_argument("verb_or_method")
    api_p.add_argument("path", nargs="?")
    api_p.add_argument("--body")

    render_p = sub.add_parser("render")
    render_sub = render_p.add_subparsers(dest="render_action", required=True)
    gantt_p = render_sub.add_parser("gantt")
    gantt_p.add_argument("--format", choices=["md", "ascii"])
    gantt_p.add_argument("--out", type=Path)
    board_p = render_sub.add_parser("board")
    board_p.add_argument("--format", choices=["md", "ascii"])
    board_p.add_argument("--out", type=Path)

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
    except ValidationCommandError as exc:
        _emit_error(json_mode=args.json_errors, error_type="validation", exit_code=2, message=str(exc), errors=exc.errors)
        return 2
    except PolicyViolation as exc:
        _emit_error(json_mode=args.json_errors, error_type="policy", exit_code=3, message=str(exc), errors=[str(exc)])
        return 3
    except (ResourceError, FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        _emit_error(json_mode=args.json_errors, error_type="validation", exit_code=2, message=str(exc), errors=[str(exc)])
        return 2
    except Exception as exc:  # pragma: no cover - defensive contract
        _emit_error(json_mode=args.json_errors, error_type="internal", exit_code=4, message=str(exc), errors=[str(exc)])
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
            enforce_protected_branch_write_guard(args.root)
            print(set_config_value(args.root, args.key, args.value))
            return 0
        if args.config_action == "show":
            print(json.dumps(show_config(args.root), indent=2, sort_keys=True))
            return 0
        raise ValueError(f"unsupported config action: {args.config_action}")

    if args.command == "api":
        method, endpoint = _resolve_api_method_and_path(args.verb_or_method, args.path)
        if method in {"POST", "PATCH", "DELETE"}:
            enforce_protected_branch_write_guard(args.root)
        print(json.dumps(execute_api(method, endpoint, body=args.body, root=args.root), indent=2, sort_keys=True))
        return 0

    if args.command == "validate":
        ok, errors = run_validation(args.root, args.validate_action)
        if ok:
            print(f"validation: PASS ({args.validate_action})")
            return 0
        raise ValidationCommandError(args.validate_action, errors)

    if args.command == "render":
        workspace = GateflowWorkspace(args.root)
        if args.render_action == "gantt":
            output = render_gantt(workspace, out_path=args.out, fmt=args.format)
            if args.out is None:
                print(output, end="")
            return 0
        if args.render_action == "board":
            output = render_board(workspace, out_path=args.out, fmt=args.format)
            if args.out is None:
                print(output, end="")
            return 0
        raise ValueError(f"unsupported render action: {args.render_action}")

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
        enforce_protected_branch_write_guard(args.root)
        print(create_resource(workspace, resource, json.loads(args.body)))
        return 0
    if action == "update":
        enforce_protected_branch_write_guard(args.root)
        print(update_resource(workspace, resource, args.item_id, json.loads(args.body)))
        return 0
    if action == "delete":
        enforce_protected_branch_write_guard(args.root)
        print(delete_resource(workspace, resource, args.item_id))
        return 0
    raise ValueError(f"unsupported action: {action}")


def _resolve_api_method_and_path(verb_or_method: str, path: str | None) -> tuple[str, str]:
    method = verb_or_method.upper()
    if path is None:
        raise ValueError("api requires METHOD and /resource path")
    if method in {"GET", "POST", "PATCH", "DELETE"}:
        return method, path
    raise ValueError(f"unsupported api method: {verb_or_method}")


def _emit_error(
    *,
    json_mode: bool,
    error_type: str,
    exit_code: int,
    message: str,
    errors: list[str],
) -> None:
    if json_mode:
        payload: dict[str, Any] = {
            "ok": False,
            "error_type": error_type,
            "exit_code": exit_code,
            "message": message,
            "errors": errors,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    prefix = "internal error" if error_type == "internal" else f"{error_type} error"
    print(f"{prefix}: {message}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
