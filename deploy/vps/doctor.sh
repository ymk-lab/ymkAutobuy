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
systemctl is-enabled qresearch-paper-once.timer 2>/dev/null || echo "once.timer: not enabled"

echo "== crontab (backup; timers are primary)"
crontab -l 2>/dev/null | head -20 || echo "(no crontab for $USER)"

echo "== latest signal"
SIG="$ROOT/examples/data/structure_gate_v13_paper/latest_signal.json"
if [[ -f "$SIG" ]]; then
  python3 - <<PY
import json
from pathlib import Path
s=json.loads(Path("$SIG").read_text())
print("asof=", s.get("asof"), "mode=", s.get("mode"), "target=", s.get("target"))
PY
else
  echo "missing $SIG"
fi

echo "== ports"
ss -ltn 2>/dev/null | grep -E ':11111|:8787' || netstat -ltn 2>/dev/null | grep -E ':11111|:8787' || true
