#!/usr/bin/env bash
# Install/refresh systemd units from repo templates (never raw-cp REPLACE_USER).
# Usage: sudo bash deploy/vps/bin/sync-systemd.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
VPS="$(cd "$HERE/.." && pwd)"
APP_USER="${QRESEARCH_USER:-${SUDO_USER:-$USER}}"
REPO_ROOT="${QRESEARCH_ROOT:-$ROOT}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

if ! id "$APP_USER" >/dev/null 2>&1; then
  echo "User $APP_USER not found; set QRESEARCH_USER=..." >&2
  exit 1
fi

for unit in qresearch-opend.service qresearch-api.service; do
  src="$VPS/systemd/$unit"
  dst="/etc/systemd/system/$unit"
  if [[ ! -f "$src" ]]; then
    echo "missing $src" >&2
    exit 1
  fi
  sed -e "s|/opt/qresearch|$REPO_ROOT|g" -e "s|REPLACE_USER|$APP_USER|g" "$src" >"$dst"
  echo "wrote $dst (user=$APP_USER root=$REPO_ROOT)"
done

systemctl daemon-reload
echo "daemon-reload done"
echo "Start/restart with:"
echo "  systemctl restart qresearch-opend qresearch-api"
echo "  systemctl status qresearch-api --no-pager | head -20"
