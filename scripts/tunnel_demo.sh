#!/usr/bin/env bash
# The demo (scripts/demo.py) at a public HTTPS address, through a free Cloudflare quick tunnel.
#
#     scripts/tunnel_demo.sh             # the demo behind https://<random>.trycloudflare.com
#     scripts/tunnel_demo.sh --reset     # any demo.py option passes through
#     API_PORT=8004 WEB_PORT=3004 scripts/tunnel_demo.sh
#
# A quick tunnel needs no Cloudflare account or domain, but its address is new every time it starts. The API only
# accepts sign-ins from the origins in AUTH_AUTHORIZED_PARTIES, so this starts the tunnel first and adds its address
# to that list for this run. demo.py reads .env with load_dotenv, which never overrides a variable already set.
# The address is also written to .demo/url. Ctrl-C (or stopping the service) stops the demo and the tunnel.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_PORT="${API_PORT:-8010}"
WEB_PORT="${WEB_PORT:-3000}"
LOGS="$ROOT/.demo"
mkdir -p "$LOGS"
rm -f "$LOGS/url"

command -v cloudflared >/dev/null || { echo "cloudflared isn't installed: see README → Share it publicly." >&2; exit 1; }

cloudflared tunnel --no-autoupdate --url "http://localhost:$WEB_PORT" >"$LOGS/tunnel.log" 2>&1 &
TUNNEL=$!
trap 'kill "$TUNNEL" 2>/dev/null || true' EXIT

URL=""
for _ in $(seq 60); do
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOGS/tunnel.log" | head -1 || true)"
  [ -n "$URL" ] && break
  kill -0 "$TUNNEL" 2>/dev/null || { echo "cloudflared stopped:" >&2; tail -15 "$LOGS/tunnel.log" >&2; exit 1; }
  sleep 1
done
[ -n "$URL" ] || { echo "No tunnel address after a minute: see .demo/tunnel.log" >&2; exit 1; }
echo "$URL" >"$LOGS/url"
echo "Public address: $URL   (also in .demo/url)"

export AUTH_AUTHORIZED_PARTIES="http://localhost:$WEB_PORT,http://127.0.0.1:$WEB_PORT,$URL"
"$ROOT/.venv/bin/python" "$ROOT/scripts/demo.py" --api-port "$API_PORT" --web-port "$WEB_PORT" "$@"
