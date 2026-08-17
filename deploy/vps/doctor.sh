#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
LOCAL="${QRESEARCH_VPS_SECRETS:-$HERE/secrets/local}"

echo "== repo $ROOT"
echo "== secrets $LOCAL"
bash "$HERE/bin/require-secrets.sh" || true

if [[ -f "$ROOT/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
fi
export PYTHONPATH="$ROOT/src"
python3 - <<'PY'
from qresearch.brokers.futu import has_futu_opend
print("has_futu_opend=", has_futu_opend())
PY

echo "== systemd (if installed)"
systemctl is-active qresearch-opend.service 2>/dev/null || echo "opend: not installed/active"
systemctl is-active qresearch-api.service 2>/dev/null || echo "api: not installed/active"

echo "== paper timers"
systemctl list-timers 'qresearch-paper-*' --no-pager 2>/dev/null || echo "timers: not installed"
systemctl is-enabled qresearch-paper-signal.timer 2>/dev/null || echo "signal.timer: not enabled"
systemctl is-enabled qresearch-paper-signal-watchdog.timer 2>/dev/null || echo "watchdog.timer: not enabled"
systemctl is-enabled qresearch-paper-once.timer 2>/dev/null || echo "once.timer: not enabled"

echo "== crontab (backup; timers are primary)"
crontab -l 2>/dev/null | head -20 || echo "(no crontab for $USER)"

echo "== latest signal vs expected US session"
SIG="$ROOT/examples/data/structure_gate_v13_paper/latest_signal.json"
python3 - "$SIG" <<'PY'
import json, sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

path = Path(sys.argv[1])
et = ZoneInfo("America/New_York")
now = datetime.now(et)
d = now.date()
if now.weekday() >= 5:
    d = d - timedelta(days=now.weekday() - 4)
elif (now.hour, now.minute) < (16, 30):
    d = d - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
expect = d.isoformat()
asof = mode = target = None
if path.is_file():
    try:
        s = json.loads(path.read_text())
        asof = s.get("asof")
        mode = s.get("mode")
        target = s.get("target")
    except Exception as exc:
        print("signal json error:", exc)
else:
    print("missing", path)
print("et_now=", now.isoformat())
print("expect_asof=", expect)
print("asof=", asof, "mode=", mode, "target=", target)
print("stale=", (not asof) or str(asof)[:10] < expect)
PY

echo "== last signal service runs"
journalctl -u qresearch-paper-signal.service -n 15 --no-pager 2>/dev/null || true
journalctl -u qresearch-paper-signal-watchdog.service -n 8 --no-pager 2>/dev/null || true

echo "== ports"
ss -ltn 2>/dev/null | grep -E ':11111|:8787' || netstat -ltn 2>/dev/null | grep -E ':11111|:8787' || true
