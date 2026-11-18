#!/bin/bash
# Spotify Light sync + relaunch + tunnel for Alec's Mac (paste 2: round 13).
# Alec runs ONE short line: bash <this file>. It self-checks and prints
# TUNNEL_URL + TOKEN at the end to paste back into chat.
TARGET=0f9970302e17bf6d5f709bcba16c91104156a9c6
cd /Users/alec/Documents/Projects/luvatrix-spotify-light || { echo "REPO PATH NOT FOUND - stop"; exit 1; }
git fetch origin || echo "WARN: fetch origin failed"
git fetch origin "$TARGET" || echo "WARN: fetch target failed"
git checkout -B feature/liquid-glass-3d01 "$TARGET" || echo "WARN: checkout failed"
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
