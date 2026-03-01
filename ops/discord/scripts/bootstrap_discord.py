#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE_URL = "https://discord.com/api/v10"

TEXT_CHANNEL = 0
CATEGORY_CHANNEL = 4

VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
READ_MESSAGE_HISTORY = 1 << 16
PERM_VIEW_READ = VIEW_CHANNEL | READ_MESSAGE_HISTORY
PERM_VIEW_SEND_READ = VIEW_CHANNEL | SEND_MESSAGES | READ_MESSAGE_HISTORY
EXEC_ALLOW = str(PERM_VIEW_SEND_READ)
EXEC_DENY = str(VIEW_CHANNEL)


def api_request(method: str, path: str, token: str, payload: dict[str, Any] | None = None) -> Any:
    url = f"{BASE_URL}{path}"
    data = None
    headers = {
        "Authorization": f"Bot {token}",
        "User-Agent": "luvatrix-discord-bootstrap/1.0",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url=url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Discord API error {exc.code} on {method} {path}: {err}") from exc


def load_blueprint(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def by_name(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["name"]: item for item in items}


def ensure_role(guild_id: str, token: str, role_cfg: dict[str, Any], existing_roles: dict[str, dict[str, Any]], apply: bool) -> dict[str, Any]:
    name = role_cfg["name"]
    if name in existing_roles:
        print(f"[ok] role exists: {name}")
        return existing_roles[name]
    print(f"[create] role: {name}")
    if not apply:
        return {"id": f"dry-run-{name}", "name": name}
    created = api_request("POST", f"/guilds/{guild_id}/roles", token, role_cfg)
    return created


def role_overwrite(role_id: str, allow: int, deny: int) -> dict[str, str]:
    return {
        "id": role_id,
        "type": "0",
        "allow": str(allow),
        "deny": str(deny),
    }


def category_overwrites(category_cfg: dict[str, Any], roles: dict[str, dict[str, Any]], everyone_role_id: str) -> list[dict[str, str]]:
    # Restrict category to leadership only.
    if not category_cfg.get("restricted"):
        # Gate visibility to users with the Onboarded role.
        if not category_cfg.get("requires_onboarded"):
            return []
        overwrites = [
            {
                "id": everyone_role_id,
                "type": "0",
                "allow": "0",
                "deny": str(VIEW_CHANNEL),
            }
        ]
        for role_name in ("Onboarded", "CEO", "Leads"):
            role = roles.get(role_name)
            if role is None:
                continue
            overwrites.append(role_overwrite(role["id"], PERM_VIEW_SEND_READ, 0))
        return overwrites

    overwrites = [
        {
            "id": everyone_role_id,
            "type": "0",
            "allow": "0",
            "deny": EXEC_DENY,
        }
    ]
    for role_name in ("CEO", "Leads"):
        role = roles.get(role_name)
        if role is None:
            continue
        overwrites.append(role_overwrite(role["id"], PERM_VIEW_SEND_READ, 0))
    return overwrites


def ensure_category(guild_id: str, token: str, category_cfg: dict[str, Any], roles: dict[str, dict[str, Any]], existing_channels: list[dict[str, Any]], everyone_role_id: str, position: int, apply: bool) -> dict[str, Any]:
    name = category_cfg["name"]
    existing = next((c for c in existing_channels if c["name"] == name and c["type"] == CATEGORY_CHANNEL), None)
    payload = {
        "name": name,
        "type": CATEGORY_CHANNEL,
        "position": position,
    }
    overwrites = category_overwrites(category_cfg, roles, everyone_role_id)
    if overwrites:
        payload["permission_overwrites"] = overwrites

    if existing:
        print(f"[ok] category exists: {name}")
        if apply:
            try:
                api_request("PATCH", f"/channels/{existing['id']}", token, payload)
            except RuntimeError as exc:
                if "Missing Access" in str(exc) or "Missing Permissions" in str(exc):
                    print(f"[warn] could not patch category '{name}' due access restrictions; keeping existing config")
                else:
                    raise
        return existing

    print(f"[create] category: {name}")
    if not apply:
        return {"id": f"dry-run-{name}", "name": name, "type": CATEGORY_CHANNEL}
    return api_request("POST", f"/guilds/{guild_id}/channels", token, payload)


def ensure_text_channel(
    guild_id: str,
    token: str,
    channel_name: str,
    channel_cfg: dict[str, Any],
    category_id: str,
    roles: dict[str, dict[str, Any]],
    existing_channels: list[dict[str, Any]],
    position: int,
    apply: bool,
) -> dict[str, Any]:
    existing = next(
        (
            c
            for c in existing_channels
            if c["name"] == channel_name and c["type"] == TEXT_CHANNEL and c.get("parent_id") == category_id
        ),
        None,
    )
    payload: dict[str, Any] = {
        "name": channel_name,
        "type": TEXT_CHANNEL,
        "parent_id": category_id,
        "position": position,
    }
    if channel_cfg.get("read_only"):
        overwrites: list[dict[str, str]] = [
            {
                "id": guild_id,
                "type": "0",
                "allow": "0",
                "deny": str(SEND_MESSAGES),
            }
        ]
        poster_roles = channel_cfg.get("poster_roles", ["CEO", "Leads", "Core Engineer", "AI Agent"])
        for role_name in poster_roles:
            role = roles.get(role_name)
            if role is None:
                continue
            overwrites.append(role_overwrite(role["id"], PERM_VIEW_SEND_READ, 0))
        payload["permission_overwrites"] = overwrites

    if existing:
        print(f"[ok] channel exists: #{channel_name}")
        if apply:
            try:
                api_request("PATCH", f"/channels/{existing['id']}", token, payload)
            except RuntimeError as exc:
                if "Missing Access" in str(exc) or "Missing Permissions" in str(exc):
                    print(f"[warn] could not patch channel '#{channel_name}' due access restrictions; keeping existing config")
                else:
                    raise
        return existing

    print(f"[create] channel: #{channel_name}")
    if not apply:
        return {"id": f"dry-run-{channel_name}", "name": channel_name, "type": TEXT_CHANNEL}
    return api_request("POST", f"/guilds/{guild_id}/channels", token, payload)


def send_seed_message(token: str, channel_id: str, text: str, apply: bool) -> None:
    print(f"[seed] channel={channel_id}")
    if not apply:
        return
    try:
        message = api_request("POST", f"/channels/{channel_id}/messages", token, {"content": text})
    except RuntimeError as exc:
        if "Missing Access" in str(exc) or "Missing Permissions" in str(exc):
            print(f"[warn] could not seed message in channel={channel_id}; missing access")
            return
        raise
    try:
        api_request("PUT", f"/channels/{channel_id}/pins/{message['id']}", token)
    except RuntimeError as exc:
        if "Missing Permissions" in str(exc):
            print(f"[warn] could not pin seed message in channel={channel_id}; message posted without pin")
            return
        raise


def delete_channel(token: str, channel: dict[str, Any], apply: bool) -> None:
    prefix = "[delete]" if apply else "[dry-delete]"
    ctype = "category" if channel.get("type") == CATEGORY_CHANNEL else "channel"
    print(f"{prefix} {ctype}: {channel.get('name')} ({channel.get('id')})")
    if not apply:
        return
    try:
        api_request("DELETE", f"/channels/{channel['id']}", token)
    except RuntimeError as exc:
        if "Missing Access" in str(exc) or "Missing Permissions" in str(exc):
            print(f"[warn] could not delete {ctype} '{channel.get('name')}'; missing access")
            return
        raise


def prune_legacy_structure(
    token: str,
    blueprint: dict[str, Any],
    channels: list[dict[str, Any]],
    apply: bool,
) -> None:
    cleanup_cfg = blueprint.get("legacy_cleanup", {})
    legacy_categories = cleanup_cfg.get("legacy_categories", [])
    legacy_channels = cleanup_cfg.get("legacy_channels", [])
    if not legacy_categories and not legacy_channels:
        print("[info] no legacy_cleanup config in blueprint; nothing to prune")
        return

    for cat_name in legacy_categories:
        matches = [c for c in channels if c.get("type") == CATEGORY_CHANNEL and c.get("name") == cat_name]
        for category in matches:
            children = [c for c in channels if c.get("parent_id") == category.get("id")]
            for child in children:
                delete_channel(token, child, apply)
            delete_channel(token, category, apply)

    for ch_name in legacy_channels:
        matches = [c for c in channels if c.get("type") == TEXT_CHANNEL and c.get("name") == ch_name]
        for channel in matches:
            delete_channel(token, channel, apply)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap Luvatrix Discord server structure.")
    parser.add_argument("--guild-id", default=os.getenv("DISCORD_GUILD_ID"), help="Discord guild/server ID")
    parser.add_argument("--token", default=os.getenv("DISCORD_BOT_TOKEN"), help="Discord bot token")
    parser.add_argument(
        "--blueprint",
        default="ops/discord/ops/blueprint.json",
        help="Path to blueprint JSON",
    )
    parser.add_argument("--apply", action="store_true", help="Apply changes. Without this flag runs in dry-run mode.")
    parser.add_argument("--skip-seed", action="store_true", help="Skip posting seed pinned messages.")
    parser.add_argument(
        "--prune-legacy",
        action="store_true",
        help="Delete legacy categories/channels listed under blueprint.legacy_cleanup (safe in dry-run without --apply).",
    )
    return parser.parse_args()


def normalize_channel_cfg(channel_entry: Any) -> dict[str, Any]:
    if isinstance(channel_entry, str):
        return {"name": channel_entry}
    if isinstance(channel_entry, dict):
        if "name" not in channel_entry:
            raise ValueError("channel entry must include 'name'")
        return channel_entry
    raise ValueError("channel entry must be a string or object")


def normalize_secret(value: str | None) -> str | None:
    if value is None:
        return None
    # Tolerate copy/paste from rich text where smart quotes appear.
    return (
        value.strip()
        .strip("'")
        .strip('"')
        .replace("\u2018", "")
        .replace("\u2019", "")
        .replace("\u201c", "")
        .replace("\u201d", "")
        .replace(" ", "")
    )


def main() -> int:
    args = parse_args()
    args.guild_id = normalize_secret(args.guild_id)
    args.token = normalize_secret(args.token)
    if not args.guild_id or not args.token:
        print("error: set --guild-id/--token or DISCORD_GUILD_ID/DISCORD_BOT_TOKEN", file=sys.stderr)
        return 2

    blueprint = load_blueprint(Path(args.blueprint))
    apply = args.apply

    print(f"mode: {'APPLY' if apply else 'DRY-RUN'}")
    try:
        guild = api_request("GET", f"/guilds/{args.guild_id}", args.token)
    except RuntimeError as exc:
        msg = str(exc)
        if "Unknown Guild" in msg:
            print("error: bot cannot access this guild id (or id is incorrect).", file=sys.stderr)
            try:
                guilds = api_request("GET", "/users/@me/guilds", args.token)
                print("bot currently sees these guilds:", file=sys.stderr)
                for g in guilds:
                    print(f"- {g['name']} ({g['id']})", file=sys.stderr)
            except Exception:
                print("could not list bot guilds; re-check bot install and server selection.", file=sys.stderr)
        raise
    print(f"guild: {guild['name']} ({guild['id']})")

    roles_raw = api_request("GET", f"/guilds/{args.guild_id}/roles", args.token)
    roles = by_name(roles_raw)
    everyone_role_id = guild["id"]

    created_roles: dict[str, dict[str, Any]] = {}
    for role_cfg in blueprint["roles"]:
        role = ensure_role(args.guild_id, args.token, role_cfg, roles, apply)
        created_roles[role["name"]] = role

    roles.update(created_roles)

    channels = api_request("GET", f"/guilds/{args.guild_id}/channels", args.token)

    seeded_channels: dict[str, str] = {}
    for cat_pos, category_cfg in enumerate(blueprint["categories"]):
        category = ensure_category(
            args.guild_id,
            args.token,
            category_cfg,
            roles,
            channels,
            everyone_role_id,
            cat_pos,
            apply,
        )
        category_id = category["id"]

        for ch_pos, channel_entry in enumerate(category_cfg["channels"]):
            channel_cfg = normalize_channel_cfg(channel_entry)
            channel_name = channel_cfg["name"]
            channel = ensure_text_channel(
                args.guild_id,
                args.token,
                channel_name,
                channel_cfg,
                category_id,
                roles,
                channels,
                ch_pos,
                apply,
            )
            seeded_channels[channel_name] = channel["id"]

    if not args.skip_seed:
        for channel_name, text in blueprint.get("seed_messages", {}).items():
            channel_id = seeded_channels.get(channel_name)
            if channel_id is None:
                print(f"[warn] cannot seed #{channel_name}: channel not found")
                continue
            send_seed_message(args.token, channel_id, text, apply)

    if args.prune_legacy:
        channels_after = api_request("GET", f"/guilds/{args.guild_id}/channels", args.token)
        prune_legacy_structure(args.token, blueprint, channels_after, apply)

    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
