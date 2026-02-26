#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DISCORD_BOT_TOKEN:-}" || -z "${DISCORD_GUILD_ID:-}" ]]; then
  echo "Missing DISCORD_BOT_TOKEN or DISCORD_GUILD_ID"
  exit 2
fi

# Sanitize copied values (including smart quotes)
DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN// /}"
DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN//\"/}"
DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN//\'/}"
DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN//“/}"
DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN//”/}"
DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN//‘/}"
DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN//’/}"
DISCORD_GUILD_ID="${DISCORD_GUILD_ID// /}"
DISCORD_GUILD_ID="${DISCORD_GUILD_ID//\"/}"
DISCORD_GUILD_ID="${DISCORD_GUILD_ID//\'/}"
DISCORD_GUILD_ID="${DISCORD_GUILD_ID//“/}"
DISCORD_GUILD_ID="${DISCORD_GUILD_ID//”/}"
DISCORD_GUILD_ID="${DISCORD_GUILD_ID//‘/}"
DISCORD_GUILD_ID="${DISCORD_GUILD_ID//’/}"

CHANNEL_NAME="milestones-gantt"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

CHANNEL_ID=$(curl -sS -H "Authorization: Bot ${DISCORD_BOT_TOKEN}" \
  "https://discord.com/api/v10/guilds/${DISCORD_GUILD_ID}/channels" \
  | python -c 'import sys, json
arr=json.load(sys.stdin)
for c in arr:
  if c.get("type")==0 and c.get("name")=="milestones-gantt":
    print(c["id"])
    break')

if [[ -z "$CHANNEL_ID" ]]; then
  echo "Could not find #${CHANNEL_NAME}"
  exit 3
fi

python "${REPO_ROOT}/discord/scripts/generate_gantt_markdown.py" > /tmp/gantt_md_path.txt
MD_PATH=$(cat /tmp/gantt_md_path.txt)
python "${REPO_ROOT}/discord/scripts/generate_gantt_png.py" > /tmp/gantt_path.txt
PNG_PATH=$(cat /tmp/gantt_path.txt)
export CHANNEL_ID
export MD_PATH

python - <<'PY'
from pathlib import Path
import json
import os
import urllib.request
import urllib.error

token = os.environ["DISCORD_BOT_TOKEN"]
channel_id = os.environ["CHANNEL_ID"]
md_path = Path(os.environ["MD_PATH"])
text = md_path.read_text(encoding="utf-8")

def post(content: str) -> None:
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        data=json.dumps({"content": content}).encode("utf-8"),
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "luvatrix-gantt-poster/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req):
        pass

max_len = 1900
for i in range(0, len(text), max_len):
    post(text[i:i+max_len])
PY

curl -sS -X POST "https://discord.com/api/v10/channels/${CHANNEL_ID}/messages" \
  -H "Authorization: Bot ${DISCORD_BOT_TOKEN}" \
  -F 'content=Updated milestone Gantt chart (auto-generated).' \
  -F "files[0]=@${PNG_PATH}" >/dev/null

echo "Posted Gantt image to #${CHANNEL_NAME}"
