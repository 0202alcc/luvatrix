#!/bin/bash
# Spotify Light sync + relaunch + tunnel for Alec's Mac (paste 3: merged build).
# Lands origin/main once main carries Spotify Light (PR #358); until then it
# lands origin/spotify-light-desktop — the branch with the merged build
# (rounds 11-25) — and says so loudly. Tip SHAs resolve at fetch time, so
# rerun this same script after #358 merges and it follows main forward.
# Alec runs ONE short line: bash <this file>. It self-checks and prints
# TUNNEL_URL + TOKEN at the end to paste back into chat.
cd /Users/alec/Documents/Projects/luvatrix-spotify-light || { echo "REPO PATH NOT FOUND - stop"; exit 1; }
git fetch origin main spotify-light-desktop || echo "WARN: fetch failed"
MAIN_TIP=$(git rev-parse origin/main 2>/dev/null) || { echo "STOP: cannot resolve origin/main"; exit 1; }
if git ls-tree origin/main --name-only examples/ 2>/dev/null | grep -q '^examples/spotify_light$'; then
  TARGET=$MAIN_TIP
  BRANCH=main
else
  echo "NOTE: origin/main ($MAIN_TIP) has no Spotify Light yet - PR #358 still open."
  echo "Landing origin/spotify-light-desktop instead (the merged build: rounds 11-25)."
  TARGET=$(git rev-parse origin/spotify-light-desktop 2>/dev/null) || { echo "STOP: cannot resolve origin/spotify-light-desktop"; exit 1; }
  BRANCH=spotify-light-desktop
fi
git checkout -B "$BRANCH" "$TARGET" || { echo "STOP: checkout failed - tree left unchanged"; exit 1; }
echo "Landed commit: $(git log --oneline -1)"
pkill -f 'run-app examples/spotify_light' 2>/dev/null
pkill -f 'cloudflared tunnel' 2>/dev/null
sleep 2
SESSION=examples/spotify_light/.luvatrix/mcp-session.json
rm -f "$SESSION"
nohup uv run python main.py run-app examples/spotify_light --render macos-metal --mcp > /tmp/sl-app.log 2>&1 &
for i in $(seq 1 45); do [ -f "$SESSION" ] && break; sleep 1; done
if [ ! -f "$SESSION" ]; then echo "APP NEVER WROTE SESSION FILE - send /tmp/sl-app.log"; fi
LOCAL_URL=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['url'])" "$SESSION" 2>/dev/null)
TOKEN=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['token'])" "$SESSION" 2>/dev/null)
CF=$(command -v cloudflared || true)
if [ -z "$CF" ] && [ -x /tmp/cloudflared ]; then CF=/tmp/cloudflared; fi
if [ -z "$CF" ]; then
  ARCH=$(uname -m); [ "$ARCH" = "x86_64" ] && ARCH=amd64
  curl -sL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-${ARCH}.tgz" -o /tmp/cf.tgz && tar xzf /tmp/cf.tgz -C /tmp && CF=/tmp/cloudflared
fi
nohup "$CF" tunnel --url "$LOCAL_URL" --no-autoupdate > /tmp/sl-tunnel.log 2>&1 &
TUNNEL=""
for i in $(seq 1 30); do TUNNEL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' /tmp/sl-tunnel.log 2>/dev/null | head -1); [ -n "$TUNNEL" ] && break; sleep 1; done
if [ -z "$TUNNEL" ]; then echo "NO TUNNEL URL AFTER 30s - send /tmp/sl-tunnel.log"; fi
sleep 2
echo "local check: $(curl -s --http1.1 -m 5 -X POST "$LOCAL_URL" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"app_state","arguments":{}}}' | head -c 80)"
echo "tunnel check: $(curl -s --http1.1 -m 8 -X POST "$TUNNEL/mcp" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"app_state","arguments":{}}}' | head -c 80)"
echo "=========================================="
echo "TUNNEL_URL=$TUNNEL/mcp"
echo "TOKEN=$TOKEN"
echo "=========================================="
echo "Paste those two lines back into the chat."
