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
MAX_MESSAGE_LEN = 1900

ARTIFACT_TO_CHANNEL = {
    "team_charter.md": "project-charter-public",
    "workplan.md": "workplan-public",
    "milestone_gantt.md": "milestones-gantt",
    "work_breakdown_structure.md": "wbs-work-breakdown",
    "responsibility_matrix.md": "responsibility-matrix",
    "adr_index.md": "adr-log",
    "risk_register.md": "risk-incident-log",
    "executive_digest_template.md": "exec-dashboard",
    "agile_board_seed.md": "agile-ceremonies",
}


def normalize(value: str | None) -> str | None:
    if value is None:
        return None
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


def api_request(method: str, path: str, token: str, payload: dict[str, Any] | None = None) -> Any:
    url = f"{BASE_URL}{path}"
    data = None
    headers = {
        "Authorization": f"Bot {token}",
        "User-Agent": "luvatrix-discord-artifact-poster/1.0",
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


def chunk_text(text: str, max_len: int = MAX_MESSAGE_LEN) -> list[str]:
    lines = text.splitlines(keepends=True)
    chunks: list[str] = []
    current = ""
    for line in lines:
        if len(current) + len(line) <= max_len:
            current += line
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(line) <= max_len:
            current = line
        else:
            for i in range(0, len(line), max_len):
                chunks.append(line[i : i + max_len])
    if current:
        chunks.append(current)
    return chunks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post artifact docs to mapped Discord channels.")
    parser.add_argument("--guild-id", default=os.getenv("DISCORD_GUILD_ID"))
    parser.add_argument("--token", default=os.getenv("DISCORD_BOT_TOKEN"))
    parser.add_argument("--artifacts-dir", default="discord/artifacts")
    parser.add_argument("--apply", action="store_true", help="Apply changes. Without this flag runs in dry-run mode.")
    parser.add_argument("--pin-first", action="store_true", help="Attempt to pin first posted message chunk.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    guild_id = normalize(args.guild_id)
    token = normalize(args.token)
    if not guild_id or not token:
        print("error: set DISCORD_GUILD_ID and DISCORD_BOT_TOKEN or pass --guild-id/--token", file=sys.stderr)
        return 2

    apply = args.apply
    print(f"mode: {'APPLY' if apply else 'DRY-RUN'}")
    guild = api_request("GET", f"/guilds/{guild_id}", token)
    print(f"guild: {guild['name']} ({guild['id']})")

    channels = api_request("GET", f"/guilds/{guild_id}/channels", token)
    text_channels = {c["name"]: c for c in channels if c.get("type") == 0}

    artifacts_dir = Path(args.artifacts_dir)
    missing: list[str] = []
    for artifact_name, channel_name in ARTIFACT_TO_CHANNEL.items():
        artifact_path = artifacts_dir / artifact_name
        if not artifact_path.exists():
            missing.append(str(artifact_path))
            continue
        channel = text_channels.get(channel_name)
        if channel is None:
            print(f"[warn] channel not found: #{channel_name} (artifact {artifact_name} skipped)")
            continue

        content = artifact_path.read_text(encoding="utf-8")
        chunks = chunk_text(f"## Baseline Artifact: {artifact_name}\n\n{content}")
        print(f"[post] {artifact_name} -> #{channel_name} ({len(chunks)} message chunk(s))")
        if not apply:
            continue

        first_msg_id: str | None = None
        for chunk in chunks:
            try:
                msg = api_request("POST", f"/channels/{channel['id']}/messages", token, {"content": chunk})
                if first_msg_id is None:
                    first_msg_id = msg["id"]
            except RuntimeError as exc:
                if "Missing Access" in str(exc) or "Missing Permissions" in str(exc):
                    print(f"[warn] missing permission to post in #{channel_name}; skipped")
                    first_msg_id = None
                    break
                raise

        if args.pin_first and first_msg_id is not None:
            try:
                api_request("PUT", f"/channels/{channel['id']}/pins/{first_msg_id}", token)
                print(f"[pin] #{channel_name}")
            except RuntimeError as exc:
                if "Missing Access" in str(exc) or "Missing Permissions" in str(exc):
                    print(f"[warn] cannot pin in #{channel_name}; continuing")
                else:
                    raise

    if missing:
        print("error: missing artifact files:")
        for path in missing:
            print(f"- {path}")
        return 1

    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
