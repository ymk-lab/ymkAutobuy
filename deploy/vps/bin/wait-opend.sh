#!/usr/bin/env bash
# Wait until OpenD TCP port accepts connections.
set -euo pipefail

HOST="${1:-127.0.0.1}"
PORT="${2:-11111}"
TRIES="${3:-60}"

for ((i = 1; i <= TRIES; i++)); do
  if command -v nc >/dev/null 2>&1; then
    if nc -z "$HOST" "$PORT" >/dev/null 2>&1; then
      echo "OpenD up ${HOST}:${PORT} (try $i)"
      exit 0
    fi
  else
    if python3 -c "import socket;s=socket.socket();s.settimeout(1);s.connect(('${HOST}',${PORT}));s.close()" 2>/dev/null; then
      echo "OpenD up ${HOST}:${PORT} (try $i)"
      exit 0
    fi
  fi
  sleep 2
done
echo "OpenD not reachable ${HOST}:${PORT} after ${TRIES} tries" >&2
exit 1
