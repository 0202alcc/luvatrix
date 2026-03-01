#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import re
import tempfile
from pathlib import Path

import discord

RENDER_TRIGGER = re.compile(r"\bgantt\s+render\b", re.IGNORECASE)
JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def extract_schedule_json(message_content: str) -> str | None:
    m = JSON_BLOCK_RE.search(message_content)
    return m.group(1) if m else None


async def run_generate_png(schedule_path: Path, out_path: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        "python",
        "ops/discord/scripts/generate_gantt_png.py",
        "--schedule",
        str(schedule_path),
        "--out",
        str(out_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="ignore"))


def build_intents() -> discord.Intents:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    return intents


client = discord.Client(intents=build_intents())


@client.event
async def on_ready() -> None:
    print(f"Logged in as {client.user}")


@client.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot or client.user is None:
        return
    if client.user not in message.mentions:
        return
    if not RENDER_TRIGGER.search(message.content):
        return

    await message.channel.send("Generating Gantt chart...")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            schedule_override = extract_schedule_json(message.content)
            schedule_path = tmp / "schedule.json"
            if schedule_override:
                schedule_path.write_text(schedule_override, encoding="utf-8")
            else:
                schedule_path = Path("ops/planning/gantt/milestone_schedule.json")
            out_path = tmp / "gantt.png"
            await run_generate_png(schedule_path, out_path)
            await message.channel.send(
                content="Generated Gantt chart from schedule.",
                file=discord.File(str(out_path), filename="milestones_gantt.png"),
            )
    except Exception as exc:
        await message.channel.send(f"Failed to generate Gantt chart: `{exc}`")


def main() -> int:
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise SystemExit("Set DISCORD_BOT_TOKEN")
    client.run(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
