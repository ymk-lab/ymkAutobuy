#!/usr/bin/env bash
# Ephemeral trycloudflare.com URL (NOT permanent). For smoke tests only.
set -euo pipefail
PORT="${QRESEARCH_UI_PORT:-8787}"
BIN="${CLOUDFLARED_BIN:-/tmp/cloudflared}"
if [[ ! -x "$BIN" ]]; then
  curl -fsSL -o "$BIN" https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
  chmod +x "$BIN"
fi
exec "$BIN" tunnel --url "http://127.0.0.1:${PORT}"
