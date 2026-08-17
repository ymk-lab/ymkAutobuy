#!/usr/bin/env bash
# If latest_signal.asof is behind the last completed US cash session, start the
# same oneshot the 16:30 timer uses. Safe to run often (watchdog / sync).
#
# Does NOT invoke the paper python job directly — only systemctl start.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
REPO_ROOT="${QRESEARCH_ROOT:-$ROOT}"
SIG_JSON="${QRESEARCH_SG_PAPER_OUT:-$REPO_ROOT/examples/data/structure_gate_v13_paper}/latest_signal.json"
UNIT="${QRESEARCH_SIGNAL_UNIT:-qresearch-paper-signal.service}"
LOCK="${XDG_RUNTIME_DIR:-/run}/qresearch-ensure-paper-signal.lock"
mkdir -p "$(dirname "$LOCK")" 2>/dev/null || LOCK="/tmp/qresearch-ensure-paper-signal.lock"

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "ensure-paper-signal: another instance holds lock — skip"
  exit 0
fi

eval "$(
  python3 - "$SIG_JSON" <<'PY'
import json, sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

path = Path(sys.argv[1])
et = ZoneInfo("America/New_York")
now = datetime.now(et)
d = now.date()
if now.weekday() >= 5:  # Sat/Sun → prior Friday
    d = d - timedelta(days=now.weekday() - 4)
elif (now.hour, now.minute) < (16, 30):
    d = d - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
expect = d.isoformat()
asof = ""
if path.is_file():
    try:
        asof = str(json.loads(path.read_text()).get("asof") or "")[:10]
    except Exception:
        asof = ""
stale = (not asof) or (asof < expect)
# shell-safe
def q(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"

print(f"NEED={1 if stale else 0}")
print(f"EXPECT={q(expect)}")
print(f"ASOF={q(asof or 'missing')}")
print(f"ET_NOW={q(now.isoformat())}")
PY
)"

echo "ensure-paper-signal: asof=$ASOF expect=$EXPECT et_now=$ET_NOW need=$NEED"

if [[ "$NEED" != "1" ]]; then
  echo "ensure-paper-signal: fresh — no start"
  exit 0
fi

STATE="$(systemctl is-active "$UNIT" 2>/dev/null || true)"
if [[ "$STATE" == "activating" || "$STATE" == "active" ]]; then
  echo "ensure-paper-signal: $UNIT already $STATE — wait"
  exit 0
fi

echo "ensure-paper-signal: stale — systemctl start $UNIT"
systemctl start "$UNIT"
systemctl status "$UNIT" --no-pager -l | head -25 || true
