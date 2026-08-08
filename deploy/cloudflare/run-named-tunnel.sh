#!/usr/bin/env bash
# Permanent hostname via Cloudflare named tunnel.
# Requires CLOUDFLARE_TUNNEL_TOKEN in .env (from Zero Trust → Tunnels).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

BIN="${CLOUDFLARED_BIN:-/tmp/cloudflared}"
if [[ ! -x "$BIN" ]]; then
  echo "downloading cloudflared…"
  curl -fsSL -o "$BIN" https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
  chmod +x "$BIN"
fi

if [[ -z "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]]; then
  echo "Missing CLOUDFLARE_TUNNEL_TOKEN."
  echo "Create a Named Tunnel in Cloudflare Zero Trust, route http://127.0.0.1:${QRESEARCH_UI_PORT:-8787},"
  echo "then put the tunnel token into .env as CLOUDFLARE_TUNNEL_TOKEN=..."
  exit 2
fi

exec "$BIN" tunnel --no-autoupdate run --token "$CLOUDFLARE_TUNNEL_TOKEN"
