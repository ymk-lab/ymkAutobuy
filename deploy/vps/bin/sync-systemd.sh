#!/usr/bin/env bash
# Install/refresh systemd units + paper timers (never raw-cp REPLACE_USER).
# Usage: sudo bash deploy/vps/bin/sync-systemd.sh
# Optional: QRESEARCH_USER=root QRESEARCH_ROOT=/opt/qresearch
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
VPS="$(cd "$HERE/.." && pwd)"
APP_USER="${QRESEARCH_USER:-${SUDO_USER:-$USER}}"
REPO_ROOT="${QRESEARCH_ROOT:-$ROOT}"
ENABLE_TIMERS="${QRESEARCH_ENABLE_TIMERS:-1}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

if ! id "$APP_USER" >/dev/null 2>&1; then
  echo "User $APP_USER not found; set QRESEARCH_USER=..." >&2
  exit 1
fi

UNITS=(
  qresearch-opend.service
  qresearch-api.service
  qresearch-paper-signal.service
  qresearch-paper-signal.timer
  qresearch-paper-once.service
  qresearch-paper-once.timer
)

for unit in "${UNITS[@]}"; do
  src="$VPS/systemd/$unit"
  dst="/etc/systemd/system/$unit"
  if [[ ! -f "$src" ]]; then
    echo "missing $src" >&2
    exit 1
  fi
  sed -e "s|/opt/qresearch|$REPO_ROOT|g" -e "s|REPLACE_USER|$APP_USER|g" "$src" >"$dst"
  echo "wrote $dst (user=$APP_USER root=$REPO_ROOT)"
done

# Keep scripts executable (cron/timer invoke them directly).
chmod +x "$VPS"/bin/*.sh "$VPS/doctor.sh" "$VPS/install.sh" 2>/dev/null || true

systemctl daemon-reload
echo "daemon-reload done"

if [[ "$ENABLE_TIMERS" == "1" ]]; then
  systemctl enable --now qresearch-paper-signal.timer qresearch-paper-once.timer
  echo "==> timers enabled"
  systemctl list-timers 'qresearch-paper-*' --no-pager || true
fi

# Best-effort: also install user crontab from example (timers are primary).
if [[ "${QRESEARCH_INSTALL_CRONTAB:-1}" == "1" ]]; then
  if command -v crontab >/dev/null 2>&1; then
    cron_src="$VPS/crontab.example"
    # Rewrite paths if repo not at /opt/qresearch
    cron_tmp="$(mktemp)"
    sed -e "s|/opt/qresearch|$REPO_ROOT|g" "$cron_src" >"$cron_tmp"
    crontab -u "$APP_USER" "$cron_tmp"
    rm -f "$cron_tmp"
    echo "==> crontab installed for $APP_USER (backup timers still primary)"
  else
    echo "WARN: crontab binary missing — timers only"
  fi
fi

echo "Start/restart API/OpenD with:"
echo "  systemctl restart qresearch-opend qresearch-api"
echo "  systemctl status qresearch-api --no-pager | head -20"
echo "Check schedule:"
echo "  systemctl list-timers 'qresearch-paper-*' --no-pager"
echo "  journalctl -u qresearch-paper-signal.service -n 50 --no-pager"
