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

  # First-time / missed windows: Persistent= only helps after a timer has
  # already fired once. If latest_signal.asof is older than the last completed
  # US cash session (Mon–Fri), start the oneshot service now (same unit the
  # timer uses — not a one-off ad-hoc script).
  if [[ "${QRESEARCH_CATCHUP_SIGNAL:-1}" == "1" ]]; then
    SIG_JSON="$REPO_ROOT/examples/data/structure_gate_v13_paper/latest_signal.json"
    NEED_CATCHUP="$(
      python3 - "$SIG_JSON" <<'PY'
import json, sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

path = Path(sys.argv[1])
et = ZoneInfo("America/New_York")
now = datetime.now(et)
# Last session date whose 16:30 signal should already exist.
# Before 16:30 ET on a weekday → expect previous session; else today (if weekday).
d = now.date()
if now.weekday() >= 5:  # Sat/Sun → Friday
    d = d - timedelta(days=now.weekday() - 4)
elif (now.hour, now.minute) < (16, 30):
    d = d - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
expect = d.isoformat()
asof = None
if path.is_file():
    try:
        asof = str(json.loads(path.read_text()).get("asof") or "")[:10]
    except Exception:
        asof = None
print(asof or "missing", expect, file=sys.stderr)
print("1" if (not asof or asof < expect) else "0")
PY
    )" || NEED_CATCHUP="0"
    if [[ "$NEED_CATCHUP" == "1" ]]; then
      echo "==> signal stale vs last US session — starting qresearch-paper-signal.service"
      systemctl start qresearch-paper-signal.service || echo "WARN: catch-up signal failed"
      systemctl status qresearch-paper-signal.service --no-pager -l | head -30 || true
    else
      echo "==> latest_signal asof is current for last US session — no catch-up"
    fi
  fi
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

# Always bounce API so UI/status pick up new code + latest_signal/diagnose files.
if systemctl list-unit-files qresearch-api.service >/dev/null 2>&1; then
  systemctl restart qresearch-api.service || echo "WARN: restart qresearch-api failed"
  systemctl --no-pager --full status qresearch-api.service | head -20 || true
fi

echo "Start/restart API/OpenD with:"
echo "  systemctl restart qresearch-opend qresearch-api"
echo "  systemctl status qresearch-api --no-pager | head -20"
echo "Check schedule:"
echo "  systemctl list-timers 'qresearch-paper-*' --no-pager"
echo "  journalctl -u qresearch-paper-signal.service -n 50 --no-pager"
