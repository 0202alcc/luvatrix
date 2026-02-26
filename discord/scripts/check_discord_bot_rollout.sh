#!/usr/bin/env bash
set -euo pipefail

API_BASE="https://discord.com/api/v10"

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "[FAIL] Missing env var: $name"
    exit 2
  fi
}

api_get() {
  local path="$1"
  curl -sS -H "Authorization: Bot ${DISCORD_BOT_TOKEN}" "${API_BASE}${path}"
}

check_for_discord_error() {
  local body="$1"
  if echo "$body" | grep -q '"code"'; then
    if echo "$body" | grep -q '"message"'; then
      local msg
      msg=$(echo "$body" | python -c 'import sys,json
try:
 d=json.load(sys.stdin)
 print(d.get("message",""))
except Exception:
 print("unknown error")')
      local code
      code=$(echo "$body" | python -c 'import sys,json
try:
 d=json.load(sys.stdin)
 print(d.get("code",""))
except Exception:
 print("")')
      if [[ -n "$code" ]]; then
        echo "[FAIL] Discord API error: $msg (code=$code)"
        exit 3
      fi
    fi
  fi
}

require_env DISCORD_BOT_TOKEN
require_env DISCORD_GUILD_ID

DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN// /}"
DISCORD_GUILD_ID="${DISCORD_GUILD_ID// /}"
# Strip ascii and smart quotes from copied values.
DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN//\"/}"
DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN//\'/}"
DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN//“/}"
DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN//”/}"
DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN//‘/}"
DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN//’/}"
DISCORD_GUILD_ID="${DISCORD_GUILD_ID//\"/}"
DISCORD_GUILD_ID="${DISCORD_GUILD_ID//\'/}"
DISCORD_GUILD_ID="${DISCORD_GUILD_ID//“/}"
DISCORD_GUILD_ID="${DISCORD_GUILD_ID//”/}"
DISCORD_GUILD_ID="${DISCORD_GUILD_ID//‘/}"
DISCORD_GUILD_ID="${DISCORD_GUILD_ID//’/}"

echo "Checking Discord bot rollout for guild=${DISCORD_GUILD_ID}"

guild_json=$(api_get "/guilds/${DISCORD_GUILD_ID}")
check_for_discord_error "$guild_json"

guild_name=$(echo "$guild_json" | python -c 'import sys,json; d=json.load(sys.stdin); print(d.get("name","<unknown>"))')
echo "[OK] Guild reachable: ${guild_name} (${DISCORD_GUILD_ID})"

members_json=$(api_get "/guilds/${DISCORD_GUILD_ID}/members?limit=1000")
check_for_discord_error "$members_json"

bot_usernames=$(echo "$members_json" | python -c 'import sys,json
arr=json.load(sys.stdin)
for m in arr:
 u=m.get("user",{})
 if u.get("bot"):
  print(u.get("username",""))')

if [[ -z "${bot_usernames}" ]]; then
  echo "[FAIL] No bot members detected in guild"
  exit 4
fi

echo "Detected bot members:"
echo "${bot_usernames}" | sed 's/^/- /'

expected_bots=(
  "Luvatrix Ops Bot"
  "Carl-bot"
  "sesh"
  "MyRepoBot"
  "Ticket Tool"
)

echo
pass_count=0
fail_count=0
for bot in "${expected_bots[@]}"; do
  if echo "${bot_usernames}" | grep -iq "${bot}"; then
    echo "[OK] Found bot: ${bot}"
    pass_count=$((pass_count+1))
  else
    echo "[WARN] Bot not found: ${bot}"
    fail_count=$((fail_count+1))
  fi
done

echo
channels_json=$(api_get "/guilds/${DISCORD_GUILD_ID}/channels")
check_for_discord_error "$channels_json"

required_channels=(
  "welcome"
  "onboarding-checklist"
  "milestones-gantt"
  "team-runtime-board"
  "testing-ci"
  "risk-incident-log"
  "exec-dashboard"
)

channel_names=$(echo "$channels_json" | python -c 'import sys,json
arr=json.load(sys.stdin)
for c in arr:
 if c.get("type") == 0:
  print(c.get("name",""))')

for channel in "${required_channels[@]}"; do
  if echo "$channel_names" | grep -qx "$channel"; then
    echo "[OK] Channel exists: #${channel}"
    pass_count=$((pass_count+1))
  else
    echo "[FAIL] Missing channel: #${channel}"
    fail_count=$((fail_count+1))
  fi
done

echo
if [[ $fail_count -eq 0 ]]; then
  echo "Rollout check: PASS (${pass_count} checks)"
  exit 0
fi

echo "Rollout check: ATTENTION (${pass_count} passed, ${fail_count} issues)"
exit 1
